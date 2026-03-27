import { setGlobalProperties } from "../config.js"


export class TextEncoder {
    readonly encoding = 'utf-8'

    encode(input: string): Uint8Array {
        const strPtr = Memory.allocUtf8String(input)
        const eosZeros = Memory.scanSync(strPtr, input.length * 4, "00")
        const blen = eosZeros[0].address.sub(strPtr)
        return new Uint8Array(strPtr.readByteArray(Number(blen))!)
    }

}


export class TextDecoder {
    readonly encoding = 'utf-8'

    decode(input: ArrayBuffer): string {
        if (typeof(input['unwrap']) === 'function') {
            return input.unwrap().readUtf8String() || ''
        }

        const tmp = Memory.alloc(input.byteLength)
        tmp.writeByteArray(input)
        return tmp.readUtf8String() || ''
    }
}


setGlobalProperties({
    TextDecoder,
    TextEncoder,
})