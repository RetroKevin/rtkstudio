/* Loaded into the 32-bit game. Map, inventory, and the other menus
   redraw the cursor on top of a picture they do not clear. Each new
   cursor is stamped beside the last one, and that stale picture flips
   in and out. Before a cursor is drawn, put the previous spot back,
   unless the game has already drawn a new frame there. */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>

#define DDSD_CAPS        0x00000001
#define DDSD_HEIGHT      0x00000002
#define DDSD_WIDTH       0x00000004
#define DDSD_PIXELFORMAT 0x00001000
#define DDSCAPS_OFFSCREENPLAIN 0x00000040
#define DDSCAPS_SYSTEMMEMORY   0x00000800
#define DDBLTFAST_WAIT   0x00000010
#define DDLOCK_WAIT      0x00000001
#define DDLOCK_READONLY  0x00000010

typedef int (__cdecl *ApplyFn)(int obj, int id, int fast, void *src_rect, int *dest);
typedef HRESULT (WINAPI *BltFastFn)(void *self, DWORD x, DWORD y, void *src, RECT *src_rect, DWORD flags);
typedef HRESULT (WINAPI *GetDescFn)(void *self, void *desc);
typedef HRESULT (WINAPI *LockFn)(void *self, RECT *rect, void *desc, DWORD flags, HANDLE event);
typedef HRESULT (WINAPI *UnlockFn)(void *self, void *rect);
typedef HRESULT (WINAPI *CreateSurfaceFn)(void *self, void *desc, void **surf, void *unk);
typedef ULONG (WINAPI *ReleaseFn)(void *self);

static ApplyFn g_real;
static void *g_dd;
static void *g_hold;
static void *g_scratch;
static int g_hold_w, g_hold_h;
static int g_inside;

static RECT g_old;
static int g_old_w, g_old_h;
static int g_have_old;
static unsigned char *g_after;
static int g_after_bytes;

struct Desc {
    DWORD size;
    DWORD flags;
    DWORD height;
    DWORD width;
    LONG pitch;
    DWORD pad[4];
    void *bits;
    unsigned char rest[80];
};

static void note(const char *text)
{
    (void)text;
}

static BltFastFn bltfast_of(void *surf)
{
    return (BltFastFn)(*(void ***)surf)[7];
}

static int ensure_hold(void *dd, void *back, int w, int h)
{
    struct Desc have, want;
    CreateSurfaceFn create_surface;
    unsigned char raw[128];
    HRESULT hr;
    if (g_hold && g_scratch && g_dd == dd && g_hold_w == w && g_hold_h == h)
        return 1;
    if (g_hold) {
        ((ReleaseFn)(*(void ***)g_hold)[2])(g_hold);
        ((ReleaseFn)(*(void ***)g_scratch)[2])(g_scratch);
        g_hold = NULL;
        g_scratch = NULL;
    }
    ZeroMemory(&have, sizeof have);
    have.size = 108;
    if (FAILED(((GetDescFn)(*(void ***)back)[22])(back, &have)))
        return 0;
    ZeroMemory(raw, sizeof raw);
    memcpy(raw, &have, 108);
    ((DWORD *)raw)[0] = 108;
    ((DWORD *)raw)[1] = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT;
    ((DWORD *)raw)[2] = (DWORD)h;
    ((DWORD *)raw)[3] = (DWORD)w;
    ((DWORD *)raw)[26] = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_SYSTEMMEMORY;
    (void)want;
    create_surface = (CreateSurfaceFn)(*(void ***)dd)[6];
    hr = create_surface(dd, raw, &g_hold, NULL);
    if (FAILED(hr))
        return 0;
    hr = create_surface(dd, raw, &g_scratch, NULL);
    if (FAILED(hr))
        return 0;
    g_dd = dd;
    g_hold_w = w;
    g_hold_h = h;
    if (g_after_bytes < w * h * 2) {
        if (g_after)
            HeapFree(GetProcessHeap(), 0, g_after);
        g_after = (unsigned char *)HeapAlloc(GetProcessHeap(), 0, w * h * 2);
        g_after_bytes = w * h * 2;
    }
    return g_hold && g_scratch && g_after;
}

static int read_rect(void *back, RECT *rect, void *sys, unsigned char *out)
{
    struct Desc desc;
    int y, w, h;
    unsigned char *src;
    if (FAILED(bltfast_of(sys)(sys, 0, 0, back, rect, DDBLTFAST_WAIT)))
        return 0;
    if (!out)
        return 1;
    ZeroMemory(&desc, sizeof desc);
    desc.size = 108;
    if (FAILED(((LockFn)(*(void ***)sys)[25])(sys, NULL, &desc, DDLOCK_WAIT | DDLOCK_READONLY, NULL)))
        return 0;
    w = rect->right - rect->left;
    h = rect->bottom - rect->top;
    src = (unsigned char *)desc.bits;
    for (y = 0; y < h; y++)
        memcpy(out + y * w * 2, src + y * desc.pitch, w * 2);
    ((UnlockFn)(*(void ***)sys)[32])(sys, NULL);
    return 1;
}

static int still_there(void *back, RECT *rect, int w, int h)
{
    struct Desc desc;
    int y, match;
    unsigned char *src;
    if (FAILED(bltfast_of(g_scratch)(g_scratch, 0, 0, back, rect, DDBLTFAST_WAIT)))
        return 0;
    ZeroMemory(&desc, sizeof desc);
    desc.size = 108;
    if (FAILED(((LockFn)(*(void ***)g_scratch)[25])(g_scratch, NULL, &desc, DDLOCK_WAIT | DDLOCK_READONLY, NULL)))
        return 0;
    src = (unsigned char *)desc.bits;
    match = 1;
    for (y = 0; y < h; y++) {
        if (memcmp(src + y * desc.pitch, g_after + y * w * 2, w * 2) != 0) {
            match = 0;
            break;
        }
    }
    ((UnlockFn)(*(void ***)g_scratch)[32])(g_scratch, NULL);
    return match;
}

static int restore_under_cursor(int obj, int id, void *src_rect, int *dest)
{
    void *back, *dd, *table, *overlay;
    int w, h, x, y;
    RECT rect;
    struct Desc desc;
    MEMORY_BASIC_INFORMATION info;
    back = *(void **)(obj + 0x10);
    dd = *(void **)(obj + 4);
    table = *(void **)(obj + 0x20);
    if (!back || !dd || !table)
        return 0;
    if (!VirtualQuery(table, &info, sizeof info) || info.State != MEM_COMMIT)
        return 0;
    overlay = *(void **)((char *)table + (id - 1) * 0x10);
    if (!overlay || !VirtualQuery(overlay, &info, sizeof info) || info.State != MEM_COMMIT)
        return 0;
    if (src_rect) {
        w = ((int *)src_rect)[2] - ((int *)src_rect)[0];
        h = ((int *)src_rect)[3] - ((int *)src_rect)[1];
    } else {
        ZeroMemory(&desc, sizeof desc);
        desc.size = 108;
        if (FAILED(((GetDescFn)(*(void ***)overlay)[22])(overlay, &desc)))
            return 0;
        w = (int)desc.width;
        h = (int)desc.height;
    }
    x = dest[0];
    y = dest[1];
    if (w < 4 || h < 4 || w > 96 || h > 96 || x < 0 || y < 0)
        return 0;
    rect.left = x;
    rect.top = y;
    rect.right = x + w;
    rect.bottom = y + h;
    if (!ensure_hold(dd, back, w, h))
        return 0;
    if (g_have_old && g_old_w == w && g_old_h == h && still_there(back, &g_old, w, h))
        bltfast_of(back)(back, g_old.left, g_old.top, g_hold, NULL, DDBLTFAST_WAIT);
    if (!read_rect(back, &rect, g_hold, NULL))
        return 0;
    g_old = rect;
    g_old_w = w;
    g_old_h = h;
    return 1;
}

static int __cdecl apply_hook(int obj, int id, int fast, void *src_rect, int *dest)
{
    int prepared, result;
    if (g_inside || !g_real || !fast || !dest || obj == 0 || id < 1)
        return g_real(obj, id, fast, src_rect, dest);
    g_inside = 1;
    prepared = 0;
    __try {
        prepared = restore_under_cursor(obj, id, src_rect, dest);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        prepared = 0;
        g_have_old = 0;
        note("exception\r\n");
    }
    result = g_real(obj, id, fast, src_rect, dest);
    if (prepared) {
        __try {
            if (read_rect(*(void **)(obj + 0x10), &g_old, g_scratch, g_after))
                g_have_old = 1;
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            g_have_old = 0;
        }
    }
    g_inside = 0;
    return result;
}

static int patch_import(HMODULE mod)
{
    unsigned char *base;
    IMAGE_DOS_HEADER *dos;
    IMAGE_NT_HEADERS *nt;
    IMAGE_IMPORT_DESCRIPTOR *imp;
    DWORD rva;
    if (!mod)
        return 0;
    base = (unsigned char *)mod;
    dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return 0;
    nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva)
        return 0;
    for (imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + rva); imp->Name; imp++) {
        const char *dll = (const char *)(base + imp->Name);
        IMAGE_THUNK_DATA *hint;
        IMAGE_THUNK_DATA *iat;
        if (lstrcmpiA(dll, "t3dll.dll") != 0)
            continue;
        hint = (IMAGE_THUNK_DATA *)(base + imp->OriginalFirstThunk);
        iat = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
        for (; hint->u1.AddressOfData; hint++, iat++) {
            IMAGE_IMPORT_BY_NAME *name;
            DWORD old;
            if (hint->u1.Ordinal & IMAGE_ORDINAL_FLAG32)
                continue;
            name = (IMAGE_IMPORT_BY_NAME *)(base + hint->u1.AddressOfData);
            if (lstrcmpA((char *)name->Name, "t3dDDrawApplyOverlay") != 0)
                continue;
            VirtualProtect(&iat->u1.Function, sizeof(DWORD), PAGE_EXECUTE_READWRITE, &old);
            g_real = (ApplyFn)iat->u1.Function;
            iat->u1.Function = (DWORD)apply_hook;
            VirtualProtect(&iat->u1.Function, sizeof(DWORD), old, &old);
            return 1;
        }
    }
    return 0;
}

static DWORD WINAPI worker(LPVOID unused)
{
    int i;
    (void)unused;
    for (i = 0; i < 400; i++) {
        if (GetModuleHandleA("t3dll.dll") && patch_import(GetModuleHandleA(NULL))) {
            note("hooked\r\n");
            return 0;
        }
        Sleep(25);
    }
    note("missed\r\n");
    return 1;
}

static volatile LONG g_once;

__declspec(dllexport) void __cdecl RtkFrameAttach(void)
{
    /* cnc-ddraw owns the window and the mouse. */
    (void)g_once;
}

#if 0
__declspec(dllexport) void __cdecl RtkFrameAttachDisabled(void)
{
    HANDLE thread;
    if (InterlockedCompareExchange(&g_once, 1, 0) != 0)
        return;
    thread = CreateThread(NULL, 0, worker, NULL, 0, NULL);
    if (thread)
        CloseHandle(thread);
}
#endif

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    (void)inst;
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(inst);
    return TRUE;
}
