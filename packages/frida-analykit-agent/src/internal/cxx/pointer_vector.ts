import { Java } from "../../bridges/index.js"
import { NativePointerObject } from "../frida/pointer_object.js"

export class PointerVector extends NativePointerObject {
    private _deleted = false

    constructor(handle: NativePointer = NULL) {
        super(handle.isNull() ? Memory.alloc(Process.pointerSize * 3) : handle)
    }

    get start(): NativePointer {
        return this.$handle.readPointer()
    }

    get finish(): NativePointer {
        return this.$handle.add(Process.pointerSize).readPointer()
    }

    get endOfStorage(): NativePointer {
        return this.$handle.add(Process.pointerSize * 2).readPointer()
    }

    toPointerArray(): NativePointer[] {
        const items: NativePointer[] = []
        for (let current = this.start; !current.isNull() && current.compare(this.finish) < 0; current = current.add(Process.pointerSize)) {
            items.push(current.readPointer())
        }
        return items
    }

    dispose(): void {
        if (this._deleted) {
            return
        }
        this._deleted = true
        const storage = this.start
        if (!storage.isNull()) {
            ;(Java as any).api.$delete(storage)
        }
        this.$handle.writePointer(NULL)
        this.$handle.add(Process.pointerSize).writePointer(NULL)
        this.$handle.add(Process.pointerSize * 2).writePointer(NULL)
    }
}
