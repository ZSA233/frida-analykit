import { readScopeValue, isScopeSlotId } from "./scope.js"

export const HANDLE_REF_MARKER = "__frida_analykit_handle_ref__"

export type RPCHandleRef =
    | {
        [HANDLE_REF_MARKER]: "path"
        segments: string[]
    }
    | {
        [HANDLE_REF_MARKER]: "scope"
        slot_id: string
        segments: string[]
    }

export type RPCHandleSpec = RPCHandleRef | string


export function enumerateObjectProperties(
    specOrSpecs: RPCHandleSpec | Array<RPCHandleSpec>,
    scopeId: string,
): Array<{ [key: string]: string }> {
    const specs = Array.isArray(specOrSpecs) ? specOrSpecs : [specOrSpecs]
    return specs.map(spec => {
        const props: { [key: string]: string } = {}
        let target: any
        try {
            target = resolveHandleSpec(spec, scopeId)
        } catch (error) {
            void error
            return props
        }

        const numericKeys: number[] = []
        let cursor = target
        try {
            while (cursor && cursor !== Object.prototype) {
                for (const key of Reflect.ownKeys(cursor)) {
                    if (typeof key === "symbol") {
                        continue
                    }
                    if (/^\d+$/.test(key)) {
                        numericKeys.push(parseInt(key, 10))
                        continue
                    }
                    props[String(key)] = propertyTypeOf(cursor, key)
                }
                cursor = Object.getPrototypeOf(cursor)
            }
            if (numericKeys.length > 0) {
                numericKeys.sort((left, right) => left - right)
                if (numericKeys.length <= 50) {
                    for (const index of numericKeys) {
                        const key = index.toString()
                        props[key] = propertyTypeOf(target, key)
                    }
                } else {
                    const minIndex = numericKeys[0]
                    const maxIndex = numericKeys[numericKeys.length - 1]
                    props[`[${minIndex}:${maxIndex + 1}]`] = "index"
                }
            }
        } catch (error) {
            void error
        }
        return props
    })
}


export function materializeArgument(value: any, scopeId: string): any {
    if (Array.isArray(value)) {
        return value.map(item => materializeArgument(item, scopeId))
    }
    if (isHandleRef(value)) {
        return resolveHandleSpec(value, scopeId)
    }
    if (value !== null && typeof value === "object") {
        const mapped: { [key: string]: any } = {}
        for (const [key, item] of Object.entries(value)) {
            mapped[key] = materializeArgument(item, scopeId)
        }
        return mapped
    }
    return value
}


export function previewRpcValue(value: any): { hasValue: boolean, value: any | null } {
    if (value === undefined || value === null) {
        return { hasValue: true, value }
    }

    switch (typeof value) {
        case "string":
        case "number":
        case "boolean":
            return { hasValue: true, value }
        case "bigint":
        case "function":
        case "symbol":
            return { hasValue: false, value: null }
        default:
            break
    }

    if (value instanceof Promise) {
        return { hasValue: false, value: null }
    }

    if (Array.isArray(value) || isPlainObject(value)) {
        try {
            JSON.stringify(value)
            return { hasValue: true, value }
        } catch (error) {
            void error
        }
    }

    return { hasValue: false, value: null }
}


export function resolveHandleSpec(spec: RPCHandleSpec, scopeId: string, bind: boolean = false): any {
    return resolveHandleRef(normalizeHandleSpec(spec), scopeId, bind)
}


export function resolveOwnedScopeSlot(spec: RPCHandleSpec): string | null {
    const normalized = normalizeHandleSpec(spec)
    if (normalized[HANDLE_REF_MARKER] !== "scope" || normalized.segments.length > 0) {
        return null
    }
    return normalized.slot_id
}


function normalizeHandleSpec(spec: RPCHandleSpec): RPCHandleRef {
    if (typeof spec !== "string") {
        return spec
    }
    const [base, ...rest] = spec.split("/").filter(Boolean)
    if (base === undefined) {
        throw new Error("handle spec must not be empty")
    }
    if (isScopeSlotId(base)) {
        return {
            [HANDLE_REF_MARKER]: "scope",
            slot_id: base,
            segments: rest,
        }
    }
    return {
        [HANDLE_REF_MARKER]: "path",
        segments: [base, ...rest],
    }
}


function isHandleRef(value: any): value is RPCHandleRef {
    if (value === null || typeof value !== "object") {
        return false
    }
    const marker = value[HANDLE_REF_MARKER]
    if (marker === "path") {
        return Array.isArray(value.segments)
    }
    if (marker === "scope") {
        return typeof value.slot_id === "string" && Array.isArray(value.segments)
    }
    return false
}


function resolveHandleRef(ref: RPCHandleRef, scopeId: string, bind: boolean = false): any {
    const bindRootPropertyReceiver = ref[HANDLE_REF_MARKER] === "scope"
    const root = ref[HANDLE_REF_MARKER] === "path"
        ? globalThis
        : readScopeValue(scopeId, ref.slot_id)
    return getValueBySegments(ref.segments, bind, root, bindRootPropertyReceiver)
}


function getValueBySegments(
    segments: string[],
    bind: boolean = false,
    root: any = globalThis,
    bindRootPropertyReceiver: boolean = false,
): any {
    if (segments.length === 0) {
        return root
    }

    let parent = root
    let value = root
    for (const segment of segments) {
        parent = value
        value = value[segment]
    }

    // Scope refs point at a stored object, so its direct methods still need that
    // object as `this`. Top-level path refs should keep existing global behavior.
    if (typeof value === "function" && (parent !== root || bindRootPropertyReceiver)) {
        return bind ? value.bind(parent) : value
    }
    return value
}


function isPlainObject(value: any): boolean {
    if (value === null || typeof value !== "object") {
        return false
    }
    const prototype = Object.getPrototypeOf(value)
    return prototype === Object.prototype || prototype === null
}


function propertyTypeOf(target: any, key: string): string {
    const descriptor = Reflect.getOwnPropertyDescriptor(target, key)
    if (descriptor?.get) {
        return "getter"
    }
    if (descriptor?.set) {
        return "setter"
    }
    return typeof target[key]
}
