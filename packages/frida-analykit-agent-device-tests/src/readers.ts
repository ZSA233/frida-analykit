export function readJavaStringText(javaString: { toUTF16String: () => { toString: () => string; release: () => unknown } }): string {
    const utf16 = javaString.toUTF16String();
    try {
        return utf16.toString();
    } finally {
        utf16.release();
    }
}

export function readUtf16PointerText(pointer: NativePointer, length: number): string {
    return pointer.readUtf16String(length) ?? "";
}

export function readCharElementsText(
    elements: { $index: (index: number) => { toChar: () => number } },
    length: number,
): string {
    let text = "";
    for (let index = 0; index < length; index++) {
        text += String.fromCharCode(elements.$index(index).toChar());
    }
    return text;
}

export function readObjectArrayTexts(
    javaArray: { $length: number; $index: (index: number) => { $jstring: unknown; $unref: () => unknown } },
): string[] {
    const texts: string[] = [];
    for (let index = 0; index < javaArray.$length; index++) {
        const element = javaArray.$index(index) as any;
        try {
            texts.push(readJavaStringText(element.$jstring));
        } finally {
            element.$unref();
        }
    }
    return texts;
}
