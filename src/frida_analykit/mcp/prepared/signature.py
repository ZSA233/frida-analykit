from __future__ import annotations

import hashlib
import json

from .constants import SCHEMA_VERSION
from .models import BootstrapKind, QuickCapability, QuickTemplate


def signature_for_request(
    *,
    app: str,
    capabilities: tuple[QuickCapability, ...],
    template: QuickTemplate,
    bootstrap_kind: BootstrapKind,
    bootstrap_path: str | None,
    bootstrap_hash: str | None,
    bootstrap_source: str | None,
    host: str,
    device: str | None,
    path: str,
    datadir: str,
    stdout: str,
    stderr: str,
    dextools_output_dir: str,
    elftools_output_dir: str,
    nettools_output_dir: str,
    agent_package_spec: str,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "app": app,
        "capabilities": list(capabilities),
        "template": template,
        "bootstrap_kind": bootstrap_kind,
        "bootstrap_path": bootstrap_path,
        "bootstrap_hash": bootstrap_hash,
        "bootstrap_source": bootstrap_source,
        "host": host,
        "device": device,
        "path": path,
        "datadir": datadir,
        "stdout": stdout,
        "stderr": stderr,
        "dextools_output_dir": dextools_output_dir,
        "elftools_output_dir": elftools_output_dir,
        "nettools_output_dir": nettools_output_dir,
        "agent_package_spec": agent_package_spec,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
