
import { nativeFunctionOptions } from "../consts.js"
import { CMemoryScanRes } from "../utils/scan.js"


const CM = new CModule(`
#include <glib.h>
#include <gum/gummemory.h>
#include <gum/gumdefs.h>

#define PAGE_SIZE 0x1000
#define GET_ADDR_PAGE(x) ((uintptr_t)(x) & ~(PAGE_SIZE - 1))
#define ADRP_IMM_LEN_MASK 0x1fffff
#define ADRP_FIXED28_24_BITSET_MASK (0b10000 << 24)
#define ADRP_PAGE_INSTR_MASK 0x9fffffe0

typedef struct _MemoryScanRes MemoryScanRes;
typedef struct _ScanUserData ScanUserData;

static gboolean on_match_fuzzy_adrp(GumAddress address, gsize size, gpointer user_data);

struct _ScanUserData
{
    gpointer target_address;
    gint align_offset;
};


struct _MemoryScanRes 
{
    GArray *results;
    ScanUserData *user_data;
};

void _dispose(const MemoryScanRes *res)
{
    g_array_free(res->results, TRUE);
}

static gboolean on_match_fuzzy_adrp(GumAddress address, gsize size, gpointer user_data)
{
    MemoryScanRes *scan_res = (MemoryScanRes *)user_data;
    const guintptr target_page = (guintptr)GET_ADDR_PAGE(scan_res->user_data->target_address);
    const guintptr align_offset = (guintptr)scan_res->user_data->align_offset;
    const guintptr addr_val = (guintptr)address - align_offset;
    const gpointer pc_addr = (gpointer)addr_val;
    
    // 4字节指令对齐
    if ((addr_val & (sizeof(guint32) - 1)) != 0)
        return TRUE;
    
    // 按pc页差进行匹配
    const guintptr pc_page = (guintptr)GET_ADDR_PAGE(address);
    const guint32 page_delta = (guint32)((target_page - pc_page) >> 12) & ADRP_IMM_LEN_MASK;
    const guint32 immlo = page_delta & 0b11;
    const guint32 immhi = page_delta >> 2;
    const guint32 op = 0x1;
    const guint32 adrp_sign =
        (op << 31) | 
        (immlo << 29) | 
        ADRP_FIXED28_24_BITSET_MASK | 
        (immhi << 5);

    if (((*(guint32 *)pc_addr) & ADRP_PAGE_INSTR_MASK) != (adrp_sign & ADRP_PAGE_INSTR_MASK))
        return TRUE;

    g_array_append_val(scan_res->results, pc_addr);
    return TRUE;
}

gpointer scan(const GumAddress base_address,
               const gsize size,
               const gchar *pattern_str,
               MemoryScanRes *const scan_res)
{
    if (scan_res == NULL)
        return NULL;

    scan_res->results = g_array_new(FALSE, FALSE, sizeof(gpointer));

    const GumMemoryRange range = {base_address, size};
    const GumMatchPattern *pattern = gum_match_pattern_new_from_string(pattern_str);

    gum_memory_scan(&range, pattern, on_match_fuzzy_adrp, scan_res);

    return scan_res->results;
}

`)


export class ScanAdrpCMod {
    static readonly cm: CModule = CM

    static readonly $scan = new NativeFunction(this.cm.scan, 'pointer', ['pointer', 'size_t', 'pointer', 'pointer'], nativeFunctionOptions)

    static scan(scanRange: { base: NativePointer, size: number }, pattern: string, targetAddr: NativePointer, alignOffset: number) {
        let matcheResults: NativePointer[] = []
        
        const userData = Memory.alloc(8 + 4)
        userData.writePointer(targetAddr)
        userData.add(8).writeU32(alignOffset)
        
        const scanRes = new CMemoryScanRes(userData)
        const { base, size } = scanRange
        this.$scan(
            base, size, Memory.allocUtf8String(pattern), scanRes.$handle,
        )
        if (scanRes.data.length > 0) {
            matcheResults = scanRes.data.toArray().map(v => v.readPointer())
        }
        this.$dispose(scanRes.$handle)
        return matcheResults
    }

    static readonly $dispose = new NativeFunction(this.cm._dispose, 'void', ['pointer'], nativeFunctionOptions)
}

