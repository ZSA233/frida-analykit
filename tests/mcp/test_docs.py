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
                "mcp.toml",
                "session_root",
                "session_workspace",
                "config_path_raw",
                "{yyyymmdd-hhmmss-shortid}",
            ),
        ),
        (
            "resource_quickstart_markdown",
            (
                "session_open_quick",
                "template",
                "capabilities",
                "bootstrap_path",
                "bootstrap_source",
                "generated `index.ts`",
                "dextools.dumpalldex",
                "[dex] complete",
            ),
        ),
        (
            "resource_tools_markdown",
            (
                "session_open_quick",
                "install_snippet",
                "tail_logs",
                "template",
                "capabilities",
                "bootstrap_path",
                "bootstrap_source",
                "session_root",
                "session_workspace",
                "elf_enhanced",
                "live in-memory snippet state",
                "dextools.dumpalldex",
                "source = \"host\"",
            ),
        ),
        (
            "resource_workflow_markdown",
            (
                "session_open_quick",
                "install_snippet",
                "tail_logs",
                "session_close",
                "session_recover",
                "session_root",
                "session_workspace",
                "[dex] complete",
            ),
        ),
        (
            "resource_recovery_markdown",
            (
                "session_recover",
                "session_close",
                "broken",
                "/rpc",
                "session_root",
                "session_workspace",
                "tail_logs",
            ),
        ),
    ],
)
def test_packaged_docs_cover_core_mcp_contract(reader: str, keywords: tuple[str, ...]) -> None:
    provider = MCPDocsProvider()
    document = getattr(provider, reader)().lower()

    for keyword in keywords:
        assert keyword.lower() in document
