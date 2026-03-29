export {}

declare global {
    const console: {
        log: (...args: unknown[]) => void
        info: (...args: unknown[]) => void
        warn: (...args: unknown[]) => void
        error: (...args: unknown[]) => void
        debug: (...args: unknown[]) => void
    }
}
