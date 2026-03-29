export const SCOPE_SLOT_PREFIX = "__frida_analykit_scope_"
const LEGACY_SCOPE_SLOT_PREFIX = "__get__$$"

const EVAL_SCOPES: { [key: string]: { [key: string]: any } } = {}

let ID_INCR = 0

export function isScopeSlotId(value: string): boolean {
    return value.startsWith(SCOPE_SLOT_PREFIX) || value.startsWith(LEGACY_SCOPE_SLOT_PREFIX)
}


export function getEvalScope(scopeId: string): { [key: string]: any } {
    return EVAL_SCOPES[scopeId] || {}
}


export function ensureEvalScope(scopeId: string): { [key: string]: any } {
    let scope = EVAL_SCOPES[scopeId]
    if (scope === undefined) {
        scope = {}
        EVAL_SCOPES[scopeId] = scope
    }
    return scope
}


export function saveScopeValue(scopeId: string, value: any): string {
    ID_INCR++
    const slotId = `${SCOPE_SLOT_PREFIX}${ID_INCR.toString(16)}`
    ensureEvalScope(scopeId)[slotId] = value
    return slotId
}


export function deleteScopeValue(scopeId: string, slotId: string): void {
    const scope = EVAL_SCOPES[scopeId]
    if (scope !== undefined) {
        delete scope[slotId]
    }
}


export function clearScope(scopeId: string): void {
    delete EVAL_SCOPES[scopeId]
}


export function readScopeValue(scopeId: string, slotId: string): any {
    return getEvalScope(scopeId)[slotId]
}


export function describeValueType(value: any): string {
    if (value === null) {
        return "null"
    }
    if (value instanceof Promise) {
        return "promise"
    }
    if (Array.isArray(value)) {
        return "array"
    }
    return typeof value
}
