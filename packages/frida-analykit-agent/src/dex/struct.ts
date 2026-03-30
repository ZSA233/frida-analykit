import { binaryPointer, binaryReadPointer, binaryReadU32 } from "../internal/binary/readers.js"

export const DexFileStructOf = {
    B64: {
        begin: binaryReadPointer(8),
        size: binaryReadU32(16),
        location: binaryPointer(40),
    },
    B32: {
        begin: binaryReadPointer(4),
        size: binaryReadU32(8),
        location: binaryPointer(20),
    },
} as const
