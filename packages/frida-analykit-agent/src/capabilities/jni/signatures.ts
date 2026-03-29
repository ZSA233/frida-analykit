export type JniNonVoidFamily =
    | "Object"
    | "Boolean"
    | "Byte"
    | "Char"
    | "Short"
    | "Int"
    | "Long"
    | "Float"
    | "Double";

export type JniMethodReturnFamily = JniNonVoidFamily | "Void";
export type JniDescriptorKind = "primitive" | "object" | "array" | "void";

export type JniInstanceCallMethodName = `Call${JniMethodReturnFamily}Method`;
export type JniNonvirtualCallMethodName = `CallNonvirtual${JniMethodReturnFamily}Method`;
export type JniStaticCallMethodName = `CallStatic${JniMethodReturnFamily}Method`;
export type JniInstanceFieldGetMethodName = `Get${JniNonVoidFamily}Field`;
export type JniStaticFieldGetMethodName = `GetStatic${JniNonVoidFamily}Field`;
export type JniInstanceFieldSetMethodName = `Set${JniNonVoidFamily}Field`;
export type JniStaticFieldSetMethodName = `SetStatic${JniNonVoidFamily}Field`;

export interface JniTypeDescriptorInfo {
    readonly descriptor: string;
    readonly family: JniMethodReturnFamily;
    readonly kind: JniDescriptorKind;
    readonly isPrimitive: boolean;
    readonly isObjectLike: boolean;
    readonly isArray: boolean;
    readonly isVoid: boolean;
}

export interface JniMethodDescriptorInfo {
    readonly descriptor: string;
    readonly parameterDescriptors: readonly string[];
    readonly parameterTypes: readonly JniTypeDescriptorInfo[];
    readonly returnDescriptor: string;
    readonly returnType: JniTypeDescriptorInfo;
}

type ParseResult = {
    descriptor: string;
    nextIndex: number;
};

const FIELD_DESCRIPTOR_CACHE = new Map<string, JniTypeDescriptorInfo>();
const METHOD_DESCRIPTOR_CACHE = new Map<string, JniMethodDescriptorInfo>();

function descriptorFamilyFor(descriptor: string): JniMethodReturnFamily {
    switch (descriptor[0]) {
        case "Z":
            return "Boolean";
        case "B":
            return "Byte";
        case "C":
            return "Char";
        case "S":
            return "Short";
        case "I":
            return "Int";
        case "J":
            return "Long";
        case "F":
            return "Float";
        case "D":
            return "Double";
        case "V":
            return "Void";
        case "L":
        case "[":
            return "Object";
        default:
            throw new Error(`unsupported JNI descriptor: ${descriptor}`);
    }
}

function buildTypeInfo(descriptor: string): JniTypeDescriptorInfo {
    const kind = descriptor[0] === "["
        ? "array"
        : descriptor[0] === "L"
            ? "object"
            : descriptor[0] === "V"
                ? "void"
                : "primitive";
    const family = descriptorFamilyFor(descriptor);
    return {
        descriptor,
        family,
        kind,
        isPrimitive: kind === "primitive",
        isObjectLike: kind === "object" || kind === "array",
        isArray: kind === "array",
        isVoid: kind === "void",
    };
}

function parseSingleDescriptor(source: string, start: number, allowVoid: boolean): ParseResult {
    if (start >= source.length) {
        throw new Error(`unexpected end of JNI descriptor: ${source}`);
    }

    const head = source[start];
    if ("ZBCSIJFD".includes(head)) {
        return {
            descriptor: head,
            nextIndex: start + 1,
        };
    }
    if (head === "V") {
        if (!allowVoid) {
            throw new Error(`void is not a valid parameter/field descriptor: ${source}`);
        }
        return {
            descriptor: "V",
            nextIndex: start + 1,
        };
    }
    if (head === "L") {
        const end = source.indexOf(";", start);
        if (end === -1) {
            throw new Error(`unterminated object descriptor: ${source}`);
        }
        return {
            descriptor: source.slice(start, end + 1),
            nextIndex: end + 1,
        };
    }
    if (head === "[") {
        let index = start;
        while (source[index] === "[") {
            index++;
        }
        const component = parseSingleDescriptor(source, index, false);
        return {
            descriptor: source.slice(start, component.nextIndex),
            nextIndex: component.nextIndex,
        };
    }
    throw new Error(`unsupported JNI descriptor head ${head} in ${source}`);
}

export function parseFieldDescriptor(descriptor: string): JniTypeDescriptorInfo {
    const cached = FIELD_DESCRIPTOR_CACHE.get(descriptor);
    if (cached !== undefined) {
        return cached;
    }

    const parsed = parseSingleDescriptor(descriptor, 0, false);
    if (parsed.nextIndex !== descriptor.length) {
        throw new Error(`invalid trailing tokens in field descriptor: ${descriptor}`);
    }

    const info = buildTypeInfo(parsed.descriptor);
    FIELD_DESCRIPTOR_CACHE.set(descriptor, info);
    return info;
}

export function parseMethodDescriptor(descriptor: string): JniMethodDescriptorInfo {
    const cached = METHOD_DESCRIPTOR_CACHE.get(descriptor);
    if (cached !== undefined) {
        return cached;
    }
    if (!descriptor.startsWith("(")) {
        throw new Error(`invalid JNI method descriptor: ${descriptor}`);
    }

    const parameterDescriptors: string[] = [];
    let index = 1;
    while (index < descriptor.length && descriptor[index] !== ")") {
        const parsed = parseSingleDescriptor(descriptor, index, false);
        parameterDescriptors.push(parsed.descriptor);
        index = parsed.nextIndex;
    }
    if (descriptor[index] !== ")") {
        throw new Error(`invalid JNI method descriptor, missing ')': ${descriptor}`);
    }

    const returnDescriptor = parseSingleDescriptor(descriptor, index + 1, true);
    if (returnDescriptor.nextIndex !== descriptor.length) {
        throw new Error(`invalid trailing tokens in method descriptor: ${descriptor}`);
    }

    const info: JniMethodDescriptorInfo = {
        descriptor,
        parameterDescriptors,
        parameterTypes: parameterDescriptors.map(parseFieldDescriptor),
        returnDescriptor: returnDescriptor.descriptor,
        returnType: buildTypeInfo(returnDescriptor.descriptor),
    };
    METHOD_DESCRIPTOR_CACHE.set(descriptor, info);
    return info;
}

export function getMethodReturnFamily(descriptor: string): JniMethodReturnFamily {
    return parseMethodDescriptor(descriptor).returnType.family;
}

export function getFieldFamily(descriptor: string): JniNonVoidFamily {
    const family = parseFieldDescriptor(descriptor).family;
    if (family === "Void") {
        throw new Error(`field descriptor cannot resolve to void: ${descriptor}`);
    }
    return family;
}

export function getInstanceCallMethodName(descriptor: string): JniInstanceCallMethodName {
    return `Call${getMethodReturnFamily(descriptor)}Method`;
}

export function getStaticCallMethodName(descriptor: string): JniStaticCallMethodName {
    return `CallStatic${getMethodReturnFamily(descriptor)}Method`;
}

export function getNonvirtualCallMethodName(descriptor: string): JniNonvirtualCallMethodName {
    return `CallNonvirtual${getMethodReturnFamily(descriptor)}Method`;
}

export function getInstanceFieldGetMethodName(descriptor: string): JniInstanceFieldGetMethodName {
    return `Get${getFieldFamily(descriptor)}Field`;
}

export function getStaticFieldGetMethodName(descriptor: string): JniStaticFieldGetMethodName {
    return `GetStatic${getFieldFamily(descriptor)}Field`;
}

export function getInstanceFieldSetMethodName(descriptor: string): JniInstanceFieldSetMethodName {
    return `Set${getFieldFamily(descriptor)}Field`;
}

export function getStaticFieldSetMethodName(descriptor: string): JniStaticFieldSetMethodName {
    return `SetStatic${getFieldFamily(descriptor)}Field`;
}
