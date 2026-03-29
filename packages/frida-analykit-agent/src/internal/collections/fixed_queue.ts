

export class FixedQueue<T> {
    private _index = -1
    private $depth = 0
    private $list: (T | undefined)[]
    private $length = 0
    private $overflowCallback?: (elements: T[]) => void

    constructor(length: number) {
        this.$list = Array.from({ length: length }, () => undefined)
        this.$length = 0
        this.$depth = length
    }

    push(elm: T): T | undefined {
        let popElm = undefined
        this._index = (this._index + 1) % this.$depth
        if (this.$length === this.$depth) {
            popElm = this.$list[this._index]
        } else {
            this.$length++
        }
        this.$list[this._index] = elm
        if(popElm !== undefined) {
            this.$onOverflow(popElm)
        }
        return popElm
    }

    pop(): T | undefined {
        if (this.$length === this.$depth) {
            const head = this.$headIndex
            const elm = this.$list[head]
            this.$length--
            this.$list[head] = undefined
            return elm
        } else if (this.$length > 0) {
            let head = this.$headIndex
            const elm = this.$list[head]
            this.$length--
            if (this.$length < 0) this.$length = 0
            this.$list[head] = undefined
            return elm
        }
        return undefined
    }

    clear() {
        this.$length = 0
        this._index = 0
    }

    get $headIndex(): number {
        let head = this._index + 1 - this.$length
        if (head < 0) {
            head += this.$depth
        }
        return head
    }

    get $tailIndex(): number {
        return this._index
    }

    get list(): T[] {
        if (this.$length <= 0) {
            return []
        }
        const head = this.$headIndex
        const tail = this.$tailIndex + 1
        if (head >= tail) {
            return [...this.$list.slice(head), ...this.$list.slice(0, tail)] as T[]
        }
        return this.$list.slice(head, tail) as T[]
    }

    get length() {
        return this.$length
    }

    index(offset: number): T | undefined {
        const idx = (this._index + 1 + offset) % this.$depth
        return this.$list[idx]
    }

    flush(): Array<T> {
        const list = this.list
        this.clear()
        return list
    }

    registerOverflowCallback(callback: (elements: T[]) => void){
        this.$overflowCallback = callback
    }

    $onOverflow(element: T) {
        if(!this.$overflowCallback) return
        this.$overflowCallback([element, ...this.flush()])
    }

}
