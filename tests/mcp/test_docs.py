from frida_analykit.mcp.docs import MCPDocsProvider


def test_packaged_docs_cover_core_mcp_workflow_terms() -> None:
    provider = MCPDocsProvider()

    index_doc = provider.resource_index_markdown()
    config_doc = provider.resource_config_markdown()
    tools_doc = provider.resource_tools_markdown()
    recovery_doc = provider.resource_recovery_markdown()

    assert "session_open" in index_doc
    assert "frida://service/config" in config_doc
    assert "config.toml" in config_doc
    assert "bootstrap_path" in config_doc
    assert "bootstrap_source" in config_doc
    assert "install_snippet" in tools_doc
    assert "session_recover" in recovery_doc
    assert "session_close" in recovery_doc
    assert "broken" in recovery_doc
    assert "/rpc" in recovery_doc
