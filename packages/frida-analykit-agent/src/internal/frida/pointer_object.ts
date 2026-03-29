export class NativePointerObject {
    protected readonly _handle: NativePointer

    constructor(handle: NativePointer) {
        this._handle = handle
    }

    get $handle(): NativePointer {
        return this._handle
    }

    $isNull(): boolean {
        return this.$handle.isNull()
    }
}
