from __future__ import annotations

import asyncio
import os
import select
import signal
import socket
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from io import TextIOWrapper
from types import FrameType
from typing import Any, Callable, TextIO

import anyio
import mcp.types as mcp_types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage


_EOF_SENTINEL = object()


class _InterruptState:
    def __init__(self, *, message: str, stderr: TextIO) -> None:
        self._message = message
        self._stderr = stderr
        self._lock = threading.Lock()
        self._interrupt_count = 0
        self.interrupted = False
        self._shutdown_printed = False
        self._shutdown_loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_task: asyncio.Task[Any] | None = None
        self._wake_reader: Callable[[], None] | None = None

    def handle_sigint(self, _signum: int, _frame: FrameType | None) -> None:
        with self._lock:
            self._interrupt_count += 1
            if self._interrupt_count == 1:
                self.interrupted = True
                self._print_shutdown_locked()
                self._cancel_main_task_locked()
                return
        raise KeyboardInterrupt

    def bind_shutdown_target(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[Any],
        wake_reader: Callable[[], None],
    ) -> None:
        with self._lock:
            self._shutdown_loop = loop
            self._shutdown_task = task
            self._wake_reader = wake_reader

    def clear_shutdown_target(self) -> None:
        with self._lock:
            self._shutdown_loop = None
            self._shutdown_task = None
            self._wake_reader = None

    def print_shutdown_once(self) -> None:
        with self._lock:
            self.interrupted = True
            self._print_shutdown_locked()

    def _print_shutdown_locked(self) -> None:
        if self._shutdown_printed:
            return
        print(self._message, file=self._stderr, flush=True)
        self._shutdown_printed = True

    def _cancel_main_task_locked(self) -> None:
        loop = self._shutdown_loop
        task = self._shutdown_task
        wake_reader = self._wake_reader
        if wake_reader is not None:
            wake_reader()
        if loop is None or task is None or task.done():
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            return


@contextmanager
def _sigint_handler(state: _InterruptState):
    try:
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, state.handle_sigint)
    except ValueError:
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


@asynccontextmanager
async def interruptible_stdio_server(
    *,
    interrupted: Callable[[], bool],
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
):
    input_stream = stdin or TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    output_stream = stdout or TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    stdin_fd = input_stream.fileno()

    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    loop = asyncio.get_running_loop()
    incoming: asyncio.Queue[SessionMessage | Exception | object] = asyncio.Queue()
    wake_reader_sock, wake_writer_sock = socket.socketpair()
    wake_reader_sock.setblocking(False)
    wake_writer_sock.setblocking(False)
    wake_fd = wake_reader_sock.fileno()
    wake_lock = threading.Lock()
    wake_requested = False

    def publish(item: SessionMessage | Exception | object) -> None:
        try:
            loop.call_soon_threadsafe(incoming.put_nowait, item)
        except RuntimeError:
            return

    def wake_stdin_reader() -> None:
        nonlocal wake_requested
        with wake_lock:
            if wake_requested:
                return
            wake_requested = True
        try:
            wake_writer_sock.send(b"\x00")
        except OSError:
            return

    def stdin_reader() -> None:
        buffered = bytearray()
        while True:
            try:
                ready, _, _ = select.select([stdin_fd, wake_fd], [], [])
            except Exception as exc:
                if interrupted():
                    publish(_EOF_SENTINEL)
                else:
                    publish(exc)
                return
            if wake_fd in ready:
                publish(_EOF_SENTINEL)
                return
            if stdin_fd not in ready:
                continue
            try:
                chunk = os.read(stdin_fd, 65536)
            except Exception as exc:
                if interrupted():
                    publish(_EOF_SENTINEL)
                else:
                    publish(exc)
                return
            if not chunk:
                if buffered:
                    try:
                        message = mcp_types.JSONRPCMessage.model_validate_json(buffered.decode("utf-8"))
                    except Exception as exc:  # pragma: no cover
                        publish(exc)
                    else:
                        publish(SessionMessage(message))
                publish(_EOF_SENTINEL)
                return
            buffered.extend(chunk)
            while True:
                newline = buffered.find(b"\n")
                if newline < 0:
                    break
                raw_line = bytes(buffered[: newline + 1])
                del buffered[: newline + 1]
                try:
                    message = mcp_types.JSONRPCMessage.model_validate_json(raw_line.decode("utf-8"))
                except Exception as exc:  # pragma: no cover
                    publish(exc)
                    continue
                publish(SessionMessage(message))

    reader_thread = threading.Thread(
        target=stdin_reader,
        name="frida-analykit-mcp-stdin",
        daemon=True,
    )
    reader_thread.start()

    async def stdin_forwarder() -> None:
        async with read_stream_writer:
            while True:
                item = await incoming.get()
                if item is _EOF_SENTINEL:
                    break
                await read_stream_writer.send(item)

    async def stdout_writer() -> None:
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    payload = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    await anyio.to_thread.run_sync(output_stream.write, payload + "\n")
                    await anyio.to_thread.run_sync(output_stream.flush)
        except (BrokenPipeError, OSError, ValueError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_forwarder)
        tg.start_soon(stdout_writer)
        try:
            yield read_stream, write_stream, wake_stdin_reader
        finally:
            wake_stdin_reader()
            try:
                await asyncio.shield(write_stream.aclose())
            finally:
                await asyncio.shield(asyncio.to_thread(reader_thread.join, 1.0))
                wake_reader_sock.close()
                wake_writer_sock.close()


async def _run_server(server: FastMCP[Any], state: _InterruptState) -> None:
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("MCP stdio runner task is unavailable")
    try:
        async with interruptible_stdio_server(interrupted=lambda: state.interrupted) as (
            read_stream,
            write_stream,
            wake_stdin_reader,
        ):
            state.bind_shutdown_target(loop=asyncio.get_running_loop(), task=task, wake_reader=wake_stdin_reader)
            await server._mcp_server.run(
                read_stream,
                write_stream,
                server._mcp_server.create_initialization_options(),
            )
    except asyncio.CancelledError:
        if state.interrupted:
            return
        raise
    finally:
        state.clear_shutdown_target()


def serve_stdio(server: FastMCP[Any], *, shutdown_message: str, stderr: TextIO | None = None) -> int:
    stream = stderr or sys.stderr
    state = _InterruptState(message=shutdown_message, stderr=stream)
    try:
        with _sigint_handler(state):
            anyio.run(_run_server, server, state)
    except KeyboardInterrupt:
        state.print_shutdown_once()
        return 130
    return 130 if state.interrupted else 0
