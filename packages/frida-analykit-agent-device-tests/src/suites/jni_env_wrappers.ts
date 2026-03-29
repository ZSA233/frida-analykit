import { JNIEnv } from "@zsa233/frida-analykit-agent";

import { readCharElementsText, readUtf16PointerText } from "../readers.js";
import { assertCondition, runJavaSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runJniEnvWrappersSuite(): AgentUnitSuiteResult {
    return runJavaSuite("jni_env_wrappers", [
        {
            name: "call_byte_method_reads_java_byte",
            run: () => {
                const byteClass = JNIEnv.FindClass("java/lang/Byte");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(byteClass, "valueOf", "(B)Ljava/lang/Byte;");
                    const byteValue = JNIEnv.GetMethodID(byteClass, "byteValue", "()B");
                    const byteObject = JNIEnv.CallStaticObjectMethod(byteClass, valueOf, 7);
                    try {
                        const value = JNIEnv.CallByteMethod(byteObject, byteValue);
                        assertCondition(typeof value.toByte === "function", "CallByteMethod must return a jbyte wrapper");
                        const actual = value.toByte();
                        assertCondition(actual === 7, `expected byte value 7, got ${actual}`);
                        return `value=${actual}`;
                    } finally {
                        byteObject.$unref();
                    }
                } finally {
                    byteClass.$unref();
                }
            },
        },
        {
            name: "call_long_method_returns_jlong_wrapper",
            run: () => {
                const expected = 5000000000;
                const longClass = JNIEnv.FindClass("java/lang/Long");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(longClass, "valueOf", "(J)Ljava/lang/Long;");
                    const longValue = JNIEnv.GetMethodID(longClass, "longValue", "()J");
                    const longObject = JNIEnv.CallStaticObjectMethod(longClass, valueOf, expected);
                    try {
                        const value = JNIEnv.CallLongMethod(longObject, longValue) as { toLong?: () => number };
                        assertCondition(typeof value.toLong === "function", "CallLongMethod must return a jlong wrapper");
                        const actual = value.toLong();
                        assertCondition(actual === expected, `expected long value ${expected}, got ${actual}`);
                        return `value=${actual}`;
                    } finally {
                        longObject.$unref();
                    }
                } finally {
                    longClass.$unref();
                }
            },
        },
        {
            name: "call_static_long_method_returns_jlong_wrapper",
            run: () => {
                const systemClass = JNIEnv.FindClass("java/lang/System");
                try {
                    const nanoTime = JNIEnv.GetStaticMethodID(systemClass, "nanoTime", "()J");
                    const value = JNIEnv.CallStaticLongMethod(systemClass, nanoTime) as { toLong?: () => number };
                    assertCondition(typeof value.toLong === "function", "CallStaticLongMethod must return a jlong wrapper");
                    const actual = value.toLong();
                    assertCondition(actual > 0, `expected positive nanoTime, got ${actual}`);
                    return `value=${actual}`;
                } finally {
                    systemClass.$unref();
                }
            },
        },
        {
            name: "utf8_helper_reads_and_releases_java_string",
            run: () => {
                const stringClass = JNIEnv.FindClass("java/lang/String");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(stringClass, "valueOf", "(I)Ljava/lang/String;");
                    const javaString = JNIEnv.CallStaticObjectMethod(stringClass, valueOf, 1234).$jstring;
                    try {
                        const utf8 = javaString.toUTF8String();
                        try {
                            const text = utf8.toString();
                            assertCondition(text === "1234", `expected UTF-8 text 1234, got ${text}`);
                            assertCondition(utf8.release(), "expected UTF-8 release to succeed");
                            return `value=${text}`;
                        } finally {
                            utf8.release();
                        }
                    } finally {
                        javaString.$unref();
                    }
                } finally {
                    stringClass.$unref();
                }
            },
        },
        {
            name: "string_critical_roundtrip_reads_utf16_and_releases_promptly",
            run: () => {
                const stringClass = JNIEnv.FindClass("java/lang/String");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(stringClass, "valueOf", "(I)Ljava/lang/String;");
                    const javaString = JNIEnv.CallStaticObjectMethod(stringClass, valueOf, 1234).$jstring;
                    try {
                        const criticalChars = JNIEnv.GetStringCritical(javaString);
                        try {
                            const length = JNIEnv.GetStringLength(javaString).toInt();
                            const text = readUtf16PointerText(criticalChars, length);
                            assertCondition(text === "1234", `expected critical UTF-16 text 1234, got ${text}`);
                            return `value=${text}`;
                        } finally {
                            JNIEnv.ReleaseStringCritical(javaString, criticalChars);
                        }
                    } finally {
                        javaString.$unref();
                    }
                } finally {
                    stringClass.$unref();
                }
            },
        },
        {
            name: "call_float_method_returns_jfloat_wrapper",
            run: () => {
                const expected = 1.5;
                const floatClass = JNIEnv.FindClass("java/lang/Float");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(floatClass, "valueOf", "(F)Ljava/lang/Float;");
                    const floatValue = JNIEnv.GetMethodID(floatClass, "floatValue", "()F");
                    const floatObject = JNIEnv.CallStaticObjectMethod(floatClass, valueOf, expected);
                    try {
                        const value = JNIEnv.CallFloatMethod(floatObject, floatValue) as { toFloat?: () => number };
                        assertCondition(typeof value.toFloat === "function", "CallFloatMethod must return a jfloat wrapper");
                        const actual = value.toFloat();
                        assertCondition(Math.abs(actual - expected) < 0.0001, `expected float value ${expected}, got ${actual}`);
                        return `value=${actual}`;
                    } finally {
                        floatObject.$unref();
                    }
                } finally {
                    floatClass.$unref();
                }
            },
        },
        {
            name: "call_double_method_returns_jdouble_wrapper",
            run: () => {
                const expected = 3.25;
                const doubleClass = JNIEnv.FindClass("java/lang/Double");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(doubleClass, "valueOf", "(D)Ljava/lang/Double;");
                    const doubleValue = JNIEnv.GetMethodID(doubleClass, "doubleValue", "()D");
                    const doubleObject = JNIEnv.CallStaticObjectMethod(doubleClass, valueOf, expected);
                    try {
                        const value = JNIEnv.CallDoubleMethod(doubleObject, doubleValue) as { toDouble?: () => number };
                        assertCondition(typeof value.toDouble === "function", "CallDoubleMethod must return a jdouble wrapper");
                        const actual = value.toDouble();
                        assertCondition(Math.abs(actual - expected) < 0.0000001, `expected double value ${expected}, got ${actual}`);
                        return `value=${actual}`;
                    } finally {
                        doubleObject.$unref();
                    }
                } finally {
                    doubleClass.$unref();
                }
            },
        },
        {
            name: "float_and_double_field_wrappers_use_correct_return_registers",
            run: () => {
                const floatExpected = 1.5;
                const doubleExpected = 3.25;
                const piExpected = 3.141592653589793;
                const floatClass = JNIEnv.FindClass("java/lang/Float");
                const doubleClass = JNIEnv.FindClass("java/lang/Double");
                const mathClass = JNIEnv.FindClass("java/lang/Math");
                try {
                    const floatValueOf = JNIEnv.GetStaticMethodID(floatClass, "valueOf", "(F)Ljava/lang/Float;");
                    const doubleValueOf = JNIEnv.GetStaticMethodID(doubleClass, "valueOf", "(D)Ljava/lang/Double;");
                    const floatFieldId = JNIEnv.GetFieldID(floatClass, "value", "F");
                    const doubleFieldId = JNIEnv.GetFieldID(doubleClass, "value", "D");
                    const piFieldId = JNIEnv.GetStaticFieldID(mathClass, "PI", "D");
                    const floatObject = JNIEnv.CallStaticObjectMethod(floatClass, floatValueOf, floatExpected);
                    const doubleObject = JNIEnv.CallStaticObjectMethod(doubleClass, doubleValueOf, doubleExpected);
                    try {
                        const floatValue = JNIEnv.GetFloatField(floatObject, floatFieldId).toFloat();
                        const doubleValue = JNIEnv.GetDoubleField(doubleObject, doubleFieldId).toDouble();
                        const piValue = JNIEnv.GetStaticDoubleField(mathClass, piFieldId).toDouble();
                        assertCondition(
                            Math.abs(floatValue - floatExpected) < 0.0001,
                            `expected Float.value == ${floatExpected}, got ${floatValue}`,
                        );
                        assertCondition(
                            Math.abs(doubleValue - doubleExpected) < 0.0000001,
                            `expected Double.value == ${doubleExpected}, got ${doubleValue}`,
                        );
                        assertCondition(
                            Math.abs(piValue - piExpected) < 0.0000001,
                            `expected Math.PI == ${piExpected}, got ${piValue}`,
                        );
                        return `float=${floatValue}, double=${doubleValue}, pi=${piValue}`;
                    } finally {
                        floatObject.$unref();
                        doubleObject.$unref();
                    }
                } finally {
                    mathClass.$unref();
                    doubleClass.$unref();
                    floatClass.$unref();
                }
            },
        },
        {
            name: "primitive_array_elements_wrappers_are_raw_buffers",
            run: () => {
                const stringClass = JNIEnv.FindClass("java/lang/String");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(stringClass, "valueOf", "(I)Ljava/lang/String;");
                    const toCharArray = JNIEnv.GetMethodID(stringClass, "toCharArray", "()[C");
                    const javaString = JNIEnv.CallStaticObjectMethod(stringClass, valueOf, 1234).$jstring;
                    try {
                        const charArray = JNIEnv.CallObjectMethod(javaString, toCharArray).$jcharArray;
                        try {
                            const elements = JNIEnv.GetCharArrayElements(charArray);
                            try {
                                const text = readCharElementsText(elements, charArray.$length);
                                assertCondition(text === "1234", `expected char[] contents 1234, got ${text}`);
                                return `value=${text}`;
                            } finally {
                                JNIEnv.ReleaseCharArrayElements(charArray, elements, 0);
                            }
                        } finally {
                            charArray.$unref();
                        }
                    } finally {
                        javaString.$unref();
                    }
                } finally {
                    stringClass.$unref();
                }
            },
        },
        {
            name: "field_id_wrapper_reads_instance_and_static_fields",
            run: () => {
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const valueOf = JNIEnv.GetStaticMethodID(integerClass, "valueOf", "(I)Ljava/lang/Integer;");
                    const valueFieldId = JNIEnv.GetFieldID(integerClass, "value", "I");
                    const maxValueFieldId = JNIEnv.GetStaticFieldID(integerClass, "MAX_VALUE", "I");
                    const integerObject = JNIEnv.CallStaticObjectMethod(integerClass, valueOf, 42);
                    try {
                        assertCondition(
                            valueFieldId.toString().includes("jfieldID"),
                            "GetFieldID must return a jfieldID wrapper",
                        );
                        assertCondition(
                            maxValueFieldId.toString().includes("jfieldID"),
                            "GetStaticFieldID must return a jfieldID wrapper",
                        );
                        const instanceValue = JNIEnv.GetIntField(integerObject, valueFieldId).toInt();
                        const staticValue = JNIEnv.GetStaticIntField(integerClass, maxValueFieldId).toInt();
                        assertCondition(instanceValue === 42, `expected Integer.value == 42, got ${instanceValue}`);
                        assertCondition(
                            staticValue === 2147483647,
                            `expected Integer.MAX_VALUE == 2147483647, got ${staticValue}`,
                        );
                        return `instance=${instanceValue}, static=${staticValue}`;
                    } finally {
                        integerObject.$unref();
                    }
                } finally {
                    integerClass.$unref();
                }
            },
        },
        {
            name: "rpc_runtime_info_export_remains_available",
            run: () => {
                const exportsObject = rpc.exports as { rpcRuntimeInfo?: () => unknown };
                assertCondition(
                    typeof exportsObject.rpcRuntimeInfo === "function",
                    "installAgentUnitRpcExports must extend rpc.exports instead of replacing it",
                );
                return "rpcRuntimeInfo present";
            },
        },
    ]);
}
