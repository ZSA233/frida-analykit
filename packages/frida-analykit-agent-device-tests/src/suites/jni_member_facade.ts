import { JNIEnv } from "@zsa233/frida-analykit-agent/jni";

import { readJavaStringText } from "../readers.js";
import { assertCondition, formatError, runJavaSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runJniMemberFacadeSuite(): AgentUnitSuiteResult {
    return runJavaSuite("jni_member_facade", [
        {
            name: "bound_instance_method_accessor_and_direct_call",
            run: () => {
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const integerObject = integerClass.$staticCall("valueOf", "(I)Ljava/lang/Integer;", 41) as any;
                    try {
                        const accessor = integerObject.$method("toString", "()Ljava/lang/String;");
                        assertCondition(typeof accessor.call === "function", "$method must return a callable accessor");
                        assertCondition(
                            accessor.$id.toString().includes("jmethodID"),
                            "member accessor must expose its low-level jmethodID",
                        );
                        assertCondition(
                            integerObject.$methodIdFor("toString", "()Ljava/lang/String;").toString().includes("jmethodID"),
                            "$methodIdFor must preserve low-level lookup semantics",
                        );
                        const boundText = accessor.withLocal((javaString: any) => readJavaStringText(javaString));
                        const directJavaString = integerObject.$call("toString", "()Ljava/lang/String;") as any;
                        try {
                            const directText = readJavaStringText(directJavaString);
                            assertCondition(boundText === "41", `expected bound text 41, got ${boundText}`);
                            assertCondition(directText === "41", `expected direct text 41, got ${directText}`);
                            return `bound=${boundText}, direct=${directText}`;
                        } finally {
                            directJavaString.$unref();
                        }
                    } finally {
                        integerObject.$unref();
                    }
                } finally {
                    integerClass.$unref();
                }
            },
        },
        {
            name: "unbound_instance_method_accessor_on_jclass",
            run: () => {
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const integerObject = integerClass.$staticCall("valueOf", "(I)Ljava/lang/Integer;", 52) as any;
                    try {
                        const accessor = integerClass.$method("toString", "()Ljava/lang/String;");
                        const text = accessor.withLocal(integerObject, (javaString: any) => readJavaStringText(javaString));
                        assertCondition(text === "52", `expected text 52, got ${text}`);
                        return `value=${text}`;
                    } finally {
                        integerObject.$unref();
                    }
                } finally {
                    integerClass.$unref();
                }
            },
        },
        {
            name: "static_method_accessor_and_direct_call",
            run: () => {
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const accessor = integerClass.$staticMethod("valueOf", "(I)Ljava/lang/Integer;");
                    const viaAccessor = accessor.call(61) as any;
                    const viaDirect = integerClass.$staticCall("valueOf", "(I)Ljava/lang/Integer;", 62) as any;
                    try {
                        const left = viaAccessor.$call("intValue", "()I").toInt();
                        const right = viaDirect.$call("intValue", "()I").toInt();
                        assertCondition(left === 61, `expected accessor result 61, got ${left}`);
                        assertCondition(right === 62, `expected direct result 62, got ${right}`);
                        return `accessor=${left}, direct=${right}`;
                    } finally {
                        viaAccessor.$unref();
                        viaDirect.$unref();
                    }
                } finally {
                    integerClass.$unref();
                }
            },
        },
        {
            name: "constructor_accessor_and_direct_new",
            run: () => {
                const pointClass = JNIEnv.FindClass("android/graphics/Point");
                try {
                    const constructorAccessor = pointClass.$constructor("(II)V");
                    const pointA = constructorAccessor.newInstance(3, 4) as any;
                    const pointB = pointClass.$new("(II)V", 5, 6) as any;
                    try {
                        const ax = pointA.$getField("x", "I").toInt();
                        const ay = pointA.$getField("y", "I").toInt();
                        const bx = pointB.$getField("x", "I").toInt();
                        const by = pointB.$getField("y", "I").toInt();
                        assertCondition(ax === 3 && ay === 4, `expected pointA=(3,4), got (${ax},${ay})`);
                        assertCondition(bx === 5 && by === 6, `expected pointB=(5,6), got (${bx},${by})`);
                        return `pointA=${ax},${ay}; pointB=${bx},${by}`;
                    } finally {
                        pointA.$unref();
                        pointB.$unref();
                    }
                } finally {
                    pointClass.$unref();
                }
            },
        },
        {
            name: "bound_instance_field_get_and_set",
            run: () => {
                const pointClass = JNIEnv.FindClass("android/graphics/Point");
                try {
                    const point = pointClass.$new("(II)V", 1, 2) as any;
                    try {
                        const xField = point.$field("x", "I");
                        const before = xField.get().toInt();
                        xField.set(99);
                        const after = point.$getField("x", "I").toInt();
                        assertCondition(before === 1, `expected initial x=1, got ${before}`);
                        assertCondition(after === 99, `expected updated x=99, got ${after}`);
                        return `before=${before}, after=${after}`;
                    } finally {
                        point.$unref();
                    }
                } finally {
                    pointClass.$unref();
                }
            },
        },
        {
            name: "unbound_instance_field_accessor_on_jclass",
            run: () => {
                const pointClass = JNIEnv.FindClass("android/graphics/Point");
                try {
                    const point = pointClass.$new("(II)V", 7, 8) as any;
                    try {
                        const yField = pointClass.$field("y", "I");
                        const before = (yField.get(point) as { toInt: () => number }).toInt();
                        yField.set(point, 77);
                        const after = (pointClass.$getField(point, "y", "I") as { toInt: () => number }).toInt();
                        assertCondition(before === 8, `expected initial y=8, got ${before}`);
                        assertCondition(after === 77, `expected updated y=77, got ${after}`);
                        return `before=${before}, after=${after}`;
                    } finally {
                        point.$unref();
                    }
                } finally {
                    pointClass.$unref();
                }
            },
        },
        {
            name: "static_field_accessor_reads_constant",
            run: () => {
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const field = integerClass.$staticField("MAX_VALUE", "I");
                    const viaAccessor = (field.get() as { toInt: () => number }).toInt();
                    const viaDirect = (integerClass.$getStaticField("MAX_VALUE", "I") as { toInt: () => number }).toInt();
                    assertCondition(viaAccessor === 2147483647, `expected MAX_VALUE via accessor, got ${viaAccessor}`);
                    assertCondition(viaDirect === 2147483647, `expected MAX_VALUE via direct getter, got ${viaDirect}`);
                    return `value=${viaAccessor}`;
                } finally {
                    integerClass.$unref();
                }
            },
        },
        {
            name: "scoped_helper_uses_local_string_without_manual_unref",
            run: () => {
                const stringClass = JNIEnv.FindClass("java/lang/String");
                try {
                    const text = stringClass.$staticMethod("valueOf", "(I)Ljava/lang/String;")
                        .withLocal((javaString: any) => readJavaStringText(javaString), 2026);
                    assertCondition(text === "2026", `expected scoped string 2026, got ${text}`);
                    return `value=${text}`;
                } finally {
                    stringClass.$unref();
                }
            },
        },
        {
            name: "unbound_accessors_fail_fast_without_explicit_target",
            run: () => {
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                const pointClass = JNIEnv.FindClass("android/graphics/Point");
                try {
                    const methodAccessor = integerClass.$method("toString", "()Ljava/lang/String;") as any;
                    const fieldAccessor = integerClass.$field("value", "I") as any;
                    const staticFieldAccessor = integerClass.$staticField("MAX_VALUE", "I") as any;
                    const integerObject = integerClass.$staticCall("valueOf", "(I)Ljava/lang/Integer;", 1) as any;
                    const point = pointClass.$new("(II)V", 1, 2) as any;
                    const boundMethodAccessor = integerObject.$method("toString", "()Ljava/lang/String;") as any;
                    const boundFieldAccessor = point.$field("x", "I") as any;
                    let methodMessage = "";
                    let methodWithLocalMessage = "";
                    let fieldMessage = "";
                    let fieldGetMessage = "";
                    let fieldWithLocalMessage = "";
                    let boundMethodMessage = "";
                    let boundFieldGetMessage = "";
                    let boundFieldSetMessage = "";
                    let boundFieldWithLocalMessage = "";
                    let staticFieldGetMessage = "";
                    let staticFieldSetMessage = "";
                    let staticFieldWithLocalMessage = "";
                    try {
                        methodAccessor.call();
                        throw new Error("expected unbound method accessor to reject missing target");
                    } catch (error) {
                        methodMessage = formatError(error);
                    }
                    try {
                        methodAccessor.withLocal((javaString: any) => readJavaStringText(javaString));
                        throw new Error("expected unbound method accessor withLocal() to reject missing target");
                    } catch (error) {
                        methodWithLocalMessage = formatError(error);
                    }
                    try {
                        fieldAccessor.get();
                        throw new Error("expected unbound field accessor get() to reject missing target");
                    } catch (error) {
                        fieldGetMessage = formatError(error);
                    }
                    try {
                        fieldAccessor.set(1);
                        throw new Error("expected unbound field accessor to reject missing target");
                    } catch (error) {
                        fieldMessage = formatError(error);
                    }
                    try {
                        fieldAccessor.withLocal((value: any) => value.toInt());
                        throw new Error("expected unbound field accessor withLocal() to reject missing target");
                    } catch (error) {
                        fieldWithLocalMessage = formatError(error);
                    }
                    try {
                        boundMethodAccessor.withLocal(integerObject, (javaString: any) => readJavaStringText(javaString));
                        throw new Error("expected bound method accessor to reject an extra target");
                    } catch (error) {
                        boundMethodMessage = formatError(error);
                    }
                    try {
                        boundFieldAccessor.get(point);
                        throw new Error("expected bound field accessor get() to reject an extra target");
                    } catch (error) {
                        boundFieldGetMessage = formatError(error);
                    }
                    try {
                        boundFieldAccessor.set(point, 1);
                        throw new Error("expected bound field accessor set() to reject an extra target");
                    } catch (error) {
                        boundFieldSetMessage = formatError(error);
                    }
                    try {
                        boundFieldAccessor.withLocal(point, (value: any) => value.toInt());
                        throw new Error("expected bound field accessor withLocal() to reject an extra target");
                    } catch (error) {
                        boundFieldWithLocalMessage = formatError(error);
                    }
                    try {
                        staticFieldAccessor.get(integerClass);
                        throw new Error("expected static field accessor get() to reject an explicit class argument");
                    } catch (error) {
                        staticFieldGetMessage = formatError(error);
                    }
                    try {
                        staticFieldAccessor.set(integerClass, 1);
                        throw new Error("expected static field accessor set() to reject an explicit class argument");
                    } catch (error) {
                        staticFieldSetMessage = formatError(error);
                    }
                    try {
                        staticFieldAccessor.withLocal(integerClass, (value: any) => value.toInt());
                        throw new Error("expected static field accessor withLocal() to reject an explicit class argument");
                    } catch (error) {
                        staticFieldWithLocalMessage = formatError(error);
                    }
                    assertCondition(
                        methodMessage.includes("target object"),
                        `expected method guard to mention target object, got ${methodMessage}`,
                    );
                    assertCondition(
                        methodWithLocalMessage.includes("target object"),
                        `expected method withLocal guard to mention target object, got ${methodWithLocalMessage}`,
                    );
                    assertCondition(
                        fieldGetMessage.includes("target object"),
                        `expected field get guard to mention target object, got ${fieldGetMessage}`,
                    );
                    assertCondition(
                        fieldMessage.includes("target object"),
                        `expected field guard to mention target object, got ${fieldMessage}`,
                    );
                    assertCondition(
                        fieldWithLocalMessage.includes("target object"),
                        `expected field withLocal guard to mention target object, got ${fieldWithLocalMessage}`,
                    );
                    assertCondition(
                        boundMethodMessage.includes("already bound to a target"),
                        `expected bound method guard to mention bound target, got ${boundMethodMessage}`,
                    );
                    assertCondition(
                        boundFieldGetMessage.includes("already bound to a target"),
                        `expected bound field get guard to mention bound target, got ${boundFieldGetMessage}`,
                    );
                    assertCondition(
                        boundFieldSetMessage.includes("already bound to a target"),
                        `expected bound field set guard to mention bound target, got ${boundFieldSetMessage}`,
                    );
                    assertCondition(
                        boundFieldWithLocalMessage.includes("already bound to a target"),
                        `expected bound field withLocal guard to mention bound target, got ${boundFieldWithLocalMessage}`,
                    );
                    assertCondition(
                        staticFieldGetMessage.includes("already bound to a class"),
                        `expected static field get guard to mention bound class, got ${staticFieldGetMessage}`,
                    );
                    assertCondition(
                        staticFieldSetMessage.includes("already bound to a class"),
                        `expected static field set guard to mention bound class, got ${staticFieldSetMessage}`,
                    );
                    assertCondition(
                        staticFieldWithLocalMessage.includes("already bound to a class"),
                        `expected static field withLocal guard to mention bound class, got ${staticFieldWithLocalMessage}`,
                    );
                    return "guards triggered";
                } finally {
                    pointClass.$unref();
                    integerClass.$unref();
                }
            },
        },
    ]);
}
