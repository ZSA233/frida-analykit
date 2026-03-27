import { setGlobalProperties } from "../config.js"
import { InstructionSequence } from "./insn.js"



type ScoreResult = {
    instructions: Arm64Instruction[],
    eoi?: Arm64Instruction,
    score: number
}


export class Subroutine extends InstructionSequence {

    constructor(entry: Arm64Instruction) {
        super(entry)
    }

    scoreThunk(): ScoreResult {
        const MAX_INSTR = 20
        let score: number = 0

        let i: number = 0
        const insns: Arm64Instruction[] = []
        loop: for (const insn of this) {
            insns.push(insn)
            const ops = insn.operands
            switch (insn.mnemonic) {
                case 'br':
                case 'b':
                    this.eoi = insn
                    score += 100
                    break loop
                case 'stp':
                case 'ldp':
                    if (ops[2].type === 'mem' && ops[2].value.base === 'sp') {
                        score -= 20
                        break
                    }
                case 'ret':
                    score = 0
                    this.eoi = insn
                    break
                case 'sub':
                case 'add':
                    if (ops[0].value as string === 'sp') {
                        score -= 20
                        break
                    }
                    break
            }
            if (i >= 5) {
                // 指令越多分数越低
                score -= 5
            }
            i++
            if (i >= MAX_INSTR) {
                break
            }
        }

        return {
            instructions: insns,
            eoi: this.eoi,
            score: score,
        }
    }

}


setGlobalProperties({
    Subroutine,
})