/* 32-bit launcher. Starts RtK.exe suspended, loads rtkframe.dll into it,
   then lets the process run. The game image on disk is not modified. */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static int fail(const wchar_t *msg)
{
    fwprintf(stderr, L"rtkframe: %s (%lu)\n", msg, GetLastError());
    return 1;
}

static int inject(HANDLE proc, const wchar_t *dll)
{
    SIZE_T bytes = (lstrlenW(dll) + 1) * sizeof(wchar_t);
    LPVOID remote;
    HANDLE thread;
    DWORD code = 0;
    FARPROC load;
    HMODULE local;
    FARPROC start;
    LPTHREAD_START_ROUTINE remote_start;

    remote = VirtualAllocEx(proc, NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote) return fail(L"VirtualAllocEx");
    if (!WriteProcessMemory(proc, remote, dll, bytes, NULL)) return fail(L"WriteProcessMemory");
    load = GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW");
    if (!load) return fail(L"LoadLibraryW");
    thread = CreateRemoteThread(proc, NULL, 0, (LPTHREAD_START_ROUTINE)load, remote, 0, NULL);
    if (!thread) return fail(L"CreateRemoteThread LoadLibraryW");
    WaitForSingleObject(thread, 10000);
    GetExitCodeThread(thread, &code);
    CloseHandle(thread);
    if (!code) return fail(L"LoadLibraryW returned NULL");

    local = LoadLibraryW(dll);
    if (!local) return fail(L"LoadLibraryW local");
    start = GetProcAddress(local, "RtkFrameAttach");
    if (!start) return fail(L"RtkFrameAttach");
    remote_start = (LPTHREAD_START_ROUTINE)((BYTE *)code + ((BYTE *)start - (BYTE *)local));
    thread = CreateRemoteThread(proc, NULL, 0, remote_start, NULL, 0, NULL);
    FreeLibrary(local);
    if (!thread) return fail(L"CreateRemoteThread RtkFrameAttach");
    WaitForSingleObject(thread, 10000);
    CloseHandle(thread);
    VirtualFreeEx(proc, remote, 0, MEM_RELEASE);
    return 0;
}

int wmain(int argc, wchar_t **argv)
{
    wchar_t cmdline[32768];
    size_t used = 0;
    int i;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    int rc;

    if (argc < 4) {
        fwprintf(stderr, L"usage: rtkframe.exe <dll> <workdir> <RtK.exe> [args]\n");
        return 2;
    }
    cmdline[0] = 0;
    for (i = 3; i < argc; i++) {
        const wchar_t *a = argv[i];
        int quote = (a[0] == 0) || wcschr(a, L' ') || wcschr(a, L'\t');
        size_t need = wcslen(a) + (quote ? 3 : 1) + (used ? 1 : 0);
        if (used + need >= sizeof cmdline / sizeof cmdline[0]) return fail(L"command line too long");
        if (used) cmdline[used++] = L' ';
        if (quote) cmdline[used++] = L'"';
        lstrcpyW(cmdline + used, a);
        used += wcslen(a);
        if (quote) cmdline[used++] = L'"';
        cmdline[used] = 0;
    }
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(argv[3], cmdline, NULL, NULL, FALSE, CREATE_SUSPENDED,
            NULL, argv[2], &si, &pi))
        return fail(L"CreateProcessW");
    rc = inject(pi.hProcess, argv[1]);
    if (rc) {
        TerminateProcess(pi.hProcess, 1);
    } else {
        AllowSetForegroundWindow(pi.dwProcessId);
        ResumeThread(pi.hThread);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return rc;
}
