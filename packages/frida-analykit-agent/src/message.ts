



export const enum RPCMsgType {
    BATCH = 'BATCH',
    SCOPE_CALL = 'SCOPE_CALL',
    SCOPE_EVAL = 'SCOPE_EVAL',
    SCOPE_GET = 'SCOPE_GET',
    ENUMERATE_OBJ_PROPS = 'ENUMERATE_OBJ_PROPS',
    INIT_CONFIG = 'INIT_CONFIG',
    SAVE_FILE = 'SAVE_FILE',
    SSL_SECRET = 'SSL_SECRET',
    PROGRESSING = 'PROGRESSING',
}


export const enum batchSendSource {
}


export const enum saveFileSource {
    procMaps = 'procMaps',
    textFile = 'textFile',
    elfModule = 'elfModule',
}