
import { ArrayPointer } from "./array_pointer.js"

export function mustType<T>(val: T | null | undefined): T {
    if (!val) {
        throw new Error(`val不能为null`)
    }
    return val
}

export function unwrapArgs(args: InvocationArguments, n: number): (any|NativePointer)[] {
    const list = []
    for(let i = 0; i < n; i++) {
        list.push(args[i])
    }
    return list
}


type NumberReaderMethod =
    'readU8' |
    'readU16' |
    'readU32' |
    'readU64' |
    'readS8' |
    'readS16' |
    'readS32' |
    'readS64' 



type BianaryBaseReader<T> = (base: NativePointer | ArrayPointer) => T


function binaryNumberReader(offset: number, method: NumberReaderMethod): BianaryBaseReader<number> {
    return function (base: NativePointer | ArrayPointer): number {
        return Number(base.add(offset)[method]())
    }
}

function binaryPointerReader(offset: number): BianaryBaseReader<NativePointer> {
    return function (base: NativePointer | ArrayPointer): NativePointer {
        return base.add(offset).readPointer()
    }
}

function binaryPointerOffset(offset: number): BianaryBaseReader<NativePointer> {
    return function (base: NativePointer | ArrayPointer): NativePointer {
        return ptr(base.add(offset).toString())
    }
}


function readByteArray(offset: number, length: number) { return (base: NativePointer | ArrayPointer) => mustType(base.add(offset).readByteArray(length)) }
function binaryReadU8(offset: number) { return binaryNumberReader(offset, 'readU8') }
function binaryReadU16(offset: number) { return binaryNumberReader(offset, 'readU16') }
function binaryReadU32(offset: number) { return binaryNumberReader(offset, 'readU32') }
function binaryReadS32(offset: number) { return binaryNumberReader(offset, 'readS32') }
function binaryReadU64(offset: number) { return binaryNumberReader(offset, 'readU64') }
function binaryReadS64(offset: number) { return binaryNumberReader(offset, 'readS64') }
function binaryReadPointer(offset: number) { return binaryPointerReader(offset) }
function binaryPointer(offset: number) { return binaryPointerOffset(offset) }
function binaryReadPointerStruct(offset: number, structOfs: { B64: { [key: string]: BianaryBaseReader<any> }, B32?: { [key: string]: BianaryBaseReader<any> } }) {
    return function (base: NativePointer | ArrayPointer): { [key: string]: any } {
        const structOf = Process.pointerSize === 4 ? structOfs['B32'] : structOfs['B64']
        const structBase = binaryPointerReader(offset)(base)
        const obj: { [key: string]: any } = {}
        for (let [k, offseter] of Object.entries(structOf!)) {
            Object.defineProperty(obj, k, {
                value: offseter(structBase),
                writable: false,
                enumerable: true,
            })
        }
        return obj
    }
}

export {
    readByteArray,
    binaryReadU8,
    binaryReadU16,
    binaryReadU32,
    binaryReadS32,
    binaryReadU64,
    binaryReadS64,
    binaryReadPointer,
    binaryPointer,
    binaryReadPointerStruct,
}



export function wrapArgTypes(typ: NativeFunctionArgumentType, length: number): NativeFunctionArgumentType[] {
    return Array.from({ length: length }, () => typ)
}


export function arrayBuffer2Hex(
    buffer: ArrayBuffer,
    options: { uppercase?: boolean } = {}
): string {
    const { uppercase = false } = options
    const bytes = new Uint8Array(buffer)
    return Array.from(bytes)
        .map(b => {
            const hex = b.toString(16).padStart(2, '0')
            return uppercase ? hex.toUpperCase() : hex
        })
        .join(' ')
}
