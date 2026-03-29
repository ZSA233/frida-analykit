import "${agent_package_name}/rpc"

// `/rpc` now installs only the minimal structured RPC / REPL runtime.
// Import capabilities explicitly so frida-compile only bundles what you use.
// For example:
// import { help } from "${agent_package_name}/helper"
// import "${agent_package_name}/process"
// import { Java } from "${agent_package_name}/bridges"
// import { JNIEnv } from "${agent_package_name}/jni"
// import { SSLTools } from "${agent_package_name}/ssl"
// import { ElfTools } from "${agent_package_name}/elf"
// import { Libssl } from "${agent_package_name}/native/libssl"
