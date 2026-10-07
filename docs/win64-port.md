# Running Return to Krondor as a native 64-bit process

Survey of the five game images (GOG v1.00.6) and what would have to change
for them to be a 64-bit process. Nothing in the install was modified. The
evidence is the PE headers of those images and the Ghidra output under
`out/decompiled/`.

On 64-bit Windows the game already runs. It runs as a 32-bit process under
WoW64. "Native" here means a PE32+ image (`IMAGE_FILE_MACHINE_AMD64`,
optional-header magic `0x20b`) in a 64-bit process, not a 32-bit process
hosted by a 64-bit OS. Windows 11 on ARM does not emulate 32-bit x86, so
these PE32 images do not run there either; an AMD64 build would at least be
eligible for the x64 emulator. ARM64 itself is a further port and is not
laid out below.

The decompiled `.c` files are not a source tree you can retarget. They are
pseudo-C with 32-bit pointer width, 32-bit struct offsets, and register
calling conventions baked in. A native build means recovering types and
recompiling, or rewriting the subsystems that have no 64-bit system DLL.
Mixing bitness is impossible: `RtK.exe` and the DLLs share one address
space, and a 64-bit process cannot load a 32-bit DLL.

## The five images

GOG's `Launcher.exe`, `CT.exe`, `unins000.exe`, and `GameuxInstallHelper.dll`
are packaging. They are not part of the game.

| Image | Role | Built (PE timestamp) | Version resource | Image base | Code |
| --- | --- | --- | --- | --- | --- |
| `RtK.exe` | MFC game shell. Exports the script-callable game API (`Char_*`, inventory) | 1998-12-09 | 1.00.6, PyroTechnix, "Game Engine for Return to Krondor" | `0x00400000` | 1.64 MB `.text` |
| `t3dll.dll` | True3D. C API, ~1,030 exports. DirectDraw, Direct3D, DirectSound, software rasterizer | 1998-12-08 | copyright string 1995–1998 PyroTechnix | `0x10000000` | 1.01 MB `.text` |
| `Rtlib32.dll` | Studio 7 runtime: resources, sprites, audio, window | 1998-10-31 | 2.1.0, 7th Level, "Studio 7 Runtime", copyright 1997 | `0x10000000` | 0.31 MB `.text` |
| `kronctrl.dll` | In-game controls (windows, grids, scroll bars) on top of Rtlib | 1998-11-06 | none | `0x10000000` | 0.07 MB `.text` |
| `RtkMovie.dll` | Cutscene player. One export, `CreateMoviePlayer` | 1998-11-01 | 1.00.0, PyroTechnix | `0x10000000` | 0.02 MB `.text` |

Every image is `IMAGE_FILE_MACHINE_I386` (`0x14c`) with optional-header magic
`0x10b` (PE32). Every one sets `IMAGE_FILE_32BIT_MACHINE`. None sets
`IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE`, `NX_COMPAT`, or `HIGH_ENTROPY_VA`.
None has an exception directory, a TLS directory, a CLR directory, or a
delay-import directory. The subsystem is `WINDOWS_GUI` and the subsystem
version is 4.0, i.e. the binary declares Windows 95 / NT 4.0. A 64-bit
image cannot advertise subsystem 4.0; the oldest x64 subsystem version is
5.2.

`RtK.exe` also has `IMAGE_FILE_RELOCS_STRIPPED` and no `.reloc` section, so
it can only load at `0x00400000`. That address is inside the low 2 GB and is
not a usable default for a 64-bit image (x64 exes are normally based at
`0x140000000`, and they need relocations because of ASLR). The four DLLs
all ask for `0x10000000` and do have relocations, which is how four DLLs
with the same preferred base coexist today. An x64 link has to emit
`.pdata` unwind tables as well as relocations; x64 exception dispatch reads
those tables and does not walk a frame chain.

Stack reserve is 1 MB and heap reserve is 1 MB in every image, with 4 KB
commit. Those are the Visual C++ defaults, not a game-specific limit.

Linker field in the optional header is 5.10 on every image. The Rich header
agrees: linker product id 2, build 7303 (`link.exe` 5.10.7303, Visual C++
5.0), plus `cvtres` 5.00.1668 where the binary has resources. Hundreds of
objects are stamped with product id 0, which is what the VC++ 5.0 compiler
produced — comp-id stamps in the Rich header become meaningful with VC++ 6.0,
and there are no VC6 `Utc13` entries here. A handful of objects also carry
linker 5.12.8034 (3 in `RtK.exe`, 7 in `t3dll.dll`). There is no `MSVCRT.dll`
or `MFC42.dll` import. The C runtime and, in `RtK.exe`, MFC are linked
statically.

Visual C++ 5.0 cannot emit a 64-bit image. The first Microsoft compiler
that targeted x64 was a later Visual Studio (2005 era). Any native build
uses a current MSVC or `clang-cl`, and the source has to be accepted by
that compiler.

## What the 32-bit ABI actually is

Windows x64 is LLP64, not LP64. `int`, `long`, and `DWORD` stay 32 bits.
The things that grow from 4 bytes to 8, and whose alignment grows from 4
to 8, are:

| Stays 32-bit | Becomes 64-bit |
| --- | --- |
| `int`, `unsigned`, `long`, `DWORD`, `UINT`, `BOOL`, `HRESULT`, resource ids, coordinates stored as `int` | pointers, `size_t`, `ptrdiff_t`, `intptr_t` |
| `LONG` used as a style bitfield or an error code | `LONG_PTR`, `UINT_PTR`, `DWORD_PTR`, `LPARAM`, `WPARAM`, `LRESULT` |
| on-disk `u32` fields (see below) | `HANDLE`, `HWND`, `HDC`, `HINSTANCE`, `HMODULE`, `HGDIOBJ` |
| | every vtable slot, every function pointer |

A struct that embeds a pointer changes size, and every field after that
pointer changes offset. VC++ 5.0's default packing aligns a pointer to 4.
A current x64 compiler aligns it to 8, so a struct written as
`{ int a; void *p; int b; }` is 12 bytes on x86 and 24 on x64. The
decompiled code never names that struct. It uses byte offsets
(`*(int *)((int)this + 0x1c)`, `param_1[0x13]`) computed for 4-byte
pointers. Those constants are the port. They are not reusable as source.

`RtK.exe`'s recovered calling conventions (10,514 functions):

| Convention | Count | Where the arguments live on x86 |
| --- | ---: | --- |
| `__stdcall` | 4,953 | stack, callee pops |
| `__cdecl` | 2,373 | stack, caller pops |
| `__thiscall` | 1,844 | `this` in `ECX`, rest on the stack, callee pops |
| `__fastcall` | 1,338 | first two integer args in `ECX`/`EDX` |
| unknown | 6 | |

`t3dll.dll` is almost all `__cdecl` (1,477 of 1,580). `Rtlib32.dll` is
almost all `__stdcall` (1,201 of 1,501). Windows x64 has one calling
convention: the first four integer/pointer arguments in `RCX`, `RDX`, `R8`,
`R9`, `this` in `RCX`, caller-allocated shadow space, caller pops. The
keywords `__stdcall`, `__cdecl`, `__thiscall`, and `__fastcall` are accepted
on x64 and ignored. Arguments still arrive in `RCX`, `RDX`, `R8`, and `R9`.

Two x86 return habits show up in the decompilation and disappear on x64:

- Floating-point returns are x87 `ST(0)`, which Ghidra prints as `float10`.
  There are 4,185 `float10` mentions in `t3dll.c` and 932 in `RtK.c`. x64
  MSVC returns `float` and `double` in `XMM0` and does not have an 80-bit
  `long double`. Values that today quietly keep 80 bits of intermediate
  precision will round to 32 or 64. Lighting, collision, and camera code
  in True3D is where that will show up.
- 64-bit integer results come back in `EDX:EAX`. Ghidra prints those as
  `undefined8` / `CONCAT44` (226 in `t3dll.c`, 53 in `RtK.c`). On x64 the
  same value belongs in `RAX`. `t3dMMXProcessor` is one of these: it is
  `__fastcall`, runs `CPUID`, tests EDX bit 23 (the MMX feature bit), and
  the decompiler reconstructs a 64-bit return whose low half is the only
  part the caller checks.

C++ exceptions are the other ABI that does not carry over. x86 MSVC
registers an `EXCEPTION_REGISTRATION_RECORD` at `fs:[0]` on entry and tears
it down on exit. `RtK.exe`'s `.text` contains 1,115 copies of
`mov eax, fs:[0]` and 1,228 copies of `mov fs:[0], ecx`. The decompiled
form is the `ExceptionList` local (3,971 mentions in `RtK.c`). The function
table has 3,003 `Unwind@` funclets and 24 `Catch@` funclets. `RtkMovie.dll`
has the same pattern at a much smaller scale (12 `mov eax, fs:[0]`).
`t3dll.dll`, `Rtlib32.dll`, and `kronctrl.dll` do not install those frames;
they were built without C++ EH. x64 does not use `fs:[0]` for this. The
compiler emits unwind info in `.pdata`, and the funclets are not source.
They get regenerated from real `try`/`catch`, or the code is rewritten
without exceptions.

`RtK.exe` does have RTTI, because MFC and the classic iostream library were
compiled with it, and because the game's own exception types need it for
`catch`. The `.?AV` names are MFC (`CWnd`, `CWinApp`, `CDialog`,
`CPtrList`, `CMapPtrToPtr`, …), the old iostreams (`istream`, `ofstream`,
`filebuf`, not `std::`), and `type_info`. The game's own throwable types
appear as pointer-to type descriptors (`.PAVCGameException@@`,
`.PAVCGameD3DException@@`, `.PAVCGameNoCDException@@`,
`.PAVCGameFileException@@`, `.PAVCGameLoadException@@`,
`.PAVCGameDbFileOutputException@@`). Most game classes have no RTTI. Log
strings name `CAudioMixer`, `CBookshelf`, `GameWindow`, and so on, but
those classes were not compiled with `/GR`.

## What should not change

On-disk formats are already width-explicit little-endian integers. Resource
ids, chunk offsets, and sizes are `u16`/`u32`, not pointers. Widening them
would stop the game reading its own archives, including a 32-bit build's
archives. In particular the RTKRES header signature at file offset `0x04`
is the two bytes `0x3233` (`"32"`). That is a format magic checked by
`ResCreateFile`. It is not a statement about the CPU, and a 64-bit port
does not rewrite it.

The same split exists inside the resource runtime. The engine copies that
header onto a runtime handle at byte `0x2a0` and then uses handle offsets
(`ResSetEntryId` writes handle `+0x2f8`, which is file field `0x58` plus
the `0x2a0` prefix). The prefix is in-memory state. Its size is only `0x2a0`
while every pointer inside it is 4 bytes. The file image stays; the prefix
does not. See [`rtkres-write.md`](rtkres-write.md).

`unsigned int` wrapping also stays, as long as nobody "fixes" `uint` to
`size_t`. `CreateMoviePlayer` returns success as a 32-bit wrap:

```c
/* CreateMoviePlayer, RtkMovie.dll */
*param_1 = (int)puVar1;
ExceptionList = local_c;
return (-(uint)(*param_1 != 0) & 0x7ffbff00) + 0x80040100;
```

`0x7FFBFF00 + 0x80040100` is `2^32`, so a 32-bit `unsigned int` yields
`S_OK` (0) on success and `0x80040100` on failure. Windows x64 keeps
`unsigned int` at 32 bits, so this expression still wraps. It breaks if the
type is widened, and it is a bad transcription of what the source almost
certainly wrote (`return p ? S_OK : error`). Prefer the source-level
statement.

ANSI entry points (`CreateWindowExA`, `SendMessageA`, `RegOpenKeyExA`,
`GetOpenFileNameA`, …) still exist on x64. The game has no `W` imports.
A Unicode conversion is not required for a correct port.

## Changes that are mechanical once the types are real

These are real source edits, but a current Windows SDK already has the
64-bit form. They are not a reason to rewrite a subsystem.

**Window extra bytes.** `GetWindowLongA` / `SetWindowLongA` truncate a
pointer on x64. The index tells you which sites matter:

| Index | Name | On x64 |
| --- | --- | --- |
| `-4` | `GWL_WNDPROC` | pointer. Used in Rtlib and in MFC. Use `SetWindowLongPtrA` and `GWLP_WNDPROC` |
| `-6` | `GWL_HINSTANCE` | pointer. One read in `RtK.exe`. Use `GWLP_HINSTANCE` |
| `-12` (`-0xc`) | `GWL_ID` | still a 32-bit control id |
| `-16` (`-0x10`) | `GWL_STYLE` | still a 32-bit bitfield |
| `-20` (`-0x14`) | `GWL_EXSTYLE` | still a 32-bit bitfield |
| `-26` (`-0x1a`) | `GCL_STYLE` | still a 32-bit class style (`GetClassLongA` in Rtlib and in MFC) |

`GWL_HWNDPARENT` (`-8`) is also pointer-sized. It does not appear in these
decompilations. `GWL_USERDATA` (`-21`) does not either.

`Rtlib32.dll` subclasses the main window by storing a raw code address and
saving the previous proc in a `LONG`:

```c
/* Rtlib32.dll — installs a wndproc, then saves the previous one */
LVar1 = SetWindowLongA(*(HWND *)(DAT_1005cfa0 + 0xcd8), -4, 0x1001e570);
*(LONG *)(DAT_1005cfa0 + 0xc8c) = LVar1;
```

`0x1001e570` is a function inside this DLL (base `0x10000000`). The source
was a function pointer. The previous proc is stored at handle offset
`0xc8c` as a 32-bit `LONG`. On x64 both the API and the field have to be
pointer-sized, and the offset `0xc8c` moves if any earlier field in that
object is a pointer. The same pattern is in the statically linked MFC in
`RtK.exe` (`SetWindowLongA(hwnd, -4, proc)`, and one `GetWindowLongA(..., -6)`
for `GWL_HINSTANCE`). `GWL_STYLE` / `GWL_EXSTYLE` / `GWL_ID` sites can stay
on the non-`Ptr` API, but using `Ptr` for all of them is the usual edit and
is harmless for the 32-bit indices.

**MFC 4.2 cannot be relinked.** `RtK.exe` registers the static-MFC window
classes `AfxWnd42s`, `AfxFrameOrView42s`, `AfxMDIFrame42s`,
`AfxOleControl42s`, and `AfxControlBar42s`. The `42` is MFC 4.2 (the
version shipped with VC++ 5.0); the `s` means the static library, which
matches the absence of `MFC42.dll` in the import table. That library is
32-bit x86 code. Current Visual Studio still ships MFC for x64, and its
window procedures already call `SetWindowLongPtr`, but the object layout is
not the 1997 layout. `CString` in this binary is the old reference-counted
class, not `CStringT`. `CPtrArray`, `CPtrList`, and `CMapPtrToPtr` store
pointers with 4-byte stride. Message maps, `AfxOldWndProc`, and the module
state (`AFX_MODULE_STATE`) all change size. Plan on building the shell
against a current MFC and fixing every class that derives from `CWnd` /
`CWinApp` / `CDialog`, not on feeding the decompiled MFC back to the
compiler. The decompiled range that is mostly MFC is the high address end
of `RtK.c` (the `AfxGetThread` body lives around `0x0058c5a5`).

**The old iostreams have to go.** `.?AVistream@@`, `.?AVofstream@@`, and
`.?AVfilebuf@@` are the pre-standard `<iostream.h>` library that VC++ 5.0
linked by default. It is not in a current CRT. Call sites become
`std::fstream` or C `FILE*`.

**The static VC5 CRT goes away with the compiler.** Imports such as
`HeapCreate`, `TlsAlloc`, `RaiseException`, `IsBadReadPtr`, `IsBadWritePtr`,
`IsBadCodePtr`, `GetStartupInfoA`, and `MultiByteToWideChar` are the CRT's,
not the game's. `IsBadReadPtr` in particular should not be reimplemented;
the modern CRT does not use it. `RtlUnwind` is imported by `RtkMovie.dll`
for the x86 EH teardown (`FUN_10001880`) and has no role in an x64 build.

**Callbacks already described by mangled exports.** Five `Rtlib32.dll`
exports still carry VC++ mangled names. Demangled, they are all `__cdecl`:

| Export | Signature |
| --- | --- |
| `RtAddScriptReplacementFunc` | `void (unsigned int, void (__cdecl *)(void))` |
| `RtCallScriptReplacementFunc` | `int (unsigned int)` |
| `RtKEditText` | `int (int, unsigned int, unsigned int, unsigned int, unsigned int)` |
| `RtKillInternalTimer` | `void (void *, unsigned int)` |
| `RtSetInternalTimer` | `void (void *, unsigned int, int, void (__stdcall *)(unsigned int), int)` |

The timer callback takes an `unsigned int`, not a pointer. Anything that
stuffs a pointer through that slot is already truncated to 32 bits and
needs a wider argument type, not just a recompile. `__stdcall` versus
`__cdecl` on the function-pointer types stops mattering on x64, provided
every caller is recompiled with the callee.

**Win32 that is present on x64 and is not the hard part.** GDI
(`CreateDIBSection`, `BitBlt`, `CreateFontA`), the common dialogs, the
registry, `WINSPOOL`, `COMCTL32` image lists, `ole32` `CoInitialize`, and
WinMM (`timeGetTime`, `waveOut*`, `midiOut*`, `mciSendCommandA`,
`joySetCapture`, `mmio*`) all have 64-bit versions. `MSACM32` does too.
DirectSound is imported from `DSOUND.dll` as ordinal 1, which is
`DirectSoundCreate`; `t3dll.dll` also exports `t3dGetDirectSoundObject`,
`t3dSuspendDirectSound`, and `t3dResumeDirectSound`. DirectSound's COM
objects still need a recompile against the x64 headers (vtable stride),
but the DLL exists. Joystick and MCI are legacy; they are not the reason
a port fails to link.

## The renderer is the blocking change

`t3dll.dll` imports `DirectDrawCreate` and `DirectDrawEnumerateA` from
`DDRAW.dll` and nothing from `d3dim.dll` or `d3drm.dll`. Direct3D is reached
by `QueryInterface` on the DirectDraw object. `RtK.exe` says so in its own
strings: "DirectX version 6 or higher does not appear to be installed" and
"capabilities usually found in drivers beginning with DirectX 5." The shell
then calls `t3dCreateRenderContextWithDirect3D`,
`t3dCreateDirect3DDeviceList`, `t3dDirect3DAddWorld`, and the `t3dDDraw*`
surface API (`t3dDDrawLockBackBuffer`, `t3dDDrawLockOverlay`,
`t3dDDrawFlipToGDI`, gamma, color key, stretch buffer).

64-bit Windows does not ship a 64-bit `ddraw.dll`. The DLL exists only as
a 32-bit image under SysWOW64, and a PE32+ process cannot load it. DirectX
5/6 immediate-mode interfaces (`IDirectDraw`, `IDirectDrawSurface`,
`IDirect3DDevice` of that era) were never built for x64. Direct3D 9 was the
first Direct3D with a supported 64-bit runtime, and it is a different API.
There is no header-only fix.

The decompiled COM calls are the 32-bit stdcall vtable, with 4-byte slots.
`t3dDDrawIsSurfaceModeX` is a clean example. It zeros a buffer, writes
`dwSize = 0x6c` (108, which is `sizeof(DDSURFACEDESC)` on x86), calls
vtable slot `0x58 / 4 = 22` on the surface pointer stored at wrapper field
`param_1[3]`, and tests bit 21 of the caps. Slot 22 of
`IDirectDrawSurface` is `GetSurfaceDesc`, and bit 21 of `DDSCAPS` is
`DDSCAPS_MODEX`:

```c
/* t3dDDrawIsSurfaceModeX */
if (param_1[0x13] == 0)
  return 0;
local_6c[0] = 0x6c;   /* sizeof(DDSURFACEDESC) on x86 */
uVar2 = (**(code **)(*(int *)param_1[3] + 0x58))((int *)param_1[3], local_6c);
```

On x64 that slot would be byte offset `22 * 8 = 0xB0`, `this` would arrive
in `RCX` rather than on the stack, `lpSurface` inside `DDSURFACEDESC` would
be 8 bytes and the struct would no longer be 108 bytes, and the wrapper
field `param_1[3]` (byte 12) would no longer be the surface pointer. None
of that matters in practice, because there is no 64-bit DirectDraw to call.
Mode X is a VGA memory layout; it has no 64-bit successor.

`t3dll.c` has 391 calls of the form `(**(code **)(...))`. `RtK.c` has
1,976, most of those MFC and the game's own C++ objects rather than
DirectDraw. Every one of them is a 4-byte vtable slot.

What a native renderer can be instead:

- A Direct3D 11 or 12 (or Vulkan, or OpenGL) backend behind the existing
  `t3dCreateRenderContextWithDirect3D` / `t3dDDraw*` surface, as far as the
  shell actually uses them: lock a back buffer, blit, overlay, palette /
  color key, gamma, present, and the Direct3D transform/light path the
  shell turns on when a device survives `t3dIsDirect3DFeatureSupported`.
- Or the software rasterizer that is already in `t3dll.dll`, retargeted at
  a plain bitmap that GDI or a modern swapchain presents. That path is the
  part of the DLL that is algorithmically portable. It is also the part
  with the hand-written MMX.

### MMX and the software path

`t3dll.dll` has a writable section named `_MMXDATA` (0x88 bytes of
constants). Its `.text` contains 164 `movq` loads (`0F 6F`), 43 `movq`
stores (`0F 7F`), 13 `emms` (`0F 77`), and 2 `cpuid` (`0F A2`). There are
no SSE `movaps` hits. `t3dMMXProcessor` gates this on CPUID leaf 1, EDX bit
23, and `t3dSetRenderContextMMXEnabled` stores the flag at byte `0x474` of
the render context. x64 Windows requires SSE2 to boot, so the MMX feature
bit is always set on any CPU that can run the process; the check can
become "true". The instruction stream cannot stay. x64 MSVC has no inline
`__asm`. Those routines have to be rewritten as C or as SSE2/AVX
intrinsics. MMX aliases the x87 registers, which is why the code emits
`emms`; an SSE2 rewrite does not.

`RtK.exe` has a token amount of the same opcodes (one `cpuid`, a few
`emms`). The software span helpers (`t3dDrawTranslucentSpan*`) live in
`t3dll.dll`.

### Glide is already gone in this build

`t3dll.dll` exports a large Glide-named surface (`t3dGlideInit`,
`t3dGlideWriteFrameBuffer`, `t3dSetRenderContextGlideEnable`, …). There is
no `glide2x.dll` / `glide3x.dll` import and no `grSst*` string. The hardware
entry points are one stub at `0x10074ea0` (`t3dPromoteGlideTexture` and the
init / framebuffer / overlay / texture exports aliased to it) that returns
`0xffff3d3e`. The same value is this DLL's generic failure code;
`t3dGlideFPSEnable` returns it when `CreateCompatibleDC` fails.

What remains under Glide names is bookkeeping, not a 3dfx driver.
`t3dGlideSetPolygonCount` and `t3dGlideSetRegionCount` store a dword.
`t3dGlideGetGammaCorrection` returns `0.0` and `t3dGlideGetDepthBias`
returns `0`. `t3dGlideFPSEnable` is real GDI: it builds a 220×100, 16-bit
DIB (`BITMAPINFOHEADER.biSize` is `0x28`, which is still 40 bytes on x64)
and keeps the `HDC` at byte `0x3c` of the context and the DIB bits pointer
at byte `0x40`. Those two fields are pointers, so the offsets move, but the
call itself is `CreateDIBSection` and does not need Glide.

A 64-bit port can keep the hardware stubs failing. Nothing in this image
talks to a 3dfx driver.

## The movie player is a replaceable DLL

`RtK.exe` does not import `RtkMovie.dll`. It `LoadLibraryA`s it and
`GetProcAddress`es `CreateMoviePlayer`, and it already has failure strings
for a missing DLL, a missing export, and an unsupported method. That is a
real boundary: a 64-bit `RtkMovie.dll` that exports the same function can
be dropped in without the rest of the game knowing, once the pointer-sized
arguments in that signature are agreed.

Inside the DLL, playback is in-process DirectShow (the 1998 ActiveMovie
API). `CoCreateInstance` is called with `CLSCTX_INPROC_SERVER` (the pushed
context is `1`) and these GUIDs:

| GUID | Interface |
| --- | --- |
| `e436ebb3-524f-11ce-9f53-0020af0ba770` | `CLSID_FilterGraph` |
| `56a868a9-0ad4-11ce-b03a-0020af0ba770` | `IID_IGraphBuilder` |
| `56a868b1-0ad4-11ce-b03a-0020af0ba770` | `IID_IMediaControl` |
| `56a868b4-0ad4-11ce-b03a-0020af0ba770` | `IID_IVideoWindow` |
| `56a868b5-0ad4-11ce-b03a-0020af0ba770` | `IID_IBasicVideo` |
| `56a868c0-0ad4-11ce-b03a-0020af0ba770` | `IID_IMediaEventEx` |
| `00000001-0000-0000-c000-000000000046` | `IID_IClassFactory` (`CoGetClassObject`) |

`CreateMoviePlayer` allocates the player with `operator new(0x134)`. The
class factory is stored at offset `0x130` in that object, i.e. the last
4 bytes are one pointer. A 64-bit player object is larger than `0x134`
and that offset moves.

`quartz.dll` itself exists as a 64-bit DLL, so a strict recompile against
the DirectShow headers is imaginable. It is a poor plan for this release.
The cutscenes are XviD ([`README.md`](../README.md)), the decoder filter
GOG installs is 32-bit, and an in-process filter has to match the process.
The legacy Video Renderer also sits on DirectDraw. Replacing `RtkMovie.dll`
with a small 64-bit decoder (Media Foundation, or a bundled decoder) behind
`CreateMoviePlayer` is the change that matches how the exe already loads it.

## What "compile the decompiled C" would actually do

It would not produce a working 64-bit game. Concrete reasons, all visible
in `out/decompiled/`:

- Pointers, `int`, and `undefined4` are the same width in the text.
  `(int)this + 0x1c` is a byte offset, and `param_1[3]` is a pointer index.
  Both are wrong as soon as a pointer is 8 bytes.
- `operator new(0x134)` and `dwSize = 0x6c` are frozen 32-bit sizes.
- `__fastcall` functions take arguments in `ECX`/`EDX`. x64 will not.
- `float10` returns are x87. x64 MSVC will not generate that ABI, and the
  80-bit intermediates will not be there even if you call the same math.
- `ExceptionList` / `Catch@` / `Unwind@` are x86 EH. An x64 compiler emits
  tables from `try`/`catch` only.
- Immediate addresses such as the `0x1001e570` window procedure are this
  DLL's load address, not source.
- Vtable calls pass `this` on the stack and index by 4.
- `t3dMMXProcessor` and the `_MMXDATA` section are x86 machine code the
  decompiler only partly lifted (it left `cpuid_Version_info` as an
  intrinsic and a `CONCAT44` return).

The useful content of the pseudo-C is the map: which subsystem, which
export, which offset, which system DLL. Function addresses in the
`FUN_` names stay the way to find them (`python tools/show_func.py`).

## A practical order

1. **Keep shipping the PE32 build under WoW64** for x64 Windows. That path
   already works and does not require any of the edits above.
2. **Treat `RtkMovie.dll` as the first 64-bit piece**, because the exe
   binds it with `LoadLibrary` / `GetProcAddress` and the replacement does
   not have to link MFC or True3D. It still cannot be loaded by the
   existing 32-bit exe. It becomes useful only when the exe is 64-bit too,
   or as a test harness.
3. **Recover C types for `t3dll.dll`'s public structs** (render context,
   surface wrapper, the object whose MMX flag is at `+0x474`) before
   touching call sites. The export table is a C API and is mostly
   `__cdecl`, which is the friendliest of the four conventions to redeclare
   on x64. The body behind those exports is the MMX rasterizer and the
   DirectDraw COM layer.
4. **Replace DirectDraw/Direct3D 6 with one modern present path.** Leave
   the Glide exports as failures. Decide explicitly whether the software
   spans are being ported or rewritten; do not expect the `movq` sequences
   to assemble.
5. **Rebuild `Rtlib32.dll` and `kronctrl.dll` against the Windows SDK**,
   widening HWND/HDC fields and the window-long calls, and keeping every
   file struct at its current `u32` layout. The five mangled exports above
   are the script/timer boundary to freeze in a header.
6. **Rebuild `RtK.exe` against a current x64 MFC**, replace `<iostream.h>`,
   and let the compiler regenerate EH. The 71 exports (`Char_*` and the
   inventory functions) are the other half of the script boundary; the
   runtime calls back into the exe, so the exe and `Rtlib32.dll` have to
   move together.
7. **Expect numeric drift** anywhere True3D used x87 intermediates, and
   compare a 32-bit and a 64-bit frame before trusting combat or camera
   code.

No amount of linker flags turns these five files into that build. The
32-bit process is the program that exists today.
