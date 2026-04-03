from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from frida_analykit.mcp.history import SessionHistoryManager


def test_session_history_allocates_timestamped_labels_with_short_ids(tmp_path: Path) -> None:
    current = {"value": datetime(2026, 4, 3, 15, 30, 15, tzinfo=timezone.utc)}
    manager = SessionHistoryManager(tmp_path / "sessions", now_fn=lambda: current["value"])

    record = manager.begin_session(
        open_kind="explicit",
        requested_mode="attach",
        requested_pid=123,
        app="com.example.demo",
        config_path=Path("/tmp/config.toml"),
        prepared_artifact=None,
    )

    expected_prefix = current["value"].astimezone().strftime("%Y%m%d-%H%M%S")
    assert record.session_label.startswith(f"{expected_prefix}-")
    assert len(record.session_id) == 8
    assert record.session_label.endswith(record.session_id)
    assert record.root.is_dir()
    assert record.workspace_root.is_dir()
    assert record.snippets_root.is_dir()


def test_session_history_uses_unique_labels_within_same_second(tmp_path: Path) -> None:
    now = datetime(2026, 4, 3, 15, 30, 15, tzinfo=timezone.utc)
    manager = SessionHistoryManager(tmp_path / "sessions", now_fn=lambda: now)

    first = manager.begin_session(
        open_kind="explicit",
        requested_mode="attach",
        requested_pid=1,
        app="com.example.one",
        config_path=Path("/tmp/one.toml"),
        prepared_artifact=None,
    )
    second = manager.begin_session(
        open_kind="explicit",
        requested_mode="attach",
        requested_pid=2,
        app="com.example.two",
        config_path=Path("/tmp/two.toml"),
        prepared_artifact=None,
    )

    prefix = now.astimezone().strftime("%Y%m%d-%H%M%S")
    assert first.session_label.startswith(f"{prefix}-")
    assert second.session_label.startswith(f"{prefix}-")
    assert first.session_label != second.session_label
    assert first.session_id != second.session_id


def test_session_history_persists_snippet_versions_with_safe_names(tmp_path: Path) -> None:
    tick = {"value": datetime(2026, 4, 3, 15, 30, 15, tzinfo=timezone.utc)}

    def now() -> datetime:
        value = tick["value"]
        tick["value"] = value + timedelta(seconds=1)
        return value

    manager = SessionHistoryManager(tmp_path / "sessions", now_fn=now)
    record = manager.begin_session(
        open_kind="quick",
        requested_mode="attach",
        requested_pid=123,
        app="com.example.demo",
        config_path=None,
        prepared_artifact=None,
    )

    first = manager.persist_snippet(record, name="dex dump/foo", source="console.log(1)\n", replaced=False)
    second = manager.persist_snippet(record, name="dex dump/foo", source="console.log(2)\n", replaced=True)
    manifest = manager.inspect(record.session_label)

    assert first.parent.name == "dex_dump_foo"
    assert first.name.endswith("-v0001.js")
    assert second.name.endswith("-v0002.js")
    assert first.read_text(encoding="utf-8") == "console.log(1)\n"
    assert second.read_text(encoding="utf-8") == "console.log(2)\n"
    assert manifest is not None
    assert manifest.snippets["dex dump/foo"].safe_name == "dex_dump_foo"
    assert len(manifest.snippets["dex dump/foo"].versions) == 2
    assert manifest.snippets["dex dump/foo"].state == "active"


def test_session_history_disambiguates_colliding_safe_names(tmp_path: Path) -> None:
    now = datetime(2026, 4, 3, 15, 30, 15, tzinfo=timezone.utc)
    manager = SessionHistoryManager(tmp_path / "sessions", now_fn=lambda: now)
    record = manager.begin_session(
        open_kind="quick",
        requested_mode="attach",
        requested_pid=123,
        app="com.example.demo",
        config_path=None,
        prepared_artifact=None,
    )

    first = manager.persist_snippet(record, name="a/b", source="console.log('slash')\n", replaced=False)
    second = manager.persist_snippet(record, name="a_b", source="console.log('underscore')\n", replaced=False)
    manifest = manager.inspect(record.session_label)

    assert first != second
    assert first.read_text(encoding="utf-8") == "console.log('slash')\n"
    assert second.read_text(encoding="utf-8") == "console.log('underscore')\n"
    assert manifest is not None
    assert manifest.snippets["a/b"].safe_name != manifest.snippets["a_b"].safe_name
