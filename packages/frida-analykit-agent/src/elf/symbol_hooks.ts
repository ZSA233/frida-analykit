import { help } from "../helper/index.js"
import { installElfSymbolHook } from "./internal/hook_writer.js"
import { readCStringSafe } from "./internal/log.js"
import type { ElfModuleX } from "./module.js"
import type { Sym } from "./struct.js"
import type { ElfResolvedSymbol, ElfSymbolHookOptions, ElfSymbolHookResult, ElfSymbolHooksOptions } from "./types.js"

function createResolvedSymbol(symbol: Sym): ElfResolvedSymbol {
    return {
        name: symbol.name,
        linked: symbol.linked,
        hook: symbol.hook,
        implPtr: symbol.implPtr,
        relocPtr: symbol.relocPtr,
        size: symbol.st_size,
    }
}

function createLazySymbol(name: string, implPtr: NativePointer | null = null): Sym {
    return {
        name,
        relocPtr: null,
        hook: null,
        implPtr,
        linked: false,
        st_name: 0,
        st_info: 0,
        st_other: 0,
        st_shndx: 0,
        st_value: implPtr,
        st_size: 0,
    }
}

export class ElfSymbolHooks {
    readonly module: ElfModuleX
    readonly logTag: string

    private readonly _lazySymbols: Record<string, Sym> = {}
    private readonly _keepAlive: Record<string, NativePointer> = {}

    constructor(module: ElfModuleX, options: ElfSymbolHooksOptions = {}) {
        this.module = module
        this.logTag = options.logTag || module.name
        if (options.observeDlsym !== false) {
            this._installDlsymObserver()
        }
    }

    resolve(name: string): ElfResolvedSymbol | null {
        return this.findSymbol(name)
    }

    findSymbol(name: string): ElfResolvedSymbol | null {
        const symbol = this._findRawSymbol(name)
        return symbol ? createResolvedSymbol(symbol) : null
    }

    listSymbols(): ElfResolvedSymbol[] {
        const symbols = [...(this.module.dynSymbols || []), ...Object.values(this._lazySymbols)]
        return symbols.map(createResolvedSymbol)
    }

    addressMap(): Record<string, ElfResolvedSymbol> {
        const output: Record<string, ElfResolvedSymbol> = {}
        for (const symbol of this.listSymbols()) {
            if (symbol.hook) {
                output[String(symbol.hook)] = symbol
            }
            if (symbol.implPtr) {
                output[String(symbol.implPtr)] = symbol
            }
            if (!symbol.implPtr && symbol.relocPtr) {
                output[String(symbol.relocPtr)] = symbol
            }
        }
        return output
    }

    attach<RetType extends NativeFunctionReturnType, ArgTypes extends NativeFunctionArgumentType[] | []>(
        hookName: string,
        fn: AnyFunction,
        retType: RetType,
        argTypes: ArgTypes,
        options: ElfSymbolHookOptions = {},
    ): ElfSymbolHookResult {
        return installElfSymbolHook(
            {
                module: this.module,
                keepAlive: this._keepAlive,
                lazySymbols: this._lazySymbols,
            },
            hookName,
            fn,
            retType,
            argTypes,
            options,
        )
    }

    private _findRawSymbol(name: string): Sym | null {
        return this.module.findSymbol(name) || this._lazySymbols[name] || null
    }

    private _installDlsymObserver(): void {
        const installed = this.module.attachSymbol(
            "dlsym",
            (impl: AnyFunction, handle: NativePointer, name: NativePointer) => {
                const symbolName = readCStringSafe(name)
                const implementation = impl(handle, name) as NativePointer
                let symbol = this._findRawSymbol(symbolName)
                let warning = ""

                if (symbol && !symbol.implPtr) {
                    if (!implementation.isNull()) {
                        symbol.implPtr = implementation
                        symbol.st_value = implementation
                    } else {
                        warning = "[warn-null] "
                    }
                }

                if (!symbol && !implementation.isNull()) {
                    symbol = createLazySymbol(symbolName, implementation)
                    this._lazySymbols[symbolName] = symbol
                }

                help.$info(
                    `${warning}[ElfSymbolHooks::dlsym] handle[${handle}] name[${symbolName}] impl[${implementation}] hook[${symbol?.hook}]`,
                )

                if (symbol?.hook && symbol.implPtr) {
                    return symbol.hook
                }
                return implementation
            },
            "pointer",
            ["pointer", "pointer"],
        )
        if (!installed) {
            help.$debug(`[ElfSymbolHooks] ${this.module.name} has no writable dlsym relocation to observe`)
        }
    }
}
