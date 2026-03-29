import { JNIEnv } from "@zsa233/frida-analykit-agent/jni";

import { readJavaStringText } from "../readers.js";
import { assertCondition, runJavaSuite } from "../support.js";
import type { AgentUnitSuiteResult } from "../types.js";

export function runJniMemberFacadeNonvirtualSuite(): AgentUnitSuiteResult {
    return runJavaSuite("jni_member_facade_nonvirtual", [
        {
            name: "bound_nonvirtual_method_accessor_and_direct_call",
            run: () => {
                const objectClass = JNIEnv.FindClass("java/lang/Object");
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const integerObject = integerClass.$staticCall("valueOf", "(I)Ljava/lang/Integer;", 42) as any;
                    try {
                        const virtualJavaString = integerObject.$call("toString", "()Ljava/lang/String;") as any;
                        const accessor = integerObject.$nonvirtualMethod(objectClass, "toString", "()Ljava/lang/String;");
                        const expected = "java.lang.Integer@2a";
                        try {
                            assertCondition(
                                accessor.$declaringClass.$handle.equals(objectClass.$handle),
                                "bound nonvirtual accessor must expose its declaring class",
                            );
                            const virtualText = readJavaStringText(virtualJavaString);
                            const accessorText = accessor.withLocal((javaString: any) => readJavaStringText(javaString));
                            const directJavaString = integerObject.$nonvirtualCall(
                                objectClass,
                                "toString",
                                "()Ljava/lang/String;",
                            ) as any;
                            try {
                                const directText = readJavaStringText(directJavaString);
                                assertCondition(virtualText === "42", `expected virtual toString() == 42, got ${virtualText}`);
                                assertCondition(
                                    accessorText === expected,
                                    `expected bound nonvirtual text ${expected}, got ${accessorText}`,
                                );
                                assertCondition(
                                    directText === expected,
                                    `expected direct nonvirtual text ${expected}, got ${directText}`,
                                );
                                return `virtual=${virtualText}, nonvirtual=${accessorText}`;
                            } finally {
                                directJavaString.$unref();
                            }
                        } finally {
                            virtualJavaString.$unref();
                        }
                    } finally {
                        integerObject.$unref();
                    }
                } finally {
                    integerClass.$unref();
                    objectClass.$unref();
                }
            },
        },
        {
            name: "unbound_nonvirtual_method_accessor_on_jclass",
            run: () => {
                const objectClass = JNIEnv.FindClass("java/lang/Object");
                const integerClass = JNIEnv.FindClass("java/lang/Integer");
                try {
                    const integerObject = integerClass.$staticCall("valueOf", "(I)Ljava/lang/Integer;", 42) as any;
                    try {
                        const accessor = objectClass.$nonvirtualMethod("toString", "()Ljava/lang/String;");
                        const expected = "java.lang.Integer@2a";
                        assertCondition(
                            accessor.$declaringClass.$handle.equals(objectClass.$handle),
                            "unbound nonvirtual accessor must expose its declaring class",
                        );
                        assertCondition(
                            accessor.$id.toString().includes("jmethodID"),
                            "nonvirtual accessor must expose its low-level jmethodID",
                        );
                        const accessorText = accessor.withLocal(integerObject, (javaString: any) => readJavaStringText(javaString));
                        const directJavaString = objectClass.$nonvirtualCall(
                            integerObject,
                            "toString",
                            "()Ljava/lang/String;",
                        ) as any;
                        try {
                            const directText = readJavaStringText(directJavaString);
                            assertCondition(
                                accessorText === expected,
                                `expected unbound nonvirtual text ${expected}, got ${accessorText}`,
                            );
                            assertCondition(
                                directText === expected,
                                `expected direct unbound nonvirtual text ${expected}, got ${directText}`,
                            );
                            return `value=${accessorText}`;
                        } finally {
                            directJavaString.$unref();
                        }
                    } finally {
                        integerObject.$unref();
                    }
                } finally {
                    integerClass.$unref();
                    objectClass.$unref();
                }
            },
        },
    ]);
}
