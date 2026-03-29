import JavaBridge from "frida-java-bridge";

type BridgeGlobals = typeof globalThis & {
    Java?: typeof JavaBridge;
    ObjC?: unknown;
    Swift?: unknown;
    __FRIDA_ANALYKIT_CONFIG__?: Record<string, unknown>;
};

const globals = globalThis as BridgeGlobals;

export const Java = globals.Java ?? JavaBridge;
export const ObjC = globals.ObjC;
export const Swift = globals.Swift;

if (!("Java" in globals)) {
    globals.Java = Java;
}
