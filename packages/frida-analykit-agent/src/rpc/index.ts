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

// Keep a single RPC side-effect assembly point so the `/rpc` export has one
// stable owner even as the surrounding source tree is reorganized.
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
