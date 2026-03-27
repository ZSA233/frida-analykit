

import {
    readByteArray, binaryReadPointer,
    binaryPointer, binaryReadPointerStruct,
    binaryReadU8, binaryReadU16,
    binaryReadU32, binaryReadS32,
    binaryReadU64, binaryReadS64,
} from "../utils/utils.js"

export const SSL3_RANDOM_SIZE = 32

export const bssl_SSL3_STATE_structOf = {
    B64: {
        read_sequence: readByteArray(0, 8),
        cwrite_sequence: readByteArray(8, 8),
        server_random: readByteArray(16, SSL3_RANDOM_SIZE),
        client_random: readByteArray(16 + SSL3_RANDOM_SIZE, SSL3_RANDOM_SIZE),
        // ...
    },
    // B32
    B32: {}
}


export const ssl_st_structOf = {
    B64: {
        method: binaryReadPointer(0),
        config: binaryReadPointer(8),
        version: binaryReadU16(16),
        max_send_fragment: binaryReadU16(18),
        rbio: binaryReadPointer(24),
        wbio: binaryReadPointer(32),
        do_handshake: binaryReadPointer(40),
        s3: binaryReadPointerStruct(48, bssl_SSL3_STATE_structOf),
        d1: binaryReadPointer(56),
        msg_callback: binaryReadPointer(64),
        msg_callback_arg: binaryReadPointer(72),
        initial_timeout_duration_ms: binaryReadU32(80),
        session: binaryReadPointer(88),
        info_callback: binaryReadPointer(96),
        ctx: binaryReadPointer(104),
        session_ctx: binaryReadPointer(112),
        ex_data: binaryReadPointer(120),
        // ...
    },
    // B32
    B32: {}
}


