import { setGlobalProperties } from "../../config/index.js"


export class TextEncoder {
    readonly encoding = 'utf-8'

    encode(input: string): Uint8Array {
        const bytes: number[] = []
        for (let i = 0; i < input.length; i++) {
            let codePoint = input.charCodeAt(i)
            if (codePoint >= 0xd800 && codePoint <= 0xdbff && i + 1 < input.length) {
                const trail = input.charCodeAt(i + 1)
                if (trail >= 0xdc00 && trail <= 0xdfff) {
                    codePoint = 0x10000 + ((codePoint - 0xd800) << 10) + (trail - 0xdc00)
                    i += 1
                }
            }

            if (codePoint <= 0x7f) {
                bytes.push(codePoint)
                continue
            }
            if (codePoint <= 0x7ff) {
                bytes.push(
                    0xc0 | (codePoint >> 6),
                    0x80 | (codePoint & 0x3f),
                )
                continue
            }
            if (codePoint <= 0xffff) {
                bytes.push(
                    0xe0 | (codePoint >> 12),
                    0x80 | ((codePoint >> 6) & 0x3f),
                    0x80 | (codePoint & 0x3f),
                )
                continue
            }

            bytes.push(
                0xf0 | (codePoint >> 18),
                0x80 | ((codePoint >> 12) & 0x3f),
                0x80 | ((codePoint >> 6) & 0x3f),
                0x80 | (codePoint & 0x3f),
            )
        }
        return Uint8Array.from(bytes)
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
