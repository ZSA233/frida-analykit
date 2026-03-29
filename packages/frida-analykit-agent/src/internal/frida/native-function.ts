export const nativeFunctionOptions: NativeABI | NativeFunctionOptions = {
    exceptions: "propagate",
}

export function unwrapArgs(args: InvocationArguments, n: number): (unknown | NativePointer)[] {
    const list = []
    for (let i = 0; i < n; i++) {
        list.push(args[i])
    }
    return list
}
