import { RPCMsgType } from "../../message.js"
import { evalWithContext } from "./context.js"
import { enumerateObjectProperties, materializeArgument, previewRpcValue, resolveHandleSpec, resolveOwnedScopeSlot, RPCHandleSpec } from "./handles.js"
import { clearScope, deleteScopeValue, describeValueType, getEvalScope, saveScopeValue } from "./scope.js"

export const RPC_PROTOCOL_VERSION = 2
export const RPC_PROTOCOL_FEATURES = ["handle_ref", "async_scope"] as const


function createScopeResultMessage(type: RPCMsgType.SCOPE_CALL | RPCMsgType.SCOPE_EVAL, result: any, scopeId: string) {
    const slotId = saveScopeValue(scopeId, result)
    const preview = previewRpcValue(result)
    return {
        type,
        data: {
            id: slotId,
            type: describeValueType(result),
            result: preview.value,
            has_result: preview.hasValue,
        },
    }
}


function createScopeGetMessage(value: any) {
    const preview = previewRpcValue(value)
    return {
        type: RPCMsgType.SCOPE_GET,
        data: {
            value: preview.value,
            has_value: preview.hasValue,
        },
    }
}


export function rpcRuntimeInfo() {
    return {
        protocol_version: RPC_PROTOCOL_VERSION,
        features: [...RPC_PROTOCOL_FEATURES],
    }
}


export function enumerateObjProps(specOrSpecs: RPCHandleSpec | Array<RPCHandleSpec>, scopeId: string) {
    return {
        type: RPCMsgType.ENUMERATE_OBJ_PROPS,
        data: {
            props: enumerateObjectProperties(specOrSpecs, scopeId),
        },
    }
}


export function scopeCall(spec: RPCHandleSpec, args: Array<any>, scopeId: string) {
    const target = resolveHandleSpec(spec, scopeId, true)
    const resolvedArgs = args.map(value => materializeArgument(value, scopeId))
    return createScopeResultMessage(RPCMsgType.SCOPE_CALL, target(...resolvedArgs), scopeId)
}


export async function scopeCallAsync(spec: RPCHandleSpec, args: Array<any>, scopeId: string) {
    const target = resolveHandleSpec(spec, scopeId, true)
    const resolvedArgs = args.map(value => materializeArgument(value, scopeId))
    const result = await Promise.resolve(target(...resolvedArgs))
    return createScopeResultMessage(RPCMsgType.SCOPE_CALL, result, scopeId)
}


export function scopeEval(source: string, scopeId: string) {
    return createScopeResultMessage(
        RPCMsgType.SCOPE_EVAL,
        evalWithContext(source, getEvalScope(scopeId)),
        scopeId,
    )
}


export async function scopeEvalAsync(source: string, scopeId: string) {
    const result = await Promise.resolve(evalWithContext(source, getEvalScope(scopeId)))
    return createScopeResultMessage(RPCMsgType.SCOPE_EVAL, result, scopeId)
}


export function scopeGet(spec: RPCHandleSpec, scopeId: string, bind: boolean = false) {
    return createScopeGetMessage(resolveHandleSpec(spec, scopeId, bind))
}


export async function scopeGetAsync(spec: RPCHandleSpec, scopeId: string, bind: boolean = false) {
    const result = await Promise.resolve(resolveHandleSpec(spec, scopeId, bind))
    return createScopeGetMessage(result)
}


export function scopeSave(obj: any, scopeId: string) {
    return saveScopeValue(scopeId, obj)
}


export function scopeClear(scopeId: string) {
    clearScope(scopeId)
}


export function scopeDel(spec: RPCHandleSpec, scopeId: string) {
    const slotId = resolveOwnedScopeSlot(spec)
    if (slotId !== null) {
        deleteScopeValue(scopeId, slotId)
    }
}
