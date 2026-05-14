from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..config import AppConfig
from .async_utils import to_thread
from .errors import MCPManagerError
from .protocols import ServerManagerProtocol

_REMOTE_BOOT_WAIT_SECONDS = 15.0
_REMOTE_BOOT_MAX_ATTEMPTS = 2
_REMOTE_BOOT_RECOVERY_DELAY_SECONDS = 1.0
_TRANSIENT_REMOTE_BOOT_MARKERS = (
    "cannot read properties of null (reading 'queryintentactivities')",
    "timed out trying to sync up with agent",
    "timeout was reached",
    "unexpectedly timed out while waiting for signal",
)


def _is_transient_remote_boot_failure(detail: str) -> bool:
    lowered = detail.strip().lower()
    return any(marker in lowered for marker in _TRANSIENT_REMOTE_BOOT_MARKERS)


@dataclass(slots=True)
class RemoteServerLease:
    config: AppConfig
    manager: ServerManagerProtocol
    boot_owned: bool = False
    _boot_task: asyncio.Task[None] | None = None
    _boot_error: BaseException | None = None

    async def ensure_ready(self, *, timeout_seconds: float = _REMOTE_BOOT_WAIT_SECONDS) -> None:
        last_detail = "timed out while waiting for the remote host"
        for attempt in range(1, _REMOTE_BOOT_MAX_ATTEMPTS + 1):
            status = await to_thread(self.manager.inspect_remote_server, self.config, probe_abi=False, probe_host=True)
            if getattr(status, "host_reachable", None):
                return

            running_pids = await to_thread(self.manager.list_remote_server_pids, self.config)
            if running_pids:
                detail = getattr(status, "host_error", None) or "unknown transport error"
                pid_list = ", ".join(str(pid) for pid in sorted(running_pids))
                raise MCPManagerError(
                    "remote frida-server is already running but the forwarded host is not reachable "
                    f"({detail}; pids: {pid_list}). Repair the device session first, or run "
                    "`frida-analykit server stop --config ...` before retrying."
                )

            if self._boot_task is None or self._boot_task.done():
                self._boot_error = None
                self._boot_task = asyncio.create_task(self._boot_worker())
                self.boot_owned = True

            last_detail = await self._wait_until_reachable(
                initial_status=status,
                timeout_seconds=timeout_seconds,
            )
            if last_detail is None:
                return

            if attempt < _REMOTE_BOOT_MAX_ATTEMPTS and _is_transient_remote_boot_failure(last_detail):
                # Some Android/Frida combinations can leave the just-stopped
                # server child in a transient bad state. Keep recovery scoped to
                # these known early boot errors, then retry from a clean forward.
                await self._recover_transient_boot_failure()
                continue
            break

        raise MCPManagerError(f"failed to boot remote frida-server: {last_detail}")

    async def _wait_until_reachable(
        self,
        *,
        initial_status: object,
        timeout_seconds: float,
    ) -> str | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        latest_status = initial_status
        while loop.time() < deadline:
            if self._boot_error is not None:
                return str(self._boot_error)
            latest_status = await to_thread(
                self.manager.inspect_remote_server,
                self.config,
                probe_abi=False,
                probe_host=True,
            )
            if getattr(latest_status, "host_reachable", None):
                return None
            if self._boot_task is not None and self._boot_task.done() and self._boot_error is None:
                break
            await asyncio.sleep(0.25)
        return getattr(latest_status, "host_error", None) or "timed out while waiting for the remote host"

    async def _recover_transient_boot_failure(self) -> None:
        try:
            await to_thread(self.manager.stop_remote_server, self.config)
        except Exception:
            pass
        if self._boot_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._boot_task), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self._boot_task = None
        self._boot_error = None
        self.boot_owned = False
        await asyncio.sleep(_REMOTE_BOOT_RECOVERY_DELAY_SECONDS)

    async def stop(self) -> None:
        if not self.boot_owned:
            return
        await to_thread(self.manager.stop_remote_server, self.config)
        if self._boot_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._boot_task), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self._boot_task = None
        self._boot_error = None
        self.boot_owned = False

    async def _boot_worker(self) -> None:
        try:
            await to_thread(self.manager.boot_remote_server, self.config, force_restart=False)
        except BaseException as exc:
            self._boot_error = exc
