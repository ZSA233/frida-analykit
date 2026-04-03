import pytest

from frida_analykit.mcp.docs import MCPDocsProvider


@pytest.mark.parametrize(
    ("reader", "keywords"),
    [
        (
            "resource_index_markdown",
            (
                "session_open_quick",
                "frida://service/config",
                "session_recover",
            ),
        ),
        (
            "resource_config_markdown",
            (
                "frida://service/config",
                "quick_path",
                "config.toml",
                "session_history_root",
                "{yyyymmdd-hhmmss-shortid}",
            ),
        ),
            (
                "resource_quickstart_markdown",
                (
                    "generated `index.ts` is the effective quick compile entry",
                    "explicit original binding references",
                    "bootstrap_source is inlined",
                    "bootstrap_path remains a separate import",
                    "self-contained",
                ),
            ),
        (
            "resource_tools_markdown",
            (
                "session_open_quick",
                "install_snippet",
                'template="minimal"',
                "elf_enhanced",
                "effective quick compile entry",
                "bootstrap_source is inlined",
                "session_history_root",
                "live in-memory snippet state",
                "self-contained",
            ),
        ),
        (
            "resource_workflow_markdown",
            (
                "effective compile entry",
                "{yyyymmdd-hhmmss-shortid}",
                "session_workspace",
                "session_recover",
                "broken",
                "self-contained",
            ),
        ),
        (
            "resource_recovery_markdown",
            (
                "session_recover",
                "session_close",
                "broken",
                "/rpc",
                "session_workspace",
            ),
        ),
    ],
)
def test_packaged_docs_cover_core_mcp_contract(reader: str, keywords: tuple[str, ...]) -> None:
    provider = MCPDocsProvider()
    document = getattr(provider, reader)().lower()

    for keyword in keywords:
        assert keyword.lower() in document
