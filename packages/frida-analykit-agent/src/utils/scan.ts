

import { NativePointerObject } from "../helper.js"
import {
    binaryPointer,
    binaryReadPointer,
    binaryReadU32,
} from "./utils.js"


export const GArray_structOf = {
    B64: {
        data: binaryReadPointer(0),
        len: binaryReadU32(8),
    },
    // B32
    B32: {}
}





class GArrayPtr extends NativePointerObject {

    constructor(handle: NativePointer) {
        super(handle)
    }

    static cast(handle: NativePointer): GArrayPtr {
        return new GArrayPtr(handle)
    }

    get data(): NativePointer {
        const obj = this.$handle.readPointer()
        if (obj.isNull()) return NULL
        return GArray_structOf.B64.data(obj)
    }

    get length(): number {
        const obj = this.$handle.readPointer()
        if (obj.isNull()) return 0
        return GArray_structOf.B64.len(obj)
    }

    [Symbol.iterator]() {
        let nextPtr = this.data
        const length = this.length
        let inc = 0
        return {
            next() {
                const result = {
                    value: nextPtr,
                    done: inc >= length,
                }
                nextPtr = nextPtr.add(Process.pointerSize)
                inc++
                return result
            }
        }
    }

    toArray(): NativePointer[] {
        const list = []
        for (let v of this) {
            list.push(v)
        }
        return list
    }
}




export const MemoryScanRes_structOf = {
    B64: {
        results: binaryPointer(0),
        user_data: binaryPointer(8),
        SIZE: 16,
    },
    // B32
    B32: {}
}


export class CMemoryScanRes extends NativePointerObject {
    readonly data: GArrayPtr
    readonly user_data: NativePointer

    constructor(userData: NativePointer) {
        const structOf = MemoryScanRes_structOf.B64

        const handle = Memory.alloc(structOf.SIZE)

        super(handle)

        this.data = new GArrayPtr(structOf.results(handle))
        structOf.user_data(handle).writePointer(userData)
        this.user_data = userData
    }

}

