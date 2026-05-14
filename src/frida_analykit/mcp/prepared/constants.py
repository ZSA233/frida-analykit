from __future__ import annotations

import re

from ...scaffold import AGENT_PACKAGE_NAME
from .models import QuickCapability, QuickTemplate

MANIFEST_FILENAME = "prepared.json"
SCHEMA_VERSION = 7
BOOTSTRAP_FILE_STEM = "bootstrap.user"
ENV_TYPES_FILENAME = "frida-analykit-env.d.ts"
TOOLCHAIN_DIRNAME = "_toolchains"
STARTUP_PROBE_DIRNAME = "_startup_probe"
QUICK_TYPESCRIPT_VERSION = "^5.8.3"
QUICK_FRIDA_GUM_TYPES_VERSION = "^18.7.2"
OUTPUT_TAIL_LINES = 40
MISSING_FRIDA_COMPILE_MESSAGE = (
    "quick path requires `frida-compile` in the MCP environment PATH; "
    "fix the MCP environment and restart the server"
)
MISSING_NPM_MESSAGE = (
    "quick path requires `npm` in the MCP environment PATH to install or repair runtime dependencies"
)
BOOTSTRAP_RELATIVE_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*import(?:\s+type)?\s*(?:[\s\w{},*$]+\s+from\s+)?[\"'](?P<path>\.{1,2}/[^\"']+)[\"']",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*export(?:\s+type)?\s+(?:\*\s+from|{[\s\S]*?}\s+from)\s+[\"'](?P<path>\.{1,2}/[^\"']+)[\"']",
        re.MULTILINE,
    ),
    re.compile(r"\brequire\(\s*[\"'](?P<path>\.{1,2}/[^\"']+)[\"']\s*\)"),
    re.compile(r"\bimport\(\s*[\"'](?P<path>\.{1,2}/[^\"']+)[\"']\s*\)"),
)

CAPABILITY_IMPORTS: dict[QuickCapability, str] = {
    "rpc": f"{AGENT_PACKAGE_NAME}/rpc",
    "config": f"{AGENT_PACKAGE_NAME}/config",
    "bridges": f"{AGENT_PACKAGE_NAME}/bridges",
    "helper": f"{AGENT_PACKAGE_NAME}/helper",
    "process": f"{AGENT_PACKAGE_NAME}/process",
    "jni": f"{AGENT_PACKAGE_NAME}/jni",
    "ssl": f"{AGENT_PACKAGE_NAME}/ssl",
    "elf": f"{AGENT_PACKAGE_NAME}/elf",
    "dex": f"{AGENT_PACKAGE_NAME}/dex",
    "native_libssl": f"{AGENT_PACKAGE_NAME}/native/libssl",
    "native_libart": f"{AGENT_PACKAGE_NAME}/native/libart",
    "native_libc": f"{AGENT_PACKAGE_NAME}/native/libc",
}

CAPABILITY_RETAIN_EXPORTS: dict[QuickCapability, str] = {
    "config": "Config",
    "bridges": "Java",
    "helper": "help",
    "process": "proc",
    "jni": "JNIEnv",
    "ssl": "SSLTools",
    "elf": "ElfTools",
    "dex": "DexTools",
    "native_libssl": "Libssl",
    "native_libart": "Libart",
    "native_libc": "Libc",
}

TEMPLATE_CAPABILITIES: dict[QuickTemplate, tuple[QuickCapability, ...]] = {
    "minimal": (),
    "process_probe": ("helper", "process"),
    "java_bridge": ("bridges", "jni"),
    "dex_probe": ("dex",),
    "ssl_probe": ("ssl",),
    "elf_probe": ("elf",),
}

TEMPLATE_HINTS: dict[QuickTemplate, str] = {
    "minimal": "Keep target-specific probes in MCP eval_js or install_snippet calls.",
    "process_probe": "Process helpers are preloaded for fast memory-map and process-state checks.",
    "java_bridge": "Java and JNI bridge helpers are preloaded for Android runtime inspection.",
    "dex_probe": "Dex helpers are preloaded for loader enumeration and dex validation flows.",
    "ssl_probe": "SSL helpers are preloaded for keylog or libssl-oriented validation.",
    "elf_probe": "ELF helpers are preloaded for module, symbol, and hook validation.",
}
