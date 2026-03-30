



export enum RPCMsgType {
    BATCH = 'BATCH',
    SCOPE_CALL = 'SCOPE_CALL',
    SCOPE_EVAL = 'SCOPE_EVAL',
    SCOPE_GET = 'SCOPE_GET',
    ENUMERATE_OBJ_PROPS = 'ENUMERATE_OBJ_PROPS',
    INIT_CONFIG = 'INIT_CONFIG',
    SAVE_FILE = 'SAVE_FILE',
    DEX_DUMP_BEGIN = 'DEX_DUMP_BEGIN',
    DUMP_DEX_FILE = 'DUMP_DEX_FILE',
    DEX_DUMP_END = 'DEX_DUMP_END',
    ELF_SNAPSHOT_BEGIN = 'ELF_SNAPSHOT_BEGIN',
    ELF_SNAPSHOT_CHUNK = 'ELF_SNAPSHOT_CHUNK',
    ELF_SNAPSHOT_END = 'ELF_SNAPSHOT_END',
    ELF_SYMBOL_CALL_LOG = 'ELF_SYMBOL_CALL_LOG',
    SSL_SECRET = 'SSL_SECRET',
    PROGRESSING = 'PROGRESSING',
}


export enum batchSendSource {
    DEX_DUMP_FILES = 'DEX_DUMP_FILES',
    ELF_SNAPSHOT_CHUNKS = 'ELF_SNAPSHOT_CHUNKS',
}


export enum saveFileSource {
    procMaps = 'procMaps',
    textFile = 'textFile',
    elfModule = 'elfModule',
    dexFile = 'dexFile',
}
