


export class ArrayPointer extends Number {
    buff: ArrayBuffer | undefined
    constructor(val: any, buff?: ArrayBuffer) {
        super(val)
        this.buff = buff
    }

    isNull(): boolean {
        return !this.buff?.byteLength
    }

    add(val: number | ArrayPointer): ArrayPointer {
        return new ArrayPointer(this.toNumber() + Number(val), this.buff)
    }

    sub(val: number | ArrayPointer): ArrayPointer {
        return new ArrayPointer(this.toNumber() - Number(val), this.buff)
    }

    toNumber(): number {
        return Number(this)
    }

    getViewer(size: number): DataView {
        const off = this.toNumber()
        const view = new DataView(this.buff!.slice(off, off + size))
        return view
    }

    readS8(): number {
        const view = this.getViewer(1)
        return view.getInt8(0)
    }

    readU8(): number {
        const view = this.getViewer(1)
        return view.getUint8(0)
    }

    readS16(): number {
        const view = this.getViewer(2)
        return view.getInt16(0, true)
    }

    readU16(): number {
        const view = this.getViewer(2)
        return view.getUint16(0, true)
    }

    readS32(): number {
        const view = this.getViewer(4)
        return view.getInt32(0, true)
    }

    readU32(): number {
        const view = this.getViewer(4)
        return view.getUint32(0, true)
    }

    readS64(): BigInt {
        const view = this.getViewer(8)
        return view.getBigInt64(0, true)
    }

    readU64(): BigInt {
        const view = this.getViewer(8)
        return view.getBigUint64(0, true)
    }

    readCString(): string {
        if(this.isNull()) {
            return ''
        }
        const off = this.toNumber()
        let str = ''
        const bview = new DataView(this.buff!)
        for (let i = off; i < this.buff!.byteLength; i++) {
            const b = bview.getUint8(i)
            if (b === 0x00) {
                break
            }
            str += String.fromCharCode(b)
        }
        return str
    }

    readByteArray(length: number): ArrayBuffer {
        const off = this.toNumber()
        return this.buff!.slice(off, off + length)
    }

    readPointer(): NativePointer {
        return ptr(Number(this.readU64())).readPointer()
    }

    toString(): string {
        return this.readU64().toString(16)
    }
}
