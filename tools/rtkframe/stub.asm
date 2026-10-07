.386
.model flat, stdcall
assume fs:nothing

; Position-independent startup stub. Resolves LoadLibraryA and
; GetProcAddress from the loaded modules, loads rtkframe.dll, calls
; RtkFrameAttach, then jumps to the original RtK entry point.
.code

frame_stub proc
    pushad
    call    anchor
anchor:
    pop     ebp

    mov     eax, dword ptr fs:[30h]
    mov     eax, [eax+0Ch]
    lea     edx, [eax+14h]
    mov     ebx, [edx]
walk:
    cmp     ebx, edx
    je      finish
    mov     esi, [ebx+10h]
    test    esi, esi
    jz      nextmod
    cmp     word ptr [esi], 5A4Dh
    jne     nextmod
    mov     eax, [esi+3Ch]
    cmp     dword ptr [esi+eax], 4550h
    jne     nextmod
    mov     ecx, [esi+eax+78h]
    test    ecx, ecx
    jz      nextmod
    add     ecx, esi

    lea     eax, [ebp + (OFFSET s_load - OFFSET anchor)]
    call    find_export
    test    eax, eax
    jz      nextmod
    mov     edi, eax

    lea     eax, [ebp + (OFFSET s_get - OFFSET anchor)]
    call    find_export
    test    eax, eax
    jz      nextmod

    push    eax
    lea     eax, [ebp + (OFFSET s_dll - OFFSET anchor)]
    push    eax
    call    edi
    pop     edx
    test    eax, eax
    jz      finish

    lea     ecx, [ebp + (OFFSET s_attach - OFFSET anchor)]
    push    ecx
    push    eax
    call    edx
    test    eax, eax
    jz      finish
    call    eax
    jmp     finish

nextmod:
    mov     ebx, [ebx]
    jmp     walk

finish:
    popad
    mov     eax, 00577E80h
    jmp     eax
frame_stub endp

; eax = name, esi = module base, ecx = export directory.
; Returns the function in eax, or 0. Preserves ebx, ecx, edx, esi, edi, ebp.
find_export proc
    push    ebx
    push    ecx
    push    edx
    push    esi
    push    edi
    push    eax
    mov     edx, [ecx+18h]
    mov     edi, [ecx+20h]
    add     edi, esi
    xor     eax, eax
name_loop:
    cmp     eax, edx
    jge     missing
    push    eax
    push    edi
    mov     ebx, [edi+eax*4]
    add     ebx, esi
    mov     eax, [esp+8]
cmp_loop:
    mov     cl, [ebx]
    mov     ch, [eax]
    cmp     cl, ch
    jne     cmp_fail
    test    cl, cl
    jz      cmp_ok
    inc     ebx
    inc     eax
    jmp     cmp_loop
cmp_ok:
    pop     edi
    pop     eax
    mov     ecx, [esp+10h]
    mov     ebx, [ecx+24h]
    add     ebx, esi
    movzx   eax, word ptr [ebx+eax*2]
    mov     ebx, [ecx+1Ch]
    add     ebx, esi
    mov     eax, [ebx+eax*4]
    add     eax, esi
    jmp     found
cmp_fail:
    pop     edi
    pop     eax
    inc     eax
    jmp     name_loop
missing:
    xor     eax, eax
found:
    add     esp, 4
    pop     edi
    pop     esi
    pop     edx
    pop     ecx
    pop     ebx
    ret
find_export endp

s_load      db "LoadLibraryA", 0
s_get       db "GetProcAddress", 0
s_dll       db "rtkframe.dll", 0
s_attach    db "RtkFrameAttach", 0

end
