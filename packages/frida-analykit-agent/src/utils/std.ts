import { Java } from '../bridges.js'
import { help, NativePointerObject } from '../helper.js'


export class StdVector extends NativePointerObject {
    private readonly _start: NativePointer
    private readonly _finish: NativePointer
    private readonly _end_of_storage: NativePointer

    constructor(handle: NativePointer = NULL){
        let shouldDelete = handle.isNull()
        if(handle.isNull()) {
            handle = Memory.alloc(3 * Process.pointerSize)
        }
        super(handle)
        
        this._start = this.$handle
        this._finish = this.$handle.add(Process.pointerSize)
        this._end_of_storage = this.$handle.add(Process.pointerSize * 2)

        if (shouldDelete) {
            const weakRef = ptr(handle.toString())
            Script.bindWeak(this.$handle, () =>{
                Java.api.$delete(weakRef)
            })
        }
    }

    static cast(handle: NativePointer): StdVector {
        return new StdVector(handle)
    }

    get start(): NativePointer {
        return this._start.readPointer()
    }

    set start(val: NativePointer){
        this._start.writePointer(val)
    } 

    get finish(): NativePointer {
        return this._finish.readPointer()
    }

    set finish(val: NativePointer) {
        this._finish.writePointer(val)
    }

    get end_of_storage(): NativePointer {
        return this._end_of_storage.readPointer()
    }

    set end_of_storage(val: NativePointer) {
        this._end_of_storage.writePointer(val)
    }

    get length(): number {
        return this.finish.sub(this.start).toUInt32() / Process.pointerSize
    }

    get capacity(): number {
        return this.end_of_storage.sub(this.start).toUInt32() / Process.pointerSize
    }

    [Symbol.iterator](){
        let nextPtr = this.start
        const that = this
        return {
            next(){
                let done = false
                let value = nextPtr
                if(value >= that.finish) {
                    done = true
                    value = NULL
                }else{
                    nextPtr = nextPtr.add(Process.pointerSize)
                }
                return {
                    value: value,
                    done: done,
                }
            }
        }
    }

    toArray(): NativePointer[] {
        const list = []
        for(let v of this) {
            list.push(v)
        }
        return list
    }
}


const STD_STRING_MEM_BYTE_SIZE = Process.pointerSize === 4 ? 12 : 24
const STD_STRING_CAP_LONG_MODE_CAP_MASK = help.androidGetApiLevel() <= 16 
    ? (Process.pointerSize === 4 ? '0x80000000': '0x8000000000000000')
    : '0x1'


export class StdString extends NativePointerObject {
    private readonly _cap: NativePointer
    private readonly _size: NativePointer
    private readonly _data: NativePointer

    constructor(handle: NativePointer = NULL) {
        if (handle.isNull()) {
            handle = Memory.alloc(STD_STRING_MEM_BYTE_SIZE)
        }
        super(handle)

        this._cap = this.$handle
        this._size = this.$handle.add(Process.pointerSize)
        this._data = this.$handle.add(Process.pointerSize * 2)
    }

    static cast(handle: NativePointer): StdString {
        return new StdString(handle)
    }

    get size(): number  {
        return this.longMode ? this._size.readU64().toNumber() : this.$handle.add(STD_STRING_MEM_BYTE_SIZE - 1).and(0x7F).toUInt32()
    }

    get data(): ArrayBuffer | null {
        return this._data.readByteArray(this.size)
    }

    get length(): number {
        return this.size
    }

    get capacity(): number {
        return this.longMode ? this._cap.readU64().toNumber() : this.size
    }

    get longMode(): boolean {
        return !this._cap.readU64().and(STD_STRING_CAP_LONG_MODE_CAP_MASK).equals(0)
    }

    get stringPtr(): NativePointer {
        if(this.longMode) {
            return this._data.readPointer()
        }else{
            return this.$handle.readPointer()
        }
    }

    toString(): string {
        return this.stringPtr.readUtf8String(this.size) || ''
    }

    toCString(): string {
        return this.stringPtr.readCString(this.size) || ''
    }

    toUtf8String(): string {
        return this.stringPtr.readUtf8String(this.size) || ''
    }

    toUtf16String(): string {
        return this.stringPtr.readUtf16String(this.size) || ''
    }
}
