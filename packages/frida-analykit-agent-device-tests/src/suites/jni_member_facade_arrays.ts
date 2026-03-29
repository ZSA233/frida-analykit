import { JNIEnv } from "@zsa233/frida-analykit-agent";

import { readCharElementsText, readObjectArrayTexts } from "../readers.js";
import { assertCondition, runJavaSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runJniMemberFacadeArraysSuite(): AgentUnitSuiteResult {
    return runJavaSuite("jni_member_facade_arrays", [
        {
            name: "object_array_facade_returns_jni_array_ref",
            run: () => {
                const stringClass = JNIEnv.FindClass("java/lang/String");
                try {
                    const javaString = stringClass.$staticCall("valueOf", "(I)Ljava/lang/String;", 2026) as any;
                    const separator = stringClass.$staticCall("valueOf", "(I)Ljava/lang/String;", 0) as any;
                    try {
                        const accessor = javaString.$method("split", "(Ljava/lang/String;)[Ljava/lang/String;");
                        const summary = accessor.withLocal((parts: any) => {
                            const texts = readObjectArrayTexts(parts);
                            assertCondition(parts.$length === 2, `expected split length 2, got ${parts.$length}`);
                            assertCondition(texts.join("|") === "2|26", `expected split texts 2|26, got ${texts.join("|")}`);
                            return texts.join("|");
                        }, separator);
                        return `value=${summary}`;
                    } finally {
                        separator.$unref();
                        javaString.$unref();
                    }
                } finally {
                    stringClass.$unref();
                }
            },
        },
        {
            name: "primitive_array_facade_uses_elements_buffer_explicitly",
            run: () => {
                const stringClass = JNIEnv.FindClass("java/lang/String");
                try {
                    const javaString = stringClass.$staticCall("valueOf", "(I)Ljava/lang/String;", 2026) as any;
                    try {
                        const accessor = javaString.$method("toCharArray", "()[C");
                        const summary = accessor.withLocal((charArray: any) => {
                            assertCondition(charArray.$length === 4, `expected char[] length 4, got ${charArray.$length}`);
                            assertCondition(
                                typeof charArray.$elements === "function",
                                "primitive array facade must expose explicit $elements() access",
                            );
                            assertCondition(
                                typeof charArray.$index !== "function",
                                "primitive array facade must not masquerade as a raw buffer",
                            );
                            return charArray.withElements(
                                (elements: any) => readCharElementsText(elements, charArray.$length),
                            );
                        });
                        assertCondition(summary === "2026", `expected char[] text 2026, got ${summary}`);
                        return `value=${summary}`;
                    } finally {
                        javaString.$unref();
                    }
                } finally {
                    stringClass.$unref();
                }
            },
        },
    ]);
}
