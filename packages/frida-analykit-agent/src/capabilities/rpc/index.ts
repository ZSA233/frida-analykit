import {
    enumerateObjProps,
    rpcRuntimeInfo,
    scopeCall,
    scopeCallAsync,
    scopeClear,
    scopeDel,
    scopeEval,
    scopeEvalAsync,
    scopeGet,
    scopeGetAsync,
    scopeSave,
} from "./exports.js"

// Keep a single RPC side-effect assembly point so `/rpc` stays stable while the
// private implementation can move under `src/capabilities/`.
rpc.exports = {
    rpcRuntimeInfo,
    enumerateObjProps,
    scopeCall,
    scopeCallAsync,
    scopeEval,
    scopeEvalAsync,
    scopeClear,
    scopeGet,
    scopeGetAsync,
    scopeSave,
    scopeDel,
}
