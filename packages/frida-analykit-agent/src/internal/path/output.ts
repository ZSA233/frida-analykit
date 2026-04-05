const DOT_ONLY_SEGMENT = /^\.+$/

export function normalizeOutputTag(value: string, fallback: string = "default"): string {
    const trimmed = value.trim()
    if (trimmed.length === 0) {
        return ""
    }

    const normalized = trimmed
        .replace(/[\\/]+/g, "_")
        .replace(/[^A-Za-z0-9._-]+/g, "_")
        .replace(/^_+|_+$/g, "")

    if (normalized.length === 0 || DOT_ONLY_SEGMENT.test(normalized)) {
        return fallback
    }
    return normalized
}

export function normalizeRelativeOutputPath(path: string): string {
    const normalized = path.replace(/\\/g, "/")
    const segments = normalized.split("/")
    if (segments.length === 0) {
        throw new Error("[output path] empty relative path is not allowed")
    }
    for (const segment of segments) {
        if (segment.length === 0 || DOT_ONLY_SEGMENT.test(segment)) {
            throw new Error(`[output path] unsafe relative path segment: ${segment || "<empty>"}`)
        }
    }
    return segments.join("/")
}
