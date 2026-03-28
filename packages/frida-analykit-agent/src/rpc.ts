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
} from "./rpc/exports.js"

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
