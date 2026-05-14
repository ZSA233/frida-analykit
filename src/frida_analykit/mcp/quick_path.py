from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import (
    QuickPathCheckSummary,
    QuickPathCompileProbeSummary,
    QuickPathReadinessSummary,
    QuickPathToolchainSummary,
)

_MISSING_STARTUP_SUMMARY_DETAIL = "startup quick-path warmup summary was not provided"


def default_quick_path_summary(*, cache_root: Path, checked_at: datetime) -> QuickPathReadinessSummary:
    return QuickPathReadinessSummary(
        state="failed",
        checked_at=checked_at,
        message=_MISSING_STARTUP_SUMMARY_DETAIL,
        cache_root=QuickPathCheckSummary(
            state="skipped",
            path=cache_root,
            detail=_MISSING_STARTUP_SUMMARY_DETAIL,
        ),
        npm=QuickPathCheckSummary(
            state="skipped",
            path=None,
            detail=_MISSING_STARTUP_SUMMARY_DETAIL,
        ),
        frida_compile=QuickPathCheckSummary(
            state="skipped",
            path=None,
            detail=_MISSING_STARTUP_SUMMARY_DETAIL,
        ),
        shared_toolchain=QuickPathToolchainSummary(
            state="skipped",
            root=cache_root / "_toolchains",
            agent_package_spec="unknown",
            detail=_MISSING_STARTUP_SUMMARY_DETAIL,
        ),
        compile_probe=QuickPathCompileProbeSummary(
            state="skipped",
            workspace_root=cache_root / "_startup_probe",
            bundle_path=cache_root / "_startup_probe" / "_agent.js",
            detail=_MISSING_STARTUP_SUMMARY_DETAIL,
            last_error=None,
        ),
    )
