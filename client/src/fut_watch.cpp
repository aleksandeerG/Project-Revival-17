// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

#include <atomic>
#include <cstdio>
#include <cstring>
#include <psapi.h>
#include <tlhelp32.h>

namespace revival {

namespace {

constexpr uintptr_t kSubmitVtableRva = 0x38dc120;
constexpr uintptr_t kRegistrationRva = 0x6ec9ad0;
constexpr uintptr_t kClubSubmitRva = 0x6ec9ba0;
constexpr size_t kEventCapacity = 128;
constexpr size_t kInstructionBytes = 128;
constexpr size_t kStackWords = 6;

constexpr unsigned char kAptFinalizeSignature[] = {
    0x59, 0xb9, 0x01, 0xa2, 0x42, 0x5d, 0x99, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x1c, 0x00, 0x00, 0x00,
};
constexpr size_t kAptOpcodeDelta = 0x2b;
constexpr int kAptCopyCount = 2;

constexpr DWORD64 kSubmitEnableMask = 0x0f;
constexpr DWORD64 kSubmitControlMask = 0xffULL << 16;
constexpr DWORD64 kSubmitConfiguration =
    (1ULL << 0) | (1ULL << 2) |
    (3ULL << 16) | (2ULL << 18) |
    (3ULL << 20) | (2ULL << 22);

struct WatchEvent {
    std::atomic<bool> ready{false};
    DWORD thread_id = 0;
    DWORD64 dr6 = 0;
    DWORD64 rip = 0;
    DWORD64 rsp = 0;
    DWORD64 rax = 0;
    DWORD64 rbx = 0;
    DWORD64 rcx = 0;
    DWORD64 rdx = 0;
    DWORD64 rsi = 0;
    DWORD64 rdi = 0;
    DWORD64 r8 = 0;
    DWORD64 r9 = 0;
    DWORD64 r10 = 0;
    DWORD64 r11 = 0;
    DWORD64 r12 = 0;
    DWORD64 r13 = 0;
    DWORD64 r14 = 0;
    DWORD64 r15 = 0;
    DWORD64 stack[kStackWords] = {};
    unsigned char code[kInstructionBytes] = {};
    unsigned char caller_code[kInstructionBytes] = {};
    char rdi_text[64] = {};
    char rdx_text[96] = {};
    DWORD64 rax_words[16] = {};
    unsigned char rax_words_count = 0;
    unsigned char code_before = 0;
    unsigned char caller_code_before = 0;
    unsigned char stack_words = 0;
};

WatchEvent g_events[kEventCapacity];
std::atomic<size_t> g_event_count{0};
std::atomic<size_t> g_dropped_events{0};
std::atomic<size_t> g_ignored_external_hits{0};
std::atomic<DWORD64> g_apt_hit_mask{0};
std::atomic<bool> g_apt_watch_enabled{false};
std::atomic<bool> g_apt_scan_requested{false};
std::atomic<bool> g_apt_watch_ready{false};
std::atomic<DWORD> g_apt_waiter_thread{0};
std::atomic<uintptr_t> g_flux_load_movie_site{0};
std::atomic<uintptr_t> g_flux_initialize_site{0};
std::atomic<DWORD> g_flux_waiter_thread{0};
std::atomic<bool> g_flux_watch_ready{false};

std::atomic<uintptr_t> g_futdb_request_site{0};
std::atomic<bool> g_futdb_watch_ready{false};
std::atomic<DWORD> g_futdb_waiter_thread{0};
uintptr_t g_game_begin = 0;
uintptr_t g_game_end = 0;

void safe_capture_memory(void* destination, const void* source, size_t length,
                         unsigned char* captured) {
    *captured = 0;
    __try {
        memcpy(destination, source, length);
        *captured = static_cast<unsigned char>(length);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        memset(destination, 0, length);
    }
}

LONG CALLBACK submit_watch_handler(PEXCEPTION_POINTERS exception) {
    if (exception == nullptr || exception->ExceptionRecord == nullptr ||
        exception->ContextRecord == nullptr ||
        exception->ExceptionRecord->ExceptionCode != EXCEPTION_SINGLE_STEP) {
        return EXCEPTION_CONTINUE_SEARCH;
    }

    CONTEXT* context = exception->ContextRecord;
    DWORD64 hit_bits = context->Dr6 & 0xf;
    if (hit_bits == 0) return EXCEPTION_CONTINUE_SEARCH;

    if (context->Rip < g_game_begin || context->Rip >= g_game_end) {
        g_ignored_external_hits.fetch_add(1, std::memory_order_relaxed);
        context->Dr6 &= ~0xfULL;
        return EXCEPTION_CONTINUE_EXECUTION;
    }

    const DWORD64 apt_hits = hit_bits & 0xc;
    if (apt_hits != 0) {
        if (apt_hits & 0x4) context->Dr7 &= ~(3ULL << 4);
        if (apt_hits & 0x8) context->Dr7 &= ~(3ULL << 6);
        const DWORD64 already = g_apt_hit_mask.fetch_or(apt_hits);
        hit_bits &= ~(already & apt_hits);
        if (hit_bits == 0) {
            context->Dr6 &= ~0xfULL;
            return EXCEPTION_CONTINUE_EXECUTION;
        }
    }

    const size_t index = g_event_count.fetch_add(1, std::memory_order_relaxed);
    if (index < kEventCapacity) {
        WatchEvent& event = g_events[index];
        event.thread_id = GetCurrentThreadId();
        event.dr6 = hit_bits;
        event.rip = context->Rip;
        event.rsp = context->Rsp;
        event.rax = context->Rax;
        event.rbx = context->Rbx;
        event.rcx = context->Rcx;
        event.rdx = context->Rdx;
        event.rsi = context->Rsi;
        event.rdi = context->Rdi;
        event.r8 = context->R8;
        event.r9 = context->R9;
        event.r10 = context->R10;
        event.r11 = context->R11;
        event.r12 = context->R12;
        event.r13 = context->R13;
        event.r14 = context->R14;
        event.r15 = context->R15;

        safe_capture_memory(event.stack, reinterpret_cast<const void*>(context->Rsp),
                            sizeof(event.stack), &event.stack_words);
        event.stack_words = static_cast<unsigned char>(
            event.stack_words / sizeof(event.stack[0]));

        constexpr size_t kBefore = kInstructionBytes / 2;
        safe_capture_memory(event.code,
                            reinterpret_cast<const void*>(context->Rip - kBefore),
                            sizeof(event.code), &event.code_before);
        if (event.code_before != 0) event.code_before = kBefore;
        if (event.stack_words > 0) {
            safe_capture_memory(
                event.caller_code,
                reinterpret_cast<const void*>(event.stack[0] - kBefore),
                sizeof(event.caller_code), &event.caller_code_before);
            if (event.caller_code_before != 0) event.caller_code_before = kBefore;
        }
        unsigned char rax_bytes = 0;
        safe_capture_memory(event.rax_words,
                            reinterpret_cast<const void*>(context->Rax),
                            sizeof(event.rax_words), &rax_bytes);
        event.rax_words_count =
            static_cast<unsigned char>(rax_bytes / sizeof(event.rax_words[0]));

        unsigned char rdx_bytes = 0;
        safe_capture_memory(event.rdx_text,
                            reinterpret_cast<const void*>(context->Rdx),
                            sizeof(event.rdx_text) - 1, &rdx_bytes);
        event.rdx_text[sizeof(event.rdx_text) - 1] = 0;

        unsigned char text_bytes = 0;
        safe_capture_memory(event.rdi_text,
                            reinterpret_cast<const void*>(context->Rdi),
                            sizeof(event.rdi_text) - 1, &text_bytes);
        event.rdi_text[sizeof(event.rdi_text) - 1] = '\0';
        event.ready.store(true, std::memory_order_release);
    } else {
        g_dropped_events.fetch_add(1, std::memory_order_relaxed);
    }

    context->Dr6 &= ~0xfULL;
    return EXCEPTION_CONTINUE_EXECUTION;
}

bool table_is_ready(uintptr_t base, uintptr_t* registration_slot,
                    uintptr_t* submit_slot) {
    auto* table = reinterpret_cast<const uintptr_t*>(base + kSubmitVtableRva);
    __try {
        *registration_slot = table[0];
        *submit_slot = table[2];
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        *registration_slot = 0;
        *submit_slot = 0;
        return false;
    }
    return *registration_slot == base + kRegistrationRva &&
           *submit_slot == base + kClubSubmitRva;
}

int scan_region_collect(unsigned char* start, size_t size,
                        const unsigned char* needle, size_t needle_length,
                        uintptr_t* sites, int capacity, int found) {
    __try {
        size_t offset = 0;
        while (offset + needle_length <= size && found < capacity) {
            const size_t searchable = size - offset - (needle_length - 1);
            auto* candidate = reinterpret_cast<unsigned char*>(
                memchr(start + offset, needle[0], searchable));
            if (candidate == nullptr) break;
            const size_t i = static_cast<size_t>(candidate - start);
            offset = i + 1;
            if (memcmp(candidate, needle, needle_length) != 0) continue;
            if (i + kAptOpcodeDelta >= size) continue;
            sites[found++] = reinterpret_cast<uintptr_t>(candidate) + kAptOpcodeDelta;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
    return found;
}

int find_apt_opcode_sites(uintptr_t address_limit, uintptr_t* sites) {
    int found = 0;
    uintptr_t address = 0;
    while (address < address_limit && found < kAptCopyCount) {
        MEMORY_BASIC_INFORMATION mbi = {};
        if (VirtualQuery(reinterpret_cast<void*>(address), &mbi, sizeof(mbi)) == 0) {
            break;
        }
        const uintptr_t start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        const uintptr_t end = start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE &&
            !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            mbi.RegionSize >= sizeof(kAptFinalizeSignature) + kAptOpcodeDelta) {
            found = scan_region_collect(
                reinterpret_cast<unsigned char*>(start), mbi.RegionSize,
                kAptFinalizeSignature, sizeof(kAptFinalizeSignature), sites,
                kAptCopyCount, found);
        }
        if (end <= address) break;
        address = end;
    }
    return found;
}

unsigned int read_site_byte(uintptr_t site) {
    if (site == 0) return 0x100;
    __try {
        return *reinterpret_cast<const unsigned char*>(site);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0x100;
    }
}

void debug_configuration(uintptr_t apt_site0, uintptr_t apt_site1,
                         DWORD64* enable_mask, DWORD64* control_mask,
                         DWORD64* configuration) {
    *enable_mask = kSubmitEnableMask;
    *control_mask = kSubmitControlMask;
    *configuration = kSubmitConfiguration;
    if (apt_site0 != 0) {
        *enable_mask |= 0x30;
        *control_mask |= 0xfULL << 24;
        *configuration |= (1ULL << 4);
        *configuration |= 3ULL << 24;
    }
    if (apt_site1 != 0) {
        *enable_mask |= 0xc0;
        *control_mask |= 0xfULL << 28;
        if (apt_site1 == g_futdb_request_site.load(std::memory_order_acquire)) {
            *configuration |= (1ULL << 6);
        } else {
            *configuration |= (1ULL << 6) | (3ULL << 28);
        }
    }
}

bool arm_thread(DWORD thread_id, uintptr_t registration_slot,
                uintptr_t submit_slot, uintptr_t apt_site0,
                uintptr_t apt_site1, bool* conflict) {
    *conflict = false;
    HANDLE thread = OpenThread(THREAD_GET_CONTEXT | THREAD_SET_CONTEXT |
                                   THREAD_SUSPEND_RESUME | THREAD_QUERY_INFORMATION,
                               FALSE, thread_id);
    if (thread == nullptr) return false;

    bool armed = false;
    if (SuspendThread(thread) != static_cast<DWORD>(-1)) {
        CONTEXT context = {};
        context.ContextFlags = CONTEXT_DEBUG_REGISTERS;
        if (GetThreadContext(thread, &context)) {
            DWORD64 enable_mask = 0;
            DWORD64 control_mask = 0;
            DWORD64 configuration = 0;
            debug_configuration(apt_site0, apt_site1, &enable_mask,
                                &control_mask, &configuration);
            const bool already_ours =
                context.Dr0 == registration_slot && context.Dr1 == submit_slot &&
                (apt_site0 == 0 || context.Dr2 == apt_site0) &&
                (apt_site1 == 0 || context.Dr3 == apt_site1) &&
                (context.Dr7 & (enable_mask | control_mask)) == configuration;
            const bool slots_busy =
                ((context.Dr7 & 0x3) != 0 && context.Dr0 != registration_slot) ||
                ((context.Dr7 & 0xc) != 0 && context.Dr1 != submit_slot) ||
                (apt_site0 != 0 && (context.Dr7 & 0x30) != 0 &&
                 context.Dr2 != apt_site0) ||
                (apt_site1 != 0 && (context.Dr7 & 0xc0) != 0 &&
                 context.Dr3 != apt_site1);
            if (already_ours) {
                armed = true;
            } else if (slots_busy) {
                *conflict = true;
            } else {
                context.Dr0 = registration_slot;
                context.Dr1 = submit_slot;
                if (apt_site0 != 0) context.Dr2 = apt_site0;
                if (apt_site1 != 0) context.Dr3 = apt_site1;
                context.Dr6 &= ~0xfULL;
                context.Dr7 =
                    (context.Dr7 & ~(enable_mask | control_mask)) | configuration;
                armed = SetThreadContext(thread, &context) != FALSE;
            }
        }
        ResumeThread(thread);
    }
    CloseHandle(thread);
    return armed;
}

size_t arm_new_threads(uintptr_t registration_slot, uintptr_t submit_slot,
                       uintptr_t apt_site0, uintptr_t apt_site1,
                       DWORD* known_ids, size_t* known_count) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return 0;

    const DWORD process_id = GetCurrentProcessId();
    const DWORD current_thread = GetCurrentThreadId();
    size_t newly_armed = 0;
    THREADENTRY32 entry = {};
    entry.dwSize = sizeof(entry);
    if (Thread32First(snapshot, &entry)) {
        do {
            if (entry.th32OwnerProcessID != process_id ||
                entry.th32ThreadID == current_thread) {
                continue;
            }
            bool known = false;
            for (size_t i = 0; i < *known_count; ++i) {
                if (known_ids[i] == entry.th32ThreadID) {
                    known = true;
                    break;
                }
            }
            if (known) continue;

            bool conflict = false;
            if (arm_thread(entry.th32ThreadID, registration_slot, submit_slot,
                           apt_site0, apt_site1, &conflict)) {
                if (*known_count < 256) known_ids[(*known_count)++] = entry.th32ThreadID;
                newly_armed++;
            } else if (conflict) {
                log_line("[FUT-WATCH] thread %lu already uses a required debug "
                         "register; left untouched", entry.th32ThreadID);
                if (*known_count < 256) known_ids[(*known_count)++] = entry.th32ThreadID;
            }
        } while (Thread32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return newly_armed;
}

void format_code(const unsigned char* bytes, size_t length,
                 unsigned char before, char* output, size_t capacity) {
    output[0] = '\0';
    if (before == 0) return;
    size_t cursor = 0;
    for (size_t i = 0; i < length && cursor + 4 < capacity; ++i) {
        const int written = snprintf(output + cursor, capacity - cursor,
                                     i == before ? "|%02x" : "%02x", bytes[i]);
        if (written <= 0) break;
        cursor += static_cast<size_t>(written);
    }
}

void drain_events(uintptr_t base, size_t* drained) {
    const size_t reserved = g_event_count.load(std::memory_order_acquire);
    while (*drained < reserved && *drained < kEventCapacity) {
        WatchEvent& event = g_events[*drained];
        if (!event.ready.load(std::memory_order_acquire)) break;

        const DWORD64 hits = event.dr6 & 0xf;
        const bool flux_watch =
            g_flux_load_movie_site.load(std::memory_order_acquire) != 0;
        const bool futdb_watch =
            g_futdb_request_site.load(std::memory_order_acquire) != 0;
        const char* label =
            hits == 8 && futdb_watch ? "loadFUTDatabase request site" :
            hits == 1 ? "registration+0x00" :
            hits == 2 ? "users/club+0x10" :
            hits == 4 && flux_watch ? "FluxHub loadMovie opcode read" :
            hits == 8 && flux_watch ? "FluxHub InitializeScreen opcode read" :
            hits == 4 ? "APT FinalizeLogin callMethodPop copy0" :
            hits == 8 ? "APT FinalizeLogin callMethodPop copy1" : "multiple";
        char code[(kInstructionBytes * 3) + 2] = {};
        char caller_code[(kInstructionBytes * 3) + 2] = {};
        format_code(event.code, sizeof(event.code), event.code_before,
                    code, sizeof(code));
        format_code(event.caller_code, sizeof(event.caller_code),
                    event.caller_code_before, caller_code, sizeof(caller_code));
        log_line(
            "[FUT-WATCH] hit=%s thread=%lu rip=0x%llx rva=0x%llx "
            "rsp=0x%llx stack0=0x%llx stack1=0x%llx code=%s",
            label, event.thread_id, (unsigned long long)event.rip,
            (unsigned long long)(event.rip - base),
            (unsigned long long)event.rsp,
            (unsigned long long)(event.stack_words > 0 ? event.stack[0] : 0),
            (unsigned long long)(event.stack_words > 1 ? event.stack[1] : 0), code);
        log_line("[FUT-WATCH] callerCode=%s", caller_code);

        if (hits == 8 && futdb_watch) {
            const DWORD64 target =
                event.rax_words_count > 15 ? event.rax_words[15] : 0;
            log_line("[FUT-DB] dispatch receiver=0x%llx vtable=0x%llx "
                     "arg=0x%llx target[+0x78]=0x%llx",
                     (unsigned long long)event.rcx,
                     (unsigned long long)event.rax,
                     (unsigned long long)event.rdx,
                     (unsigned long long)target);
            log_line("[FUT-DB] looked-up value='%.90s'", event.rdx_text);
            char slots[16 * 19 + 1] = {};
            size_t cursor = 0;
            for (unsigned i = 0; i < event.rax_words_count && i < 16; ++i) {
                const int written =
                    snprintf(slots + cursor, sizeof(slots) - cursor, "%llx ",
                             (unsigned long long)event.rax_words[i]);
                if (written <= 0) break;
                cursor += static_cast<size_t>(written);
            }
            log_line("[FUT-DB] vtable slots: %s", slots);

            for (int which = 0; which < 2; ++which) {
                const DWORD64 address = which == 0 ? event.rax : target;
                if (address == 0) continue;
                HMODULE owner = nullptr;
                wchar_t name[MAX_PATH] = L"<unowned>";
                if (GetModuleHandleExW(
                        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                        reinterpret_cast<LPCWSTR>(address), &owner) &&
                    owner != nullptr) {
                    GetModuleBaseNameW(GetCurrentProcess(), owner, name, MAX_PATH);
                    log_line("[FUT-DB] %s 0x%llx -> %ls+0x%llx",
                             which == 0 ? "vtable" : "target",
                             (unsigned long long)address, name,
                             (unsigned long long)(address -
                                 reinterpret_cast<uintptr_t>(owner)));
                } else {
                    log_line("[FUT-DB] %s 0x%llx -> not owned by any loaded "
                             "module (heap or unmapped)",
                             which == 0 ? "vtable" : "target",
                             (unsigned long long)address);
                }
            }
        }
        log_line(
            "[FUT-WATCH] regs rax=%llx rbx=%llx rcx=%llx rdx=%llx "
            "rsi=%llx rdi=%llx r8=%llx r9=%llx r10=%llx r11=%llx "
            "r12=%llx r13=%llx r14=%llx r15=%llx",
            (unsigned long long)event.rax, (unsigned long long)event.rbx,
            (unsigned long long)event.rcx, (unsigned long long)event.rdx,
            (unsigned long long)event.rsi, (unsigned long long)event.rdi,
            (unsigned long long)event.r8, (unsigned long long)event.r9,
            (unsigned long long)event.r10, (unsigned long long)event.r11,
            (unsigned long long)event.r12, (unsigned long long)event.r13,
            (unsigned long long)event.r14, (unsigned long long)event.r15);
        for (char& ch : event.rdi_text) {
            const unsigned char byte = static_cast<unsigned char>(ch);
            if (byte == 0) break;
            if (byte < 0x20 || byte > 0x7e) ch = '.';
        }
        log_line("[FUT-WATCH] rdiText='%.63s'", event.rdi_text);
        ++*drained;
    }
}

}

DWORD WINAPI fut_submit_watch_worker(LPVOID parameter) {
    const uintptr_t watch_flags = reinterpret_cast<uintptr_t>(parameter);
    bool apt_byte_watch = (watch_flags & 1u) != 0;
    g_apt_watch_enabled.store(apt_byte_watch, std::memory_order_release);
    g_apt_scan_requested.store(false, std::memory_order_release);
    g_apt_watch_ready.store(false, std::memory_order_release);
    g_apt_waiter_thread.store(0, std::memory_order_release);
    const uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    g_game_begin = base;
    g_game_end = base + nt->OptionalHeader.SizeOfImage;
    uintptr_t registration_target = 0;
    uintptr_t submit_target = 0;
    bool mismatch_logged = false;
    for (;;) {
        if (table_is_ready(base, &registration_target, &submit_target)) break;
        if (!mismatch_logged && (registration_target != 0 || submit_target != 0)) {
            log_line(
                "[FUT-WATCH] waiting for submit vtable: slot0=0x%llx "
                "slot10=0x%llx expected={0x%llx,0x%llx}",
                (unsigned long long)registration_target,
                (unsigned long long)submit_target,
                (unsigned long long)(base + kRegistrationRva),
                (unsigned long long)(base + kClubSubmitRva));
            mismatch_logged = true;
        }
        Sleep(100);
    }

    if (AddVectoredExceptionHandler(1, submit_watch_handler) == nullptr) {
        log_line("[FUT-WATCH] AddVectoredExceptionHandler failed error=%lu",
                 GetLastError());
        return 0;
    }
    const uintptr_t registration_slot = base + kSubmitVtableRva;
    const uintptr_t submit_slot = registration_slot + 0x10;
    log_line(
        "[FUT-WATCH] handler installed; DR0 registration slot=0x%llx "
        "DR1 users/club slot=0x%llx targets={0x%llx,0x%llx}",
        (unsigned long long)registration_slot, (unsigned long long)submit_slot,
        (unsigned long long)registration_target,
        (unsigned long long)submit_target);
    if (apt_byte_watch) {
        log_line("[APT-BYTE] waiting for accountinfo parser to synchronize "
                 "futMain+0xA87F watch (two expected copies)");
    }

    DWORD known_ids[256] = {};
    size_t known_count = 0;
    size_t drained = 0;
    size_t total_armed = 0;
    size_t last_dropped = 0;
    size_t last_ignored = 0;
    uintptr_t apt_sites[kAptCopyCount] = {};
    int apt_site_count = 0;
    ULONGLONG next_apt_scan = 0;
    for (;;) {
        const uintptr_t requested_flux_load_movie =
            g_flux_load_movie_site.load(std::memory_order_acquire);
        const uintptr_t requested_flux_initialize =
            g_flux_initialize_site.load(std::memory_order_acquire);
        if (!apt_byte_watch && requested_flux_load_movie != 0 &&
            (apt_sites[0] != requested_flux_load_movie ||
             apt_sites[1] != requested_flux_initialize)) {
            apt_sites[0] = requested_flux_load_movie;
            apt_sites[1] = requested_flux_initialize;
            apt_site_count = requested_flux_initialize != 0 ? 2 : 1;
            g_apt_hit_mask.store(0, std::memory_order_release);
            g_flux_watch_ready.store(false, std::memory_order_release);
            known_count = 0;
            log_line("[FUT-FLUX-EXEC] adopting one-shot sites "
                     "loadMovie=0x%llx initializeScreen=0x%llx; rearming threads",
                     (unsigned long long)apt_sites[0],
                     (unsigned long long)apt_sites[1]);
        }
        const uintptr_t requested_futdb =
            g_futdb_request_site.load(std::memory_order_acquire);
        if (!apt_byte_watch && requested_flux_load_movie == 0 &&
            requested_futdb != 0 && apt_sites[1] != requested_futdb) {
            apt_sites[0] = 0;
            apt_sites[1] = requested_futdb;
            apt_site_count = 1;
            g_apt_hit_mask.store(0, std::memory_order_release);
            g_futdb_watch_ready.store(false, std::memory_order_release);
            known_count = 0;
            log_line("[FUT-DB] adopting one-shot execution site 0x%llx; "
                     "rearming threads", (unsigned long long)apt_sites[1]);
        }

        const size_t newly_armed = arm_new_threads(
            registration_slot, submit_slot, apt_sites[0], apt_sites[1],
            known_ids, &known_count);
        if (newly_armed != 0) {
            total_armed += newly_armed;
            log_line("[FUT-WATCH] armed %zu new thread(s), %zu total",
                     newly_armed, total_armed);
        }
        if (requested_flux_load_movie != 0 &&
            !g_flux_watch_ready.load(std::memory_order_acquire)) {
            const DWORD waiter =
                g_flux_waiter_thread.load(std::memory_order_acquire);
            bool waiter_conflict = false;
            const bool waiter_armed =
                waiter != 0 && arm_thread(
                    waiter, registration_slot, submit_slot,
                    apt_sites[0], apt_sites[1], &waiter_conflict);
            if (waiter_armed) {
                g_flux_watch_ready.store(true, std::memory_order_release);
                log_line("[FUT-FLUX-EXEC] router thread=%lu armed before "
                         "FLUX_COMPONENTS_DP continues", waiter);
            }
        }
        if (requested_futdb != 0 &&
            !g_futdb_watch_ready.load(std::memory_order_acquire)) {
            const DWORD waiter =
                g_futdb_waiter_thread.load(std::memory_order_acquire);
            bool waiter_conflict = false;
            const bool waiter_armed =
                waiter != 0 && arm_thread(
                    waiter, registration_slot, submit_slot,
                    apt_sites[0], apt_sites[1], &waiter_conflict);
            if (waiter_armed) {
                g_futdb_watch_ready.store(true, std::memory_order_release);
                log_line("[FUT-DB] thread=%lu armed on the request site", waiter);
            } else if (waiter_conflict) {
                log_line("[FUT-DB] thread=%lu already owns a debug register; "
                         "not armed", waiter);
            }
        }

        if (apt_site_count == kAptCopyCount &&
            g_apt_scan_requested.load(std::memory_order_acquire) &&
            !g_apt_watch_ready.load(std::memory_order_acquire)) {
            const DWORD waiter =
                g_apt_waiter_thread.load(std::memory_order_acquire);
            bool waiter_conflict = false;
            const bool waiter_armed =
                waiter != 0 && arm_thread(
                    waiter, registration_slot, submit_slot,
                    apt_sites[0], apt_sites[1], &waiter_conflict);
            log_line("[APT-BYTE] published-site profile arm thread=%lu armed=%u "
                     "conflict=%u", waiter, waiter_armed ? 1u : 0u,
                     waiter_conflict ? 1u : 0u);
            if (waiter_armed) {
                g_apt_watch_ready.store(true, std::memory_order_release);
            }
        }
        drain_events(base, &drained);
        const size_t dropped = g_dropped_events.load(std::memory_order_relaxed);
        if (dropped != last_dropped) {
            log_line("[FUT-WATCH] event buffer full; dropped=%zu", dropped);
            last_dropped = dropped;
        }
        const size_t ignored =
            g_ignored_external_hits.load(std::memory_order_relaxed);
        if (ignored >= last_ignored + 256) {
            log_line("[FUT-WATCH] ignored %zu external scanner/library hits",
                     ignored);
            last_ignored = ignored;
        }

        const ULONGLONG now = GetTickCount64();
        if (apt_byte_watch &&
            g_apt_scan_requested.load(std::memory_order_acquire) &&
            apt_site_count < kAptCopyCount &&
            now >= next_apt_scan) {
            uintptr_t found_sites[kAptCopyCount] = {};
            const ULONGLONG started = GetTickCount64();
            const int found = find_apt_opcode_sites(
                g_game_end + 0x40000000ULL, found_sites);
            log_line("[APT-BYTE] sweep found %d/2 opcode site(s) in %llu ms",
                     found, (unsigned long long)(GetTickCount64() - started));
            bool changed = found != apt_site_count;
            for (int i = 0; i < found && !changed; ++i) {
                changed = found_sites[i] != apt_sites[i];
            }
            if (changed) {
                apt_site_count = found;
                for (int i = 0; i < kAptCopyCount; ++i) {
                    apt_sites[i] = found_sites[i];
                }
                log_line("[APT-BYTE] sites={0x%llx,0x%llx} bytes={0x%x,0x%x}; "
                         "rearming all threads with DR2/DR3",
                         (unsigned long long)apt_sites[0],
                         (unsigned long long)apt_sites[1],
                         read_site_byte(apt_sites[0]),
                         read_site_byte(apt_sites[1]));
                known_count = 0;
                const DWORD waiter =
                    g_apt_waiter_thread.load(std::memory_order_acquire);
                bool waiter_conflict = false;
                const bool waiter_armed =
                    waiter != 0 && arm_thread(
                        waiter, registration_slot, submit_slot,
                        apt_sites[0], apt_sites[1], &waiter_conflict);
                const size_t updated = arm_new_threads(
                    registration_slot, submit_slot, apt_sites[0], apt_sites[1],
                    known_ids, &known_count);
                total_armed += updated;
                log_line("[APT-BYTE] synchronized contexts updated=%zu "
                         "profileThread=%lu armed=%u conflict=%u",
                         updated, waiter, waiter_armed ? 1u : 0u,
                         waiter_conflict ? 1u : 0u);
                if (found == kAptCopyCount && waiter_armed) {
                    g_apt_watch_ready.store(true, std::memory_order_release);
                }
            }
            next_apt_scan = GetTickCount64() + 1000;
        }
        Sleep(250);
    }
}

bool prepare_flux_opcode_watch(uintptr_t load_movie_opcode,
                               uintptr_t initialize_screen_opcode,
                               DWORD timeout_ms) {
    if (load_movie_opcode == 0 || initialize_screen_opcode == 0) return false;
    if (g_apt_watch_enabled.load(std::memory_order_acquire)) {
        log_line("[FUT-FLUX-EXEC] cannot use DR2/DR3 while apt_byte_watch=1");
        return false;
    }

    g_flux_watch_ready.store(false, std::memory_order_release);
    g_flux_waiter_thread.store(GetCurrentThreadId(), std::memory_order_release);
    g_flux_initialize_site.store(initialize_screen_opcode,
                                 std::memory_order_release);
    g_flux_load_movie_site.store(load_movie_opcode, std::memory_order_release);
    log_line("[FUT-FLUX-EXEC] requested one-shot reads loadMovie=0x%llx "
             "initializeScreen=0x%llx thread=%lu timeout=%lu",
             (unsigned long long)load_movie_opcode,
             (unsigned long long)initialize_screen_opcode,
             GetCurrentThreadId(), timeout_ms);

    const ULONGLONG started = GetTickCount64();
    while (timeout_ms != 0 &&
           !g_flux_watch_ready.load(std::memory_order_acquire) &&
           GetTickCount64() - started < timeout_ms) {
        Sleep(5);
    }
    const bool ready = g_flux_watch_ready.load(std::memory_order_acquire);
    log_line("[FUT-FLUX-EXEC] arm wait finished ready=%u elapsed=%llu ms",
             ready ? 1u : 0u,
             (unsigned long long)(GetTickCount64() - started));
    return ready;
}

bool prepare_futdb_request_watch(uintptr_t request_site, DWORD timeout_ms) {
    if (request_site == 0) return false;
    if (g_apt_watch_enabled.load(std::memory_order_acquire)) {
        log_line("[FUT-DB] cannot use DR3 while apt_byte_watch=1");
        return false;
    }
    if (g_flux_load_movie_site.load(std::memory_order_acquire) != 0) {
        log_line("[FUT-DB] cannot use DR3 while the FluxHub one-shot owns it");
        return false;
    }

    g_futdb_watch_ready.store(false, std::memory_order_release);
    g_futdb_waiter_thread.store(GetCurrentThreadId(), std::memory_order_release);
    g_futdb_request_site.store(request_site, std::memory_order_release);
    log_line("[FUT-DB] requested one-shot execution watch at 0x%llx thread=%lu "
             "timeout=%lu",
             (unsigned long long)request_site, GetCurrentThreadId(), timeout_ms);

    const ULONGLONG started = GetTickCount64();
    while (timeout_ms != 0 &&
           !g_futdb_watch_ready.load(std::memory_order_acquire) &&
           GetTickCount64() - started < timeout_ms) {
        Sleep(5);
    }
    const bool ready = g_futdb_watch_ready.load(std::memory_order_acquire);
    log_line("[FUT-DB] arm wait finished ready=%u elapsed=%llu ms",
             ready ? 1u : 0u,
             (unsigned long long)(GetTickCount64() - started));
    return ready;
}

bool prepare_apt_byte_watch_for_profile(DWORD timeout_ms) {
    if (!g_apt_watch_enabled.load(std::memory_order_acquire)) return false;

    const DWORD thread_id = GetCurrentThreadId();
    g_apt_waiter_thread.store(thread_id, std::memory_order_release);
    g_apt_scan_requested.store(true, std::memory_order_release);
    log_line("[APT-BYTE] profile boundary requested synchronized scan thread=%lu "
             "timeout=%lu", thread_id, timeout_ms);

    const ULONGLONG started = GetTickCount64();
    while (!g_apt_watch_ready.load(std::memory_order_acquire) &&
           GetTickCount64() - started < timeout_ms) {
        Sleep(10);
    }
    const bool ready = g_apt_watch_ready.load(std::memory_order_acquire);
    g_apt_scan_requested.store(false, std::memory_order_release);
    log_line("[APT-BYTE] profile boundary wait finished ready=%u elapsed=%llu ms",
             ready ? 1u : 0u,
             (unsigned long long)(GetTickCount64() - started));
    return ready;
}

}
