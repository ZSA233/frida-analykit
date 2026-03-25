import { setGlobalProperties } from "../config.js"
import { NativePointerObject } from "../helper.js"



export class InstructionSequence extends NativePointerObject {
    protected readonly entryInsn: Arm64Instruction
    protected readonly insns: Arm64Instruction[] = []
    protected eoi?: Arm64Instruction

    constructor(entry: Arm64Instruction) {
        const handle = entry.address
        super(handle)
        this.entryInsn = entry
        this.insns = [entry]
    }

    static loadFromPointer<T extends InstructionSequence>(
        this: new (insn: Arm64Instruction) => T,
        handle: NativePointer
    ): T {
        const insn = Instruction.parse(handle) as Arm64Instruction
        return new this(insn)
    }

    *[Symbol.iterator]() {
        let insns = this.insns
        let insn: Arm64Instruction = this.entryInsn
        let inc = 0
        const that = this

        let value: Arm64Instruction | undefined

        while (true) {
            value = insns[inc]
            if (value === undefined && that.eoi === undefined) {
                try {
                    insn = Instruction.parse(insns[inc - 1].next) as Arm64Instruction
                    insns.push(insn)
                } catch (error) {
                    that.eoi = insn
                    break
                }
            }
            inc++
            yield insn
        }

    }

    clearCache() {
        this.insns.length = 0
    }


}


setGlobalProperties({
    InstructionSequence,
})