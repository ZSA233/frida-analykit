import { JNIEnv } from "./env.js";
import { jobject, registerJStringFactory } from "./refs.js";

export class UTF16JString {
    protected _length: number | null = null;
    protected readonly _jstr: jstring;
    protected _str: string | null = null;
    protected _cstrPtr: NativePointer = NULL;
    protected _released = false;

    protected readonly $getString = JNIEnv.GetStringChars;
    protected readonly $readString = (pointer: NativePointer, length: number): string =>
        pointer.readUtf16String(length) ?? "";
    protected readonly $releaser = JNIEnv.ReleaseStringChars;

    constructor(jstr: jstring) {
        this._jstr = jstr;
    }

    get $length(): number {
        return this._length ?? (this._length = JNIEnv.GetStringLength(this._jstr).toInt());
    }

    toString(): string {
        if (this._str !== null) {
            return this._str;
        }
        const cstr = this.$getString(this._jstr);
        this._cstrPtr = cstr;
        this._str = this.$readString(cstr, this.$length);
        return this._str;
    }

    isNull(): boolean {
        return this._jstr.$handle.isNull();
    }

    release(): boolean {
        if (this._cstrPtr.isNull()) {
            return false;
        }
        if (this._released) {
            return true;
        }
        this._released = true;
        this.$releaser(this._jstr, this._cstrPtr);
        return true;
    }
}

export class UTF8JString extends UTF16JString {
    protected readonly $getString = JNIEnv.GetStringUTFChars;
    protected readonly $readString = (pointer: NativePointer, length: number): string =>
        pointer.readUtf8String(length) ?? "";
    protected readonly $releaser = JNIEnv.ReleaseStringUTFChars;

    get $length(): number {
        return this._length ?? (this._length = JNIEnv.GetStringUTFLength(this._jstr).toInt());
    }
}

export class CriticalUTF16JString extends UTF16JString {
    protected readonly $getString = JNIEnv.GetStringCritical;
    protected readonly $releaser = JNIEnv.ReleaseStringCritical;

    release(): boolean {
        // GetStringCritical may keep the string pinned inside the VM, so this release path must stay explicit.
        return super.release();
    }
}

export class jstring extends jobject {
    private _str: string | undefined;

    toString(): string {
        if (this.$handle.isNull() || this._str !== undefined) {
            return this._str ?? "";
        }
        const utf16 = this.toUTF16String();
        try {
            const text = utf16.toString();
            this._str = text;
            return text;
        } finally {
            utf16.release();
        }
    }

    [Symbol.toPrimitive](hint: string): string {
        if (hint === "string") {
            return `<jstring: ${this.$handle}>[${this.$IndirectRefKind}]`;
        }
        return "default";
    }

    toUTF16String(): UTF16JString {
        return new UTF16JString(this);
    }

    toUTF8String(): UTF8JString {
        return new UTF8JString(this);
    }

    toCriticalUTF16String(): CriticalUTF16JString {
        return new CriticalUTF16JString(this);
    }
}

registerJStringFactory((handle, options) => new jstring(handle, options));
