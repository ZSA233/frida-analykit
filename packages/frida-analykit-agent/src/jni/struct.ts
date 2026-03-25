

export const enum IndirectRefKind {
    kHandleScopeOrInvalid = 0,  // <<stack indirect reference table or invalid reference>>
    kLocal = 1,                 // <<local reference>>
    kGlobal = 2,                // <<global reference>>
    kWeakGlobal = 3,            // <<weak global reference>>
    kLastKind = kWeakGlobal
}


export const enum JNI_VT {
    FindClass = 6,
    FromReflectedMethod = 7,
    ToReflectedMethod = 9,
    GetSuperclass = 10,
    Throw = 13,
    ThrowNew = 14,
    ExceptionOccurred = 15,
    ExceptionDescribe = 16,
    ExceptionClear = 17,
    FatalError = 18,

    PushLocalFrame = 19,
    PopLocalFrame = 20,

    NewGlobalRef = 21,
    DeleteGlobalRef = 22,
    DeleteLocalRef = 23,
    NewLocalRef = 23,
    IsSameObject = 24,
    NewObject = 28,
    NewObjectV = 29,
    NewObjectA = 30,
    GetObjectClass = 31,
    GetMethodID = 33,

    CallObjectMethod = 34,
    CallObjectMethodV = 35,
    CallObjectMethodA = 36,

    CallBooleanMethod = 37,
    CallBooleanMethodV = 38,
    CallBooleanMethodA = 39,

    CallByteMethod = 40,
    CallByteMethodV = 41,
    CallByteMethodA = 42,

    CallCharMethod = 43,
    CallCharMethodV = 44,
    CallCharMethodA = 45,

    CallShortMethod = 46,
    CallShortMethodV = 47,
    CallShortMethodA = 48,

    CallIntMethod = 49,
    CallIntMethodV = 50,
    CallIntMethodA = 51,

    CallLongMethod = 52,
    CallLongMethodV = 53,
    CallLongMethodA = 54,

    CallFloatMethod = 55,
    CallFloatMethodV = 56,
    CallFloatMethodA = 57,

    CallDoubleMethod = 58,
    CallDoubleMethodV = 59,
    CallDoubleMethodA = 60,

    CallVoidMethod = 61,
    CallVoidMethodV = 62,
    CallVoidMethodA = 63,

    CallNonvirtualObjectMethod = 64,
    CallNonvirtualObjectMethodV = 65,
    CallNonvirtualObjectMethodA = 66,

    CallNonvirtualBooleanMethod = 67,
    CallNonvirtualBooleanMethodV = 68,
    CallNonvirtualBooleanMethodA = 69,

    CallNonvirtualByteMethod = 70,
    CallNonvirtualByteMethodV = 71,
    CallNonvirtualByteMethodA = 72,

    CallNonvirtualCharMethod = 73,
    CallNonvirtualCharMethodV = 74,
    CallNonvirtualCharMethodA = 75,

    CallNonvirtualShortMethod = 76,
    CallNonvirtualShortMethodV = 77,
    CallNonvirtualShortMethodA = 78,

    CallNonvirtualIntMethod = 79,
    CallNonvirtualIntMethodV = 80,
    CallNonvirtualIntMethodA = 81,

    CallNonvirtualLongMethod = 82,
    CallNonvirtualLongMethodV = 83,
    CallNonvirtualLongMethodA = 84,

    CallNonvirtualFloatMethod = 85,
    CallNonvirtualFloatMethodV = 86,
    CallNonvirtualFloatMethodA = 87,

    CallNonvirtualDoubleMethod = 88,
    CallNonvirtualDoubleMethodV = 89,
    CallNonvirtualDoubleMethodA = 90,

    CallNonvirtualVoidMethod = 91,
    CallNonvirtualVoidMethodV = 92,
    CallNonvirtualVoidMethodA = 93,
    
    GetFieldID = 94,
    GetObjectField = 95,
    GetBooleanField = 96,
    GetByteField = 97,
    GetCharField = 98,
    GetShortField = 99,
    GetIntField = 100,
    GetLongField = 101,
    GetFloatField = 102,
    GetDoubleField = 103,

    GetStaticMethodID = 113,
    
    CallStaticObjectMethod = 114,
    CallStaticObjectMethodV = 115,
    CallStaticObjectMethodA = 116,

    CallStaticBooleanMethod = 117,
    CallStaticBooleanMethodV = 118,
    CallStaticBooleanMethodA = 119,

    CallStaticByteMethod = 120,
    CallStaticByteMethodV = 121,
    CallStaticByteMethodA = 122,

    CallStaticCharMethod = 123,
    CallStaticCharMethodV = 124,
    CallStaticCharMethodA = 125,

    CallStaticShortMethod = 126,
    CallStaticShortMethodV = 127,
    CallStaticShortMethodA = 128,

    CallStaticIntMethod = 129,
    CallStaticIntMethodV = 130,
    CallStaticIntMethodA = 131,

    CallStaticLongMethod = 132,
    CallStaticLongMethodV = 133,
    CallStaticLongMethodA = 134,

    CallStaticFloatMethod = 135,
    CallStaticFloatMethodV = 136,
    CallStaticFloatMethodA = 137,

    CallStaticDoubleMethod = 138,
    CallStaticDoubleMethodV = 139,
    CallStaticDoubleMethodA = 140,

    CallStaticVoidMethod = 141,
    CallStaticVoidMethodV = 142,
    CallStaticVoidMethodA = 143,

    GetStaticFieldID = 144,
    GetStaticObjectField = 145,
    GetStaticBooleanField = 146,
    GetStaticByteField = 147,
    GetStaticCharField = 148,
    GetStaticShortField = 149,
    GetStaticIntField = 150,
    GetStaticLongField = 151,
    GetStaticFloatField = 152,
    GetStaticDoubleField = 153,

    GetStringLength = 164,
    GetStringChars = 165,
    ReleaseStringChars = 166,

    GetStringUTFLength = 168,
    GetStringUTFChars = 169,
    ReleaseStringUTFChars = 170,

    GetArrayLength = 171,
    GetObjectArrayElement = 173,

    GetBooleanArrayElements = 183,
    GetByteArrayElements = 184,
    GetCharArrayElements = 185,
    GetShortArrayElements = 186,
    GetIntArrayElements = 187,
    GetLongArrayElements = 188,
    GetFloatArrayElements = 189,
    GetDoubleArrayElements = 190,

    ReleaseBooleanArrayElements = 191,
    ReleaseByteArrayElements = 192,
    ReleaseCharArrayElements = 193,
    ReleaseShortArrayElements = 194,
    ReleaseIntArrayElements = 195,
    ReleaseLongArrayElements = 196,
    ReleaseFloatArrayElements = 197,
    ReleaseDoubleArrayElements = 198,

    RegisterNatives = 215,
    UnregisterNatives = 216,

    GetStringCritical = 224,
    DeleteWeakGlobalRef = 227,
    ExceptionCheck = 228,
}