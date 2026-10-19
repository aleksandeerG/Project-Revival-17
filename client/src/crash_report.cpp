// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

#include <windows.h>

#include <atomic>
#include <cstdio>
#include <cstring>

namespace revival {
namespace {

constexpr int kMaxReports = 8;
std::atomic<int> g_reports{0};
uintptr_t g_seen[kMaxReports] = {};
std::atomic<int> g_seen_count{0};
uintptr_t g_base = 0;
uintptr_t g_end = 0;

bool in_game_image(uintptr_t address) {
    return g_base != 0 && address >= g_base && address < g_end;
}

bool readable(const void* address, size_t bytes) {
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(address, &info, sizeof(info)) == 0) return false;
    if (info.State != MEM_COMMIT) return false;
    const DWORD blocked = PAGE_NOACCESS | PAGE_GUARD;
    if ((info.Protect & blocked) != 0) return false;
    const auto start = reinterpret_cast<uintptr_t>(address);
    const auto region_end =
        reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize;
    return start + bytes <= region_end;
}

void describe(const char* name, uintptr_t value, char* out, size_t cap) {
    if (value == 0) {
        _snprintf_s(out, cap, _TRUNCATE, "%s=NULL", name);
    } else if (in_game_image(value)) {
        _snprintf_s(out, cap, _TRUNCATE, "%s=0x%llx(exe+0x%llx)", name,
                    (unsigned long long)value,
                    (unsigned long long)(value - g_base));
    } else {
        _snprintf_s(out, cap, _TRUNCATE, "%s=0x%llx", name,
                    (unsigned long long)value);
    }
}

LONG CALLBACK crash_report_handler(EXCEPTION_POINTERS* info) {
    if (info == nullptr || info->ExceptionRecord == nullptr ||
        info->ContextRecord == nullptr) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    const auto* record = info->ExceptionRecord;
    if (record->ExceptionCode != EXCEPTION_ACCESS_VIOLATION) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    const CONTEXT* c = info->ContextRecord;
    const auto pc = static_cast<uintptr_t>(record->ExceptionAddress != nullptr
                                               ? reinterpret_cast<uintptr_t>(
                                                     record->ExceptionAddress)
                                               : c->Rip);
    if (!in_game_image(pc)) return EXCEPTION_CONTINUE_SEARCH;
    for (int i = 0; i < g_seen_count.load(); ++i) {
        if (g_seen[i] == pc) return EXCEPTION_CONTINUE_SEARCH;
    }
    const int slot = g_reports.fetch_add(1);
    if (slot >= kMaxReports) return EXCEPTION_CONTINUE_SEARCH;
    g_seen[slot] = pc;
    g_seen_count.store(slot + 1);
    const ULONG_PTR kind = record->NumberParameters >= 1
                               ? record->ExceptionInformation[0] : 0;
    const ULONG_PTR target = record->NumberParameters >= 2
                                 ? record->ExceptionInformation[1] : 0;
    const char* verb = kind == 0 ? "read" : kind == 1 ? "write"
                                          : kind == 8 ? "execute" : "?";

    log_line("[CRASH] access violation: %s of 0x%llx at exe+0x%llx thread=%lu",
             verb, (unsigned long long)target,
             (unsigned long long)(pc - g_base), GetCurrentThreadId());

    struct Reg { const char* name; uintptr_t value; };
    const Reg regs[] = {
        {"rax", (uintptr_t)c->Rax}, {"rbx", (uintptr_t)c->Rbx},
        {"rcx", (uintptr_t)c->Rcx}, {"rdx", (uintptr_t)c->Rdx},
        {"rsi", (uintptr_t)c->Rsi}, {"rdi", (uintptr_t)c->Rdi},
        {"rbp", (uintptr_t)c->Rbp}, {"rsp", (uintptr_t)c->Rsp},
        {"r8",  (uintptr_t)c->R8},  {"r9",  (uintptr_t)c->R9},
        {"r10", (uintptr_t)c->R10}, {"r11", (uintptr_t)c->R11},
        {"r12", (uintptr_t)c->R12}, {"r13", (uintptr_t)c->R13},
        {"r14", (uintptr_t)c->R14}, {"r15", (uintptr_t)c->R15},
    };
    char line[512];
    line[0] = '\0';
    for (const Reg& reg : regs) {
        char one[96];
        describe(reg.name, reg.value, one, sizeof(one));
        strncat_s(line, sizeof(line), one, _TRUNCATE);
        strncat_s(line, sizeof(line), " ", _TRUNCATE);
    }
    log_line("[CRASH] %s", line);

    if (readable(reinterpret_cast<const void*>(pc - 48), 160)) {
        const auto* code = reinterpret_cast<const unsigned char*>(pc - 48);
        char hex[560];
        hex[0] = '\0';
        for (int i = 0; i < 160; ++i) {
            char byte[8];
            _snprintf_s(byte, sizeof(byte), _TRUNCATE, "%s%02x",
                        i == 48 ? "| " : "", code[i]);
            strncat_s(hex, sizeof(hex), byte, _TRUNCATE);
            strncat_s(hex, sizeof(hex), " ", _TRUNCATE);
        }
        log_line("[CRASH] code -48..+64 (fault after '|'): %s", hex);
    }

    struct Dump { const char* name; uintptr_t at; };
    const Dump dumps[] = {
        {"r9", (uintptr_t)c->R9}, {"rbx", (uintptr_t)c->Rbx},
        {"rdi", (uintptr_t)c->Rdi}, {"r10", (uintptr_t)c->R10},
    };
    for (const Dump& one : dumps) {
        if (one.at == 0 || !readable(reinterpret_cast<const void*>(one.at), 0x80)) {
            continue;
        }
        const auto* words = reinterpret_cast<const uintptr_t*>(one.at);
        char text[900];
        text[0] = '\0';
        for (int i = 0; i < 16; ++i) {
            char cell[56];
            _snprintf_s(cell, sizeof(cell), _TRUNCATE, "+0x%02x=0x%llx%s ",
                        i * 8, (unsigned long long)words[i],
                        words[i] == 0 ? "(NULL)" : "");
            strncat_s(text, sizeof(text), cell, _TRUNCATE);
        }
        log_line("[CRASH] %s -> %s", one.name, text);
    }

    if (c->Rsp != 0) {
        char frames[320];
        frames[0] = '\0';
        int found = 0;
        for (int i = 0; i < 256 && found < 12; ++i) {
            const auto slot = static_cast<uintptr_t>(c->Rsp) + i * 8;
            if (!readable(reinterpret_cast<const void*>(slot), 8)) continue;
            const auto value = *reinterpret_cast<const uintptr_t*>(slot);
            if (!in_game_image(value)) continue;
            char one[40];
            _snprintf_s(one, sizeof(one), _TRUNCATE, "exe+0x%llx ",
                        (unsigned long long)(value - g_base));
            strncat_s(frames, sizeof(frames), one, _TRUNCATE);
            ++found;
        }
        log_line("[CRASH] stack return addresses: %s", frames);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

}

void install_crash_reporter() {
    const auto module = GetModuleHandleW(nullptr);
    g_base = reinterpret_cast<uintptr_t>(module);
    if (g_base != 0) {
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(g_base);
        const auto* nt =
            reinterpret_cast<const IMAGE_NT_HEADERS64*>(g_base + dos->e_lfanew);
        g_end = g_base + nt->OptionalHeader.SizeOfImage;
    }
    if (AddVectoredExceptionHandler(0, crash_report_handler) == nullptr) {
        log_line("[CRASH] AddVectoredExceptionHandler failed error=%lu",
                 GetLastError());
        return;
    }
    log_line("[CRASH] reporter installed; will log registers and the faulting "
             "instruction for access violations inside FIFA17.exe (max %d, "
             "deduplicated by address)", kMaxReports);
}

}
