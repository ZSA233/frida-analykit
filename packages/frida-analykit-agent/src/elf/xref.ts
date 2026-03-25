

import { help, MemoryPage, NativePointerObject } from "../helper.js"
import { ScanAdrpCMod } from "../cmodule/scan_adrp.js"
import { setGlobalProperties } from "../config.js";
import { InstructionSequence } from "./insn.js";



function countLeadingSignBits(input: number | bigint, width: number): number {
    if(width < 1 || width > 64) {
        throw new RangeError('width must be between 1 and 64');
    }
    const mask = (1n << BigInt(width)) - 1n
    let value = BigInt(input) & mask

    const signBit = (value >> BigInt(width - 1)) & 1n
    let count = 0
    for(let i = width - 1; i >= 0; i--) {
        const bit = (value >> BigInt(i)) & 1n
        if(bit === signBit) {
            count ++
        }else{
            break
        }
    }
    return count
}


function choiceMatchPattern(p: NativePointer, byteNum: number): string {
    return p.toMatchPattern().split(/\s+/).slice(0, byteNum).join(' ')
}


function stripLeadingZeros(hexDump: string): { count: number, stripped: string}{
    const parts = hexDump.trim().split(/\s+/)
    let count = 0
    for(const part of parts) {
        if(part.toLowerCase() === '00') {
            count++
        }else{
            break
        }
    }
    const strippedParts = parts.slice(count)
    return {
        count,
        stripped: strippedParts.join(' ')
    }
}




export class AdrlXref {
    /*  adr/adrp Xi, #{imm1}
        ------------------------------------------------------------------
        | 31  | 30 ─ 29 | 28 27 26 25 24 | 23 ──────────────── 5 | 4 ─ 0 |
        | op  |  immlo  |    1 0 0 0 0   |     immhi (19b)       |  Rd   |
        ------------------------------------------------------------------
        adr : op=0
        adrp: op=1
    */

    /*  add Xm, Xn, #{imm2}
        ----------------------------------------------------------------------
        | 31 | 30 | 29 | 28 27 26 25 24 | 23 ─ 22 | 21 ─ 10  | 9 ─ 5 | 4 ─ 0 |
        | sf | op |  S |   1 0 0 0 1    |   sh    |   imm12  |  Rn   |  Rd   |
        ----------------------------------------------------------------------
    */

    static readonly ADRP_FIXED28_24_BITSET_MASK = ptr(0b10000).shl(24)

    target: NativePointer

    constructor(target: NativePointer) {
        this.target = target
    }

    get targetPage(): NativePointer{
        return this.target.and(ptr('0xfff').not())
    }

    get targetPageOffset(): NativePointer {
        return this.target.and('0xfff')
    }


    scanAdrl(
        scanRange: { base: NativePointer, size: number },
        maxGapToAdd: number = 16,
    ): Adrl[] {
        const { base, size } = scanRange

        const targetPage = this.targetPage
        // adrp
        const op = ptr(0b1)

        const adrpMatches: NativePointer[] = []

        const pageMask = ptr(Process.pageSize - 1).not()
        const adrpImmLenMask = ptr(0x1FFFFF)

        type ScanTargetRange = {
            base: NativePointer
            size: number
            high: boolean
        }

        help.memoryReadDo(base, size, (makeReadable, makeRecovery): void => {
            makeReadable()
            const ranges: ScanTargetRange[] = []
            if (this.target <= base) {
                ranges.push({ base, size, high: true })
            } else if (this.target >= base.add(size)) {
                ranges.push({ base, size, high: false })
            } else {
                ranges.push({ base, size: Number(this.target.sub(base)), high: false })
                ranges.push({ base: this.target, size: size - Number(this.target.sub(base)), high: true })
            }

            for (let range of ranges) {
                const minPage = range.base.and(pageMask)
                const maxPage = range.base.add(range.size).and(pageMask)

                const maxPageDelta = targetPage.sub(minPage).shr(12).and(adrpImmLenMask)
                const minPageDelta = targetPage.sub(maxPage).shr(12).and(adrpImmLenMask)

                let immVal: NativePointer
                let leadingCount: number
                if(range.high) {
                    leadingCount = countLeadingSignBits(BigInt(minPageDelta.toString()), 21)
                    immVal = adrpImmLenMask
                }else{
                    leadingCount = countLeadingSignBits(BigInt(maxPageDelta.toString()), 21)    
                    immVal = NULL
                }
                const immMask: NativePointer = ptr((((1n << BigInt(leadingCount)) - 1n) << BigInt(21 - leadingCount)).toString())

                const B = ptr(1)
                const immloMask = immMask.and(0b11)
                const immhiMask = immMask.shr(2)
                const anyRdMask = NULL
                const adrpMask = choiceMatchPattern(
                    NULL.or(B.shl(31))
                        .or(immloMask.shl(29))
                        .or(AdrlXref.ADRP_FIXED28_24_BITSET_MASK)
                        .or(immhiMask.shl(5))
                        .or(anyRdMask),
                    4,
                )
                const { stripped: adrpMaskStripped, count: alignOffset } = stripLeadingZeros(adrpMask)

                const immlo = immVal.and(0b11)
                const immhi = immVal.shr(2)
                const anyRd = NULL
                const adrpSign = choiceMatchPattern(
                    NULL.or(op.shl(31))
                        .or(immlo.shl(29))
                        .or(AdrlXref.ADRP_FIXED28_24_BITSET_MASK)
                        .or(immhi.shl(5))
                        .or(anyRd),
                    4,
                )
                const adrpSignStripped = adrpSign.split(/\s+/).slice(alignOffset).join(' ')

                const scanPattern = `${adrpSignStripped} : ${adrpMaskStripped}`

                const scanRes = ScanAdrpCMod.scan(
                    range, scanPattern, this.target, alignOffset,
                )
                if(scanRes.length) {
                    adrpMatches.push(...scanRes)
                }
            }

            makeRecovery()
        })

        const adrpInstructions = adrpMatches.reduce<Adrl[]>((acc, v) => {
            const adrl = this.verify(v, maxGapToAdd)
            if (adrl) {
                acc.push(adrl)
            }
            return acc
        }, [])
        return adrpInstructions
    }

    // adrp + add
    scanAdrlSlow(
        scanRange: { base: NativePointer, size: number},
        maxGapToAdd: number = 16,
    ): Adrl[] {
        const { base, size } = scanRange

        const targetPage = this.targetPage
        // adrp
        const op = ptr(0b1)

        const adrpPageMask = choiceMatchPattern(ptr(0x9fffffe0), 4)

        const adrpMatches: MemoryScanMatch[] = []

        help.memoryReadPageDo(base, size, (page: MemoryPage): boolean => {
            const { readable } = page
            const range = { base: page.base, size: page.size}
            if(!range) {
                return false
            }else if (!readable) {
                console.error(`[AdrlXref] scanAdrp base[${range.base} => ${range.base.add(range.size)}] is unreadable.`)
                return false
            }
            
            const pcPage = range.base
            const pageDelta = targetPage.sub(pcPage).shr(3*4).and(0x1FFFFF) // immhi:immlo = 21位
            const immlo = pageDelta.and(0b11)
            const immhi = pageDelta.shr(2)
            const anyRd = NULL
            const adrpSign = choiceMatchPattern(
                NULL.or(op.shl(31))
                    .or(immlo.shl(29))
                    .or(AdrlXref.ADRP_FIXED28_24_BITSET_MASK)
                    .or(immhi.shl(5))
                    .or(anyRd),
                4,
            )

            const scanPattern = `${adrpSign} : ${adrpPageMask}`
            const scanResults = Memory.scanSync(range.base, range.size, scanPattern).filter(v => {
                return v.address.and(0x3).isNull()
            })
            adrpMatches.push(...scanResults)
            return false
        })

        const adrpInstructions = adrpMatches.reduce<Adrl[]>((acc, v) => {
            const adrl = this.verify(v.address, maxGapToAdd)
            if(adrl) {
                acc.push(adrl)
            }
            return acc
        }, [])

        return adrpInstructions
    }


    verify(p: NativePointer, maxGapToAdd: number = 16): Adrl | null {
        try {
            const maybeAdrl = Adrl.loadFromPointer(p)
            const adrpInsn = maybeAdrl.adrpInsn
            if (adrpInsn.mnemonic !== 'adrp') {
                return null
            }

            if (maybeAdrl.getTarget(false, maxGapToAdd)?.equals(this.target)) {
                return maybeAdrl
            }
            return null
        } catch (error) {

        }
        return null
    }


    scanAdr(): Adrl[] {
        // TODO:
        return []
    }

}


type JumpScanRes = {
    src: InstructionSequence
    insn: Arm64Instruction
    next: NativePointer
}



export class Adrl extends InstructionSequence {
    readonly adrpInsn: Arm64Instruction
    private addInsn?: Arm64Instruction

    constructor(adrp: Arm64Instruction, add?: Arm64Instruction) {
        super(adrp)
        this.adrpInsn = adrp
        this.addInsn = add
    }

    get instruction(): Arm64Instruction {
        return Instruction.parse(this.$handle) as Arm64Instruction
    }

    scanBL(base?: NativePointer, maxGap: number = 16): JumpScanRes | null {
        if(!base) {
            base = this.$handle
        }

        let inc = 0
        for (const insn of this) {
            switch (insn.mnemonic) {
                case 'bl':
                    return {
                        src: this,
                        insn: insn,
                        next: insn.next,
                    }
            }
            inc++
            if(inc >= maxGap) return null
        }
        return null
    }

    getTarget(mustFoundAdd: boolean = false, maxGapToAdd: number = 16): NativePointer | null {
        const [op1, op2] = this.adrpInsn.operands
        const target = ptr(op2.value.toString())
        if (!this.addInsn) {
            let inc = 0
            verifyLoop: for (const insn of this) {
                switch (insn.mnemonic) {
                    case 'add':
                        if (insn.operands.length !== 3) {
                            break
                        }
                        const [addOp1, addOp2, addOp3] = insn.operands
                        if (addOp1.value !== op1.value) {
                            break
                        }
                        if (addOp2.value !== addOp1.value) {
                            console.error(`[Adrl] findAdd [${insn}] op2，来源于另一个寄存器，无法预估目标地址。`)
                            break
                        }
                        this.addInsn = insn
                        break verifyLoop
                }
                inc++
                if (inc >= maxGapToAdd) return mustFoundAdd ? null : target
            }
            
        }
        if(!this.addInsn) {
            return target
        }
        return target.add(this.addInsn.operands[2].value.toString())
    
    }

}


setGlobalProperties({
    AdrlXref,

})