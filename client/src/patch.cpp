// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <intrin.h>
#include <psapi.h>

#pragma comment(lib, "psapi.lib")

extern "C" int32_t OriginCheckOnline(unsigned char* online);
extern "C" int32_t OriginDestroyHandle();
extern "C" uint64_t OriginGetDefaultUser();
extern "C" int32_t OriginGetGameInfoSync(int32_t type, char* value, size_t* length);
extern "C" int32_t OriginGetProfile(
    uint64_t user, uint32_t timeout_ms, void* callback, void* context);
extern "C" int32_t OriginGetProfileSync(
    uint64_t user, uint32_t timeout_ms, void* profile, void** handle);
using OriginEnumerationCallback = void(__cdecl *)(
    void* context, void* handle, uint32_t total, uint32_t available,
    int32_t error);
extern "C" int32_t OriginQueryBlockedUsers(
    uint64_t user, OriginEnumerationCallback callback, void* context);
extern "C" int32_t OriginQueryFriends(
    uint64_t user, OriginEnumerationCallback callback, void* context);
extern "C" int32_t OriginReadEnumerationSync(
    void* handle, void* buffer, size_t buffer_bytes, size_t start_index,
    size_t* items_read);
extern "C" int32_t OriginRegisterEventCallback();
extern "C" int32_t OriginRequestAuthCodeSync(
    uint64_t user, const char* client_id, const char** auth_code, size_t* length);
extern "C" int32_t OriginStartup();
extern "C" int32_t OriginUnregisterEventCallback();
extern "C" int32_t OriginUpdate();

namespace revival {

static bool dump_va_window(uintptr_t center_fn, uintptr_t pad_before,
                           uintptr_t pad_after, const wchar_t* filename,
                           const char* log_prefix, const char* tag);

static std::atomic<bool> g_recon_enabled{false};

void set_recon_enabled(bool enabled) {
    g_recon_enabled.store(enabled, std::memory_order_release);
}

bool recon_enabled() {
    return g_recon_enabled.load(std::memory_order_acquire);
}

namespace {

using CreateFileWFn = HANDLE(WINAPI *)(LPCWSTR, DWORD, DWORD,
                                       LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using CreateFileAFn = HANDLE(WINAPI *)(LPCSTR, DWORD, DWORD,
                                       LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using ReadFileFn = BOOL(WINAPI *)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);

CreateFileWFn g_original_create_file_w = nullptr;
CreateFileAFn g_original_create_file_a = nullptr;
ReadFileFn g_original_read_file = nullptr;
uintptr_t g_game_image_begin = 0;
uintptr_t g_game_image_end = 0;
thread_local bool g_file_trace_reentry = false;
std::atomic<unsigned long> g_file_trace_sequence{0};
std::atomic<uintptr_t> g_fut_save_handles[8] = {};
std::atomic<bool> g_fut_save_read_caller_dumped{false};
std::atomic<bool> g_fut_save_parent_dumped{false};

void remember_fut_save_handle(HANDLE handle, const char* path) {
    if (handle == nullptr || handle == INVALID_HANDLE_VALUE || path == nullptr ||
        strstr(path, "FutSquads") == nullptr || strstr(path, "_profile") != nullptr) {
        return;
    }
    uintptr_t value = reinterpret_cast<uintptr_t>(handle);
    for (auto& slot : g_fut_save_handles) {
        uintptr_t expected = 0;
        if (slot.compare_exchange_strong(expected, value) || expected == value) return;
    }
}

bool is_fut_save_handle(HANDLE handle) {
    uintptr_t value = reinterpret_cast<uintptr_t>(handle);
    if (value == 0 || handle == INVALID_HANDLE_VALUE) return false;
    for (auto& slot : g_fut_save_handles) {
        if (slot.load() == value) return true;
    }
    return false;
}

bool caller_is_in_game(void* caller) {
    const uintptr_t address = reinterpret_cast<uintptr_t>(caller);
    return address >= g_game_image_begin && address < g_game_image_end;
}

void sanitize_path(char* path) {
    for (size_t i = 0; path[i] != '\0'; ++i) {
        if (path[i] == '\r' || path[i] == '\n' || path[i] == '\t') path[i] = ' ';
    }
}

bool copy_ansi_path(LPCSTR source, char* destination, size_t capacity) {
    if (source == nullptr || capacity == 0) return false;
    __try {
        size_t i = 0;
        for (; i + 1 < capacity && source[i] != '\0'; ++i) destination[i] = source[i];
        destination[i] = '\0';
        sanitize_path(destination);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        destination[0] = '\0';
        return false;
    }
}

bool copy_wide_path(LPCWSTR source, char* destination, size_t capacity) {
    if (source == nullptr || capacity == 0) return false;
    __try {
        int written = WideCharToMultiByte(CP_UTF8, 0, source, -1, destination,
                                          static_cast<int>(capacity), nullptr, nullptr);
        if (written <= 0) {
            destination[0] = '\0';
            return false;
        }
        destination[capacity - 1] = '\0';
        sanitize_path(destination);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        destination[0] = '\0';
        return false;
    }
}

HANDLE WINAPI traced_create_file_w(LPCWSTR filename, DWORD desired_access,
                                    DWORD share_mode, LPSECURITY_ATTRIBUTES security,
                                    DWORD creation_disposition, DWORD flags,
                                    HANDLE template_file) {
    if (g_file_trace_reentry || g_original_create_file_w == nullptr) {
        return g_original_create_file_w(filename, desired_access, share_mode, security,
                                        creation_disposition, flags, template_file);
    }

    void* caller = _ReturnAddress();
    if (!caller_is_in_game(caller)) {
        return g_original_create_file_w(filename, desired_access, share_mode, security,
                                        creation_disposition, flags, template_file);
    }

    g_file_trace_reentry = true;
    HANDLE result = g_original_create_file_w(filename, desired_access, share_mode, security,
                                             creation_disposition, flags, template_file);
    char path[2048] = {0};
    copy_wide_path(filename, path, sizeof(path));
    remember_fut_save_handle(result, path);
    const unsigned long sequence = g_file_trace_sequence.fetch_add(1) + 1;
    log_line("[FUT-FILE] #%lu W callerRva=0x%llx access=0x%lx share=0x%lx "
             "disposition=%lu flags=0x%lx result=%p path=\"%s\"",
             sequence,
             static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(caller) -
                                             g_game_image_begin),
             desired_access, share_mode, creation_disposition, flags, result, path);
    g_file_trace_reentry = false;
    return result;
}

HANDLE WINAPI traced_create_file_a(LPCSTR filename, DWORD desired_access,
                                    DWORD share_mode, LPSECURITY_ATTRIBUTES security,
                                    DWORD creation_disposition, DWORD flags,
                                    HANDLE template_file) {
    if (g_file_trace_reentry || g_original_create_file_a == nullptr) {
        return g_original_create_file_a(filename, desired_access, share_mode, security,
                                        creation_disposition, flags, template_file);
    }

    void* caller = _ReturnAddress();
    if (!caller_is_in_game(caller)) {
        return g_original_create_file_a(filename, desired_access, share_mode, security,
                                        creation_disposition, flags, template_file);
    }

    g_file_trace_reentry = true;
    HANDLE result = g_original_create_file_a(filename, desired_access, share_mode, security,
                                             creation_disposition, flags, template_file);
    char path[2048] = {0};
    copy_ansi_path(filename, path, sizeof(path));
    remember_fut_save_handle(result, path);
    const unsigned long sequence = g_file_trace_sequence.fetch_add(1) + 1;
    log_line("[FUT-FILE] #%lu A callerRva=0x%llx access=0x%lx share=0x%lx "
             "disposition=%lu flags=0x%lx result=%p path=\"%s\"",
             sequence,
             static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(caller) -
                                             g_game_image_begin),
             desired_access, share_mode, creation_disposition, flags, result, path);
    g_file_trace_reentry = false;
    return result;
}

BOOL WINAPI traced_read_file(HANDLE file, LPVOID buffer, DWORD requested,
                             LPDWORD bytes_read, LPOVERLAPPED overlapped) {
    if (g_original_read_file == nullptr) return FALSE;
    if (!is_fut_save_handle(file) || g_file_trace_reentry) {
        return g_original_read_file(file, buffer, requested, bytes_read, overlapped);
    }

    g_file_trace_reentry = true;
    void* caller = _ReturnAddress();
    DWORD offset_low = 0;
    DWORD offset_high = 0;
    __try {
        if (overlapped != nullptr) {
            offset_low = overlapped->Offset;
            offset_high = overlapped->OffsetHigh;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        offset_low = offset_high = 0;
    }
    BOOL result = g_original_read_file(file, buffer, requested, bytes_read, overlapped);
    DWORD error = GetLastError();
    DWORD completed = 0;
    __try {
        if (bytes_read != nullptr) completed = *bytes_read;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        completed = 0;
    }
    bool game_caller = caller_is_in_game(caller);
    log_line(
        "[FUT-SAVE] ReadFile caller=0x%llx callerRva=0x%llx handle=%p "
        "requested=%lu completed=%lu overlapped=%p offset=0x%lx%08lx "
        "result=%u error=%lu",
        (unsigned long long)reinterpret_cast<uintptr_t>(caller),
        (unsigned long long)(game_caller
            ? reinterpret_cast<uintptr_t>(caller) - g_game_image_begin : 0),
        file, requested, completed, overlapped, offset_high, offset_low,
        result ? 1u : 0u, error);
    void* frames[12] = {0};
    USHORT frame_count = CaptureStackBackTrace(0, 12, frames, nullptr);
    uintptr_t parent = 0;
    for (USHORT i = 0; i < frame_count; ++i) {
        uintptr_t address = reinterpret_cast<uintptr_t>(frames[i]);
        uintptr_t rva = (address >= g_game_image_begin && address < g_game_image_end)
            ? address - g_game_image_begin : 0;
        log_line("[FUT-SAVE] stack[%u]=0x%llx rva=0x%llx", i,
                 (unsigned long long)address, (unsigned long long)rva);
        if (rva != 0 && address != reinterpret_cast<uintptr_t>(caller) && parent == 0) {
            parent = address;
        }
    }
    if (game_caller && !g_fut_save_read_caller_dumped.exchange(true)) {
        dump_va_window(reinterpret_cast<uintptr_t>(caller), 0x40000, 0x40000,
                       L"fifa17-revival-fut-save-read-caller.bin", "FUT-SAVE",
                       "read-caller");
    }
    if (parent != 0 && !g_fut_save_parent_dumped.exchange(true)) {
        dump_va_window(parent, 0x100000, 0x100000,
                       L"fifa17-revival-fut-save-parent.bin", "FUT-SAVE",
                       "parent");
    }
    g_file_trace_reentry = false;
    SetLastError(error);
    return result;
}

bool install_create_file_hook(const char* api_name, const unsigned char* expected,
                              size_t patch_length, void* hook, void** original) {
    if (expected == nullptr || patch_length < 14 || patch_length > 32) return false;
    HMODULE kernel_base = GetModuleHandleW(L"KernelBase.dll");
    if (kernel_base == nullptr) return false;
    auto* target = reinterpret_cast<unsigned char*>(GetProcAddress(kernel_base, api_name));
    if (target == nullptr) return false;
    if (memcmp(target, expected, patch_length) != 0) {
        char actual[32 * 3 + 1] = {0};
        for (size_t i = 0; i < patch_length; ++i) {
            std::snprintf(actual + i * 3, sizeof(actual) - i * 3, "%02x ", target[i]);
        }
        log_line("[FUT-FILE] %s prologue mismatch at %p: %s", api_name, target, actual);
        return false;
    }

    constexpr size_t kAbsoluteJumpLength = 14;
    auto* trampoline = reinterpret_cast<unsigned char*>(
        VirtualAlloc(nullptr, patch_length + kAbsoluteJumpLength,
                     MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, target, patch_length);
    trampoline[patch_length + 0] = 0xff;
    trampoline[patch_length + 1] = 0x25;
    memset(trampoline + patch_length + 2, 0, 4);
    *reinterpret_cast<uintptr_t*>(trampoline + patch_length + 6) =
        reinterpret_cast<uintptr_t>(target + patch_length);
    FlushInstructionCache(GetCurrentProcess(), trampoline,
                          patch_length + kAbsoluteJumpLength);
    *original = trampoline;

    unsigned char detour[32];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0xff;
    detour[1] = 0x25;
    memset(detour + 2, 0, 4);
    *reinterpret_cast<uintptr_t*>(detour + 6) = reinterpret_cast<uintptr_t>(hook);
    DWORD old_protect = 0;
    if (!VirtualProtect(target, patch_length, PAGE_EXECUTE_READWRITE, &old_protect)) {
        VirtualFree(trampoline, 0, MEM_RELEASE);
        *original = nullptr;
        return false;
    }
    memcpy(target, detour, patch_length);
    FlushInstructionCache(GetCurrentProcess(), target, patch_length);
    DWORD ignored = 0;
    VirtualProtect(target, patch_length, old_protect, &ignored);
    log_line("[FUT-FILE] %s hook target=%p trampoline=%p", api_name, target, trampoline);
    return true;
}

bool install_main_iat_hook(const char* api_name, void* hook, void** original) {
    auto* base = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    if (base == nullptr || api_name == nullptr || hook == nullptr ||
        original == nullptr) {
        return false;
    }

    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0) return false;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        return false;
    }

    const size_t image_size = nt->OptionalHeader.SizeOfImage;
    const auto& directory =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (directory.VirtualAddress == 0 || directory.Size < sizeof(IMAGE_IMPORT_DESCRIPTOR) ||
        directory.VirtualAddress >= image_size) {
        return false;
    }
    auto inside = [base, image_size](const void* pointer, size_t length) {
        const uintptr_t address = reinterpret_cast<uintptr_t>(pointer);
        const uintptr_t begin = reinterpret_cast<uintptr_t>(base);
        return address >= begin && length <= image_size &&
               address - begin <= image_size - length;
    };

    int patched = 0;
    auto* descriptor = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(
        base + directory.VirtualAddress);
    for (; inside(descriptor, sizeof(*descriptor)) && descriptor->Name != 0;
         ++descriptor) {
        if (descriptor->FirstThunk == 0 || descriptor->FirstThunk >= image_size) continue;
        const DWORD lookup_rva = descriptor->OriginalFirstThunk != 0
            ? descriptor->OriginalFirstThunk : descriptor->FirstThunk;
        if (lookup_rva >= image_size) continue;

        auto* lookup = reinterpret_cast<IMAGE_THUNK_DATA64*>(base + lookup_rva);
        auto* resolved = reinterpret_cast<IMAGE_THUNK_DATA64*>(
            base + descriptor->FirstThunk);
        for (; inside(lookup, sizeof(*lookup)) && inside(resolved, sizeof(*resolved)) &&
               lookup->u1.AddressOfData != 0;
             ++lookup, ++resolved) {
            if (IMAGE_SNAP_BY_ORDINAL64(lookup->u1.Ordinal) ||
                lookup->u1.AddressOfData >= image_size) {
                continue;
            }
            auto* named = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(
                base + lookup->u1.AddressOfData);
            if (!inside(named, sizeof(named->Hint) + 1)) continue;
            const char* name = reinterpret_cast<const char*>(named->Name);
            const size_t available = image_size -
                (reinterpret_cast<uintptr_t>(name) - reinterpret_cast<uintptr_t>(base));
            if (strnlen(name, available) == available || strcmp(name, api_name) != 0) {
                continue;
            }

            auto** slot = reinterpret_cast<void**>(&resolved->u1.Function);
            void* current = *slot;
            if (current == hook) {
                patched++;
                continue;
            }
            DWORD old_protect = 0;
            if (!VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old_protect)) {
                continue;
            }
            void* previous = InterlockedExchangePointer(
                reinterpret_cast<PVOID volatile*>(slot), hook);
            DWORD ignored = 0;
            VirtualProtect(slot, sizeof(*slot), old_protect, &ignored);
            if (*original == nullptr) *original = previous;
            patched++;
            log_line("[FUT-FILE] %s IAT hook slot=%p original=%p",
                     api_name, slot, previous);
        }
    }
    return patched != 0 && *original != nullptr;
}

std::vector<size_t> find_all(const unsigned char* haystack, size_t haystack_len,
                             const unsigned char* needle, size_t needle_len) {
    std::vector<size_t> hits;
    if (needle_len == 0 || needle_len > haystack_len) return hits;
    for (size_t i = 0; i + needle_len <= haystack_len; ++i) {
        if (memcmp(haystack + i, needle, needle_len) == 0) hits.push_back(i);
    }
    return hits;
}

}

using LoadLibraryExWFn = HMODULE(WINAPI *)(LPCWSTR, HANDLE, DWORD);
using LoadLibraryWFn = HMODULE(WINAPI *)(LPCWSTR);
LoadLibraryExWFn g_original_load_library_ex_w = nullptr;
LoadLibraryWFn g_original_load_library_w = nullptr;

bool module_name_is_interesting(const wchar_t* name) {
    if (name == nullptr) return false;
    return wcsstr(name, L"Cards") != nullptr || wcsstr(name, L"cards") != nullptr ||
           wcsstr(name, L"fut") != nullptr || wcsstr(name, L"FUT") != nullptr ||
           wcsstr(name, L"Fut") != nullptr;
}

HMODULE WINAPI traced_load_library_ex_w(LPCWSTR path, HANDLE file, DWORD flags) {
    HMODULE result = g_original_load_library_ex_w != nullptr
                         ? g_original_load_library_ex_w(path, file, flags)
                         : nullptr;
    if (module_name_is_interesting(path)) {
        log_line("[FUT-MODULE] LoadLibraryExW('%ls') flags=0x%lx -> 0x%llx%s",
                 path, flags, (unsigned long long)reinterpret_cast<uintptr_t>(result),
                 result == nullptr ? "  <== FAILED" : "");
        if (result == nullptr) {
            log_line("[FUT-MODULE] GetLastError=%lu", GetLastError());
        }
    }
    return result;
}

HMODULE WINAPI traced_load_library_w(LPCWSTR path) {
    HMODULE result = g_original_load_library_w != nullptr
                         ? g_original_load_library_w(path)
                         : nullptr;
    if (module_name_is_interesting(path)) {
        log_line("[FUT-MODULE] LoadLibraryW('%ls') -> 0x%llx%s",
                 path, (unsigned long long)reinterpret_cast<uintptr_t>(result),
                 result == nullptr ? "  <== FAILED" : "");
        if (result == nullptr) {
            log_line("[FUT-MODULE] GetLastError=%lu", GetLastError());
        }
    }
    return result;
}

int apply_module_load_trace() {
    int installed = 0;
    if (install_main_iat_hook("LoadLibraryExW",
                              reinterpret_cast<void*>(&traced_load_library_ex_w),
                              reinterpret_cast<void**>(&g_original_load_library_ex_w))) {
        installed++;
    }
    if (install_main_iat_hook("LoadLibraryW",
                              reinterpret_cast<void*>(&traced_load_library_w),
                              reinterpret_cast<void**>(&g_original_load_library_w))) {
        installed++;
    }
    return installed;
}

bool poll_loaded_modules() {
    static wchar_t seen[512][64];
    static size_t seen_count = 0;
    static bool announced_cards = false;
    static bool first_pass = true;

    HMODULE modules[1024];
    DWORD needed = 0;
    if (!EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed)) {
        return false;
    }
    const size_t count = needed / sizeof(HMODULE);
    bool cards = false;
    for (size_t i = 0; i < count && i < 1024; ++i) {
        wchar_t name[MAX_PATH];
        if (GetModuleBaseNameW(GetCurrentProcess(), modules[i], name, MAX_PATH) == 0) {
            continue;
        }
        if (_wcsicmp(name, L"CardsDLL_Win64_retail.dll") == 0) {
            cards = true;
            if (!announced_cards) {
                announced_cards = true;
                log_line("[FUT-MODULE] CardsDLL_Win64_retail.dll IS LOADED at 0x%llx",
                         (unsigned long long)reinterpret_cast<uintptr_t>(modules[i]));
            }
        }
        bool known = false;
        for (size_t s = 0; s < seen_count; ++s) {
            if (_wcsicmp(seen[s], name) == 0) { known = true; break; }
        }
        if (!known && seen_count < 512) {
            wcsncpy_s(seen[seen_count], name, _TRUNCATE);
            seen_count++;
            if (!first_pass) log_line("[FUT-MODULE] + %ls", name);
        }
    }
    if (first_pass) {
        first_pass = false;
        log_line("[FUT-MODULE] baseline: %zu module(s) loaded; reporting arrivals "
                 "from here. CardsDLL present at start: %s",
                 seen_count, cards ? "yes" : "no");
    }
    return cards;
}

int apply_game_file_io_trace() {
    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) {
        log_line("[FUT-FILE] could not query FIFA17.exe image bounds");
        return 0;
    }
    g_game_image_begin = reinterpret_cast<uintptr_t>(info.lpBaseOfDll);
    g_game_image_end = g_game_image_begin + info.SizeOfImage;

    const unsigned char expected_w[] = {
        0x48, 0x83, 0xec, 0x58,
        0x44, 0x8b, 0x94, 0x24, 0x88, 0x00, 0x00, 0x00,
        0x41, 0x8b, 0xc2,
    };
    const unsigned char expected_a[] = {
        0x48, 0x89, 0x5c, 0x24, 0x08,
        0x48, 0x89, 0x74, 0x24, 0x10,
        0x48, 0x89, 0x7c, 0x24, 0x18,
    };
    const unsigned char expected_read[] = {
        0x48, 0x89, 0x5c, 0x24, 0x10,
        0x4c, 0x89, 0x4c, 0x24, 0x20,
        0x56, 0x57, 0x41, 0x56,
        0x48, 0x83, 0xec, 0x60,
    };

    int installed = 0;
    if (install_main_iat_hook("CreateFileW",
                              reinterpret_cast<void*>(&traced_create_file_w),
                              reinterpret_cast<void**>(&g_original_create_file_w)) ||
        install_create_file_hook("CreateFileW", expected_w, sizeof(expected_w),
                                 reinterpret_cast<void*>(&traced_create_file_w),
                                 reinterpret_cast<void**>(&g_original_create_file_w))) {
        installed++;
    }
    if (install_main_iat_hook("CreateFileA",
                              reinterpret_cast<void*>(&traced_create_file_a),
                              reinterpret_cast<void**>(&g_original_create_file_a)) ||
        install_create_file_hook("CreateFileA", expected_a, sizeof(expected_a),
                                 reinterpret_cast<void*>(&traced_create_file_a),
                                 reinterpret_cast<void**>(&g_original_create_file_a))) {
        installed++;
    }
    if (install_main_iat_hook("ReadFile", reinterpret_cast<void*>(&traced_read_file),
                              reinterpret_cast<void**>(&g_original_read_file)) ||
        install_create_file_hook("ReadFile", expected_read, sizeof(expected_read),
                                 reinterpret_cast<void*>(&traced_read_file),
                                 reinterpret_cast<void**>(&g_original_read_file))) {
        installed++;
    }
    return installed;
}

HostPatchResult patch_hostnames_in_buffer(unsigned char* buffer, size_t size,
                                          const std::string& new_host) {
    HostPatchResult result;
    const unsigned char* host_bytes = reinterpret_cast<const unsigned char*>(new_host.data());
    const size_t host_len = new_host.size();

    for (const auto& target : hostname_targets()) {
        const auto hits = find_all(buffer, size,
                                   reinterpret_cast<const unsigned char*>(target.name),
                                   target.length);
        if (hits.empty()) {
            result.not_found++;
            continue;
        }
        if (host_len > target.length) {
            result.skipped_too_long++;
            continue;
        }
        for (size_t offset : hits) {
            memcpy(buffer + offset, host_bytes, host_len);
            memset(buffer + offset + host_len, 0, target.length - host_len);
            result.patched++;
        }
    }
    return result;
}

HostPatchResult patch_hostnames_in_main_module(const std::string& new_host) {
    HostPatchResult result;
    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) {
        log_line("[REDIR] could not query main module image; skipping hostname patch");
        return result;
    }

    auto* base = reinterpret_cast<unsigned char*>(info.lpBaseOfDll);
    const size_t size = info.SizeOfImage;

    const unsigned char* host_bytes = reinterpret_cast<const unsigned char*>(new_host.data());
    const size_t host_len = new_host.size();

    for (const auto& target : hostname_targets()) {
        const auto hits = find_all(base, size,
                                   reinterpret_cast<const unsigned char*>(target.name),
                                   target.length);
        if (hits.empty()) {
            result.not_found++;
            continue;
        }
        if (host_len > target.length) {
            result.skipped_too_long++;
            log_line("[REDIR] '%s' (%zu) is longer than target '%s' (%zu); not patched",
                     new_host.c_str(), host_len, target.name, target.length);
            continue;
        }
        for (size_t offset : hits) {
            unsigned char* dest = base + offset;
            DWORD old_protect = 0;
            if (VirtualProtect(dest, target.length, PAGE_EXECUTE_READWRITE, &old_protect)) {
                memcpy(dest, host_bytes, host_len);
                memset(dest + host_len, 0, target.length - host_len);
                VirtualProtect(dest, target.length, old_protect, &old_protect);
                result.patched++;
            } else {
                log_line("[REDIR] VirtualProtect failed at %p for '%s'", dest, target.name);
            }
        }
    }
    log_line("[REDIR] patched %d hostname(s); %d not found; %d skipped (too long)",
             result.patched, result.not_found, result.skipped_too_long);
    return result;
}

namespace {

HMODULE self_dll() {
    HMODULE module = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&self_dll), &module);
    return module;
}

const char* const kAnchors[] = {"ProtoSSLVerifyCert", "gosca", "ProtoSSL", "DirtySDK"};

bool region_ok(const void* addr, MEMORY_BASIC_INFORMATION& mbi) {
    if (VirtualQuery(addr, &mbi, sizeof(mbi)) == 0) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    return true;
}

bool region_executable(const MEMORY_BASIC_INFORMATION& mbi) {
    const DWORD exec = PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                       PAGE_EXECUTE_WRITECOPY;
    return (mbi.Protect & exec) != 0;
}

void dump_window(const unsigned char* p, size_t n, const char* label, uintptr_t va) {
    log_line("[SSL] --- %s @ 0x%llx (%zu bytes) ---", label, (unsigned long long)va, n);
    for (size_t off = 0; off < n; off += 16) {
        char hex[16 * 3 + 1] = {0};
        char asc[17] = {0};
        size_t row = (n - off < 16) ? (n - off) : 16;
        for (size_t i = 0; i < row; ++i) {
            unsigned char b = p[off + i];
            sprintf_s(hex + i * 3, 4, "%02x ", b);
            asc[i] = (b >= 0x20 && b < 0x7f) ? (char)b : '.';
        }
        log_line("[SSL]   +%04zx  %-48s %s", off, hex, asc);
    }
}

std::vector<std::pair<uintptr_t, size_t>> anchor_addresses(unsigned char* base, size_t size) {
    std::vector<std::pair<uintptr_t, size_t>> out;
    for (const char* anchor : kAnchors) {
        size_t len = strlen(anchor);
        for (size_t off : find_all(base, size, reinterpret_cast<const unsigned char*>(anchor), len)) {
            out.emplace_back(reinterpret_cast<uintptr_t>(base) + off, len);
        }
    }
    return out;
}

}

void recon_protossl_modules() {
    HANDLE process = GetCurrentProcess();
    HMODULE self = self_dll();
    HMODULE modules[1024];
    DWORD needed = 0;
    if (!EnumProcessModules(process, modules, sizeof(modules), &needed)) {
        log_line("[SSL] EnumProcessModules failed");
        return;
    }
    const int count = static_cast<int>(needed / sizeof(HMODULE));
    log_line("[SSL] %d modules loaded (our own DLL excluded from scans)", count);

    for (int i = 0; i < count; ++i) {
        if (modules[i] == self) continue;
        wchar_t name[MAX_PATH] = {0};
        if (!GetModuleFileNameExW(process, modules[i], name, MAX_PATH)) continue;
        MODULEINFO info = {0};
        if (!GetModuleInformation(process, modules[i], &info, sizeof(info))) continue;
        char narrow[MAX_PATH * 2] = {0};
        WideCharToMultiByte(CP_UTF8, 0, name, -1, narrow, sizeof(narrow), nullptr, nullptr);

        auto* base = reinterpret_cast<unsigned char*>(info.lpBaseOfDll);
        for (const char* anchor : kAnchors) {
            const auto hits =
                find_all(base, info.SizeOfImage, reinterpret_cast<const unsigned char*>(anchor),
                         strlen(anchor));
            if (!hits.empty()) {
                log_line("[SSL] anchor '%s' x%zu in %s (base %p, first +0x%zx)", anchor,
                         hits.size(), narrow, base, hits.front());
            }
        }
    }
}

void recon_protossl_strings() {
    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) return;
    auto* base = reinterpret_cast<unsigned char*>(info.lpBaseOfDll);

    for (const auto& [va, len] : anchor_addresses(base, info.SizeOfImage)) {
        const uintptr_t window = 1536;
        uintptr_t start = va > window ? va - window : reinterpret_cast<uintptr_t>(base);
        uintptr_t stop = va + window;
        log_line("[SSL] strings near anchor at 0x%llx:", (unsigned long long)va);
        std::string run;
        uintptr_t run_start = start;
        for (uintptr_t a = start; a < stop; ++a) {
            MEMORY_BASIC_INFORMATION mbi;
            if (!region_ok(reinterpret_cast<void*>(a), mbi)) break;
            unsigned char b = *reinterpret_cast<unsigned char*>(a);
            if (b >= 0x20 && b < 0x7f) {
                if (run.empty()) run_start = a;
                run.push_back((char)b);
            } else {
                if (run.size() >= 4) {
                    log_line("[SSL]   +0x%llx  \"%s\"",
                             (unsigned long long)(run_start - reinterpret_cast<uintptr_t>(base)),
                             run.c_str());
                }
                run.clear();
            }
        }
    }
}

int recon_protossl_xrefs() {
    static bool already_dumped = false;
    if (already_dumped) return -1;

    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) return 0;
    auto* base = reinterpret_cast<unsigned char*>(info.lpBaseOfDll);
    const uintptr_t image_start = reinterpret_cast<uintptr_t>(base);
    const uintptr_t image_end = image_start + info.SizeOfImage;

    const auto anchors = anchor_addresses(base, info.SizeOfImage);
    if (anchors.empty()) return 0;

    int dumped = 0;
    const int kMaxDumps = 16;

    uintptr_t addr = image_start;
    while (addr < image_end && dumped < kMaxDumps) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        uintptr_t region_end = region_start + mbi.RegionSize;

        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            region_executable(mbi)) {
            auto* p = reinterpret_cast<unsigned char*>(region_start);
            size_t span = mbi.RegionSize;
            for (size_t i = 0; i + 7 <= span && dumped < kMaxDumps; ++i) {
                if ((p[i] == 0x48 || p[i] == 0x4C) && p[i + 1] == 0x8D &&
                    (p[i + 2] & 0xC7) == 0x05) {
                    int32_t disp = *reinterpret_cast<int32_t*>(p + i + 3);
                    uintptr_t insn = region_start + i;
                    uintptr_t target = insn + 7 + disp;
                    for (const auto& [va, len] : anchors) {
                        if (target >= va && target < va + len) {
                            uintptr_t fn = insn;
                            uintptr_t floor = insn > 0x1000 ? insn - 0x1000 : region_start;
                            while (fn > floor) {
                                auto* q = reinterpret_cast<unsigned char*>(fn - 1);
                                if (q[0] == 0xCC && fn - 2 >= floor &&
                                    reinterpret_cast<unsigned char*>(fn - 2)[0] == 0xCC) {
                                    break;
                                }
                                fn--;
                            }
                            size_t dump_len = insn - fn + 96;
                            if (dump_len > 0x200) dump_len = 0x200;
                            char label[96];
                            sprintf_s(label, sizeof(label),
                                      "xref -> anchor 0x%llx (fn +0x%llx, lea +0x%llx)",
                                      (unsigned long long)va,
                                      (unsigned long long)(fn - image_start),
                                      (unsigned long long)(insn - image_start));
                            dump_window(reinterpret_cast<unsigned char*>(fn), dump_len, label, fn);
                            dumped++;
                            break;
                        }
                    }
                }
            }
        }
        addr = region_end;
    }

    if (dumped > 0) {
        already_dumped = true;
        log_line("[SSL] xref recon: dumped %d code window(s); patch to be derived offline", dumped);
    }
    return dumped;
}

namespace {

uintptr_t find_anchor_function(const char* anchor) {
    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) return 0;
    auto* base = reinterpret_cast<unsigned char*>(info.lpBaseOfDll);
    const size_t anchor_len = strlen(anchor);

    std::vector<uintptr_t> anchor_vas;
    for (size_t off : find_all(base, info.SizeOfImage,
                               reinterpret_cast<const unsigned char*>(anchor), anchor_len)) {
        anchor_vas.push_back(reinterpret_cast<uintptr_t>(base) + off);
    }
    if (anchor_vas.empty()) return 0;

    const uintptr_t image_start = reinterpret_cast<uintptr_t>(base);
    const uintptr_t image_end = image_start + info.SizeOfImage;
    uintptr_t addr = image_start;
    while (addr < image_end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        uintptr_t region_end = region_start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            region_executable(mbi)) {
            auto* p = reinterpret_cast<unsigned char*>(region_start);
            for (size_t i = 0; i + 7 <= mbi.RegionSize; ++i) {
                if ((p[i] == 0x48 || p[i] == 0x4C) && p[i + 1] == 0x8D &&
                    (p[i + 2] & 0xC7) == 0x05) {
                    int32_t disp = *reinterpret_cast<int32_t*>(p + i + 3);
                    uintptr_t insn = region_start + i;
                    uintptr_t target = insn + 7 + disp;
                    for (uintptr_t va : anchor_vas) {
                        if (target >= va && target < va + anchor_len) {
                            uintptr_t fn = insn;
                            uintptr_t floor = insn > 0x1000 ? insn - 0x1000 : region_start;
                            while (fn > floor) {
                                auto* q = reinterpret_cast<unsigned char*>(fn - 1);
                                if (q[0] == 0xCC && fn - 2 >= floor &&
                                    reinterpret_cast<unsigned char*>(fn - 2)[0] == 0xCC) {
                                    break;
                                }
                                fn--;
                            }
                            return fn;
                        }
                    }
                }
            }
        }
        addr = region_end;
    }
    return 0;
}

}

bool recon_protossl_dump_module() {
    static bool already = false;
    if (already) return false;

    uintptr_t cn_fn = find_anchor_function("gosca.ea.com");
    if (cn_fn == 0) return false;
    if (!recon_enabled()) {
        already = true;
        return true;
    }

    {
        HMODULE m = GetModuleHandleW(nullptr);
        MODULEINFO mi = {0};
        if (GetModuleInformation(GetCurrentProcess(), m, &mi, sizeof(mi))) {
            auto* b = reinterpret_cast<unsigned char*>(mi.lpBaseOfDll);
            uintptr_t bstart = reinterpret_cast<uintptr_t>(b);
            int refs = 0;
            uintptr_t a = bstart, aend = bstart + mi.SizeOfImage;
            while (a < aend && refs < 32) {
                MEMORY_BASIC_INFORMATION mbi;
                if (VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == 0) break;
                uintptr_t rend = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
                if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) {
                    auto* p = reinterpret_cast<unsigned char*>(a);
                    size_t n = rend - a;
                    for (size_t i = 0; i + 8 <= n && refs < 32; ++i) {
                        uintptr_t at = a + i;
                        if (p[i] == 0xE8) {
                            int32_t rel = *reinterpret_cast<int32_t*>(p + i + 1);
                            if (at + 5 + rel == cn_fn) {
                                log_line("[SSL] verify ref: call at +0x%llx",
                                         (unsigned long long)(at - bstart)); refs++;
                            }
                        }
                        if (*reinterpret_cast<uintptr_t*>(p + i) == cn_fn) {
                            log_line("[SSL] verify ref: pointer at +0x%llx",
                                     (unsigned long long)(at - bstart)); refs++;
                        }
                        if ((p[i] == 0x48 || p[i] == 0x4C) && (p[i + 1] == 0x8D || p[i + 1] == 0x8B) &&
                            (p[i + 2] & 0xC7) == 0x05) {
                            int32_t d = *reinterpret_cast<int32_t*>(p + i + 3);
                            if (at + 7 + d == cn_fn) {
                                log_line("[SSL] verify ref: lea/mov at +0x%llx",
                                         (unsigned long long)(at - bstart)); refs++;
                            }
                        }
                    }
                }
                a = rend;
            }
            if (refs == 0)
                log_line("[SSL] verify ref: none found (orchestrator reaches it another way)");
        }
    }

    const uintptr_t pad_before = 0x40000, pad_after = 0x20000;
    uintptr_t start = (cn_fn - pad_before) & ~static_cast<uintptr_t>(0xFFF);
    uintptr_t end = cn_fn + pad_after;
    size_t total = end - start;

    std::wstring path = module_directory() + L"\\fifa17-revival-protossl.bin";
    FILE* file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"wb") != 0 || file == nullptr) {
        log_line("[SSL] could not open dump file for writing");
        return false;
    }

    size_t written = 0, gaps = 0;
    uintptr_t addr = start;
    while (addr < end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        uintptr_t region_end = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        uintptr_t chunk_end = region_end < end ? region_end : end;
        size_t chunk = chunk_end - addr;
        bool readable = mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));
        if (readable) {
            fwrite(reinterpret_cast<void*>(addr), 1, chunk, file);
            written += chunk;
        } else {
            static const char zeros[4096] = {0};
            for (size_t left = chunk; left > 0;) {
                size_t n = left < sizeof(zeros) ? left : sizeof(zeros);
                fwrite(zeros, 1, n, file);
                left -= n;
            }
            gaps += chunk;
        }
        addr = chunk_end;
    }
    fclose(file);
    already = true;
    log_line("[SSL] module dump: 0x%llx .. 0x%llx (%zu bytes, %zu readable, %zu zero-filled)",
             (unsigned long long)start, (unsigned long long)end, total, written, gaps);
    log_line("[SSL] dump base VA for disassembly: 0x%llx -> fifa17-revival-protossl.bin",
             (unsigned long long)start);
    log_line("[SSL] CN-verify function at 0x%llx (file offset +0x%llx)",
             (unsigned long long)cn_fn, (unsigned long long)(cn_fn - start));
    return true;
}

static bool dump_va_window(uintptr_t center_fn, uintptr_t pad_before, uintptr_t pad_after,
                           const wchar_t* filename, const char* log_prefix, const char* tag) {
    if (!recon_enabled()) return true;
    uintptr_t start = (center_fn - pad_before) & ~static_cast<uintptr_t>(0xFFF);
    uintptr_t end = center_fn + pad_after;
    size_t total = end - start;

    std::wstring path = module_directory() + L"\\" + filename;
    FILE* file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"wb") != 0 || file == nullptr) {
        log_line("[%s] could not open dump file for writing", log_prefix);
        return false;
    }
    size_t written = 0, gaps = 0;
    uintptr_t addr = start;
    while (addr < end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        uintptr_t region_end = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        uintptr_t chunk_end = region_end < end ? region_end : end;
        size_t chunk = chunk_end - addr;
        bool readable = mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));
        if (readable) {
            fwrite(reinterpret_cast<void*>(addr), 1, chunk, file);
            written += chunk;
        } else {
            static const char zeros[4096] = {0};
            for (size_t left = chunk; left > 0;) {
                size_t n = left < sizeof(zeros) ? left : sizeof(zeros);
                fwrite(zeros, 1, n, file);
                left -= n;
            }
            gaps += chunk;
        }
        addr = chunk_end;
    }
    fclose(file);
    log_line("[%s] %s: 0x%llx .. 0x%llx (%zu bytes, %zu readable, %zu zero-filled)",
             log_prefix, tag, (unsigned long long)start, (unsigned long long)end,
             total, written, gaps);
    log_line("[%s] %s base VA 0x%llx; anchor fn at file offset +0x%llx",
             log_prefix, tag, (unsigned long long)start,
             (unsigned long long)(center_fn - start));
    return written > 0;
}

bool recon_fire2_dump() {
    static bool already = false;
    if (already) return false;

    struct Anchor { const char* text; const wchar_t* file; const char* tag; };
    const Anchor anchors[] = {
        {"Fire2Connection::mSessionKeys", L"fifa17-revival-fire2-conn.bin", "conn"},
        {"Blaze::Fire2Metadata", L"fifa17-revival-fire2-meta.bin", "meta"},
        {"Blaze::Fire2MetadataFlags", L"fifa17-revival-fire2-flags.bin", "flags"},
    };
    const uintptr_t pad = 0x80000;

    int dumped = 0;
    for (const Anchor& a : anchors) {
        uintptr_t fn = find_anchor_function(a.text);
        if (fn == 0) continue;
        log_line("[FIRE2] anchor '%s' fn=0x%llx", a.text, (unsigned long long)fn);
        if (dump_va_window(fn, pad, pad, a.file, "FIRE2", a.tag)) dumped++;
    }
    if (dumped == 0) return false;
    already = true;
    log_line("[FIRE2] dumped %d anchor window(s) for offline analysis", dumped);
    return true;
}

uintptr_t fut_club_url_builder_address();

std::atomic<uintptr_t> g_fut_club_url_builder_va{0};

uintptr_t fut_club_url_builder_address() {
    return g_fut_club_url_builder_va.load(std::memory_order_acquire);
}

std::atomic<bool> g_certificate_patch_done{false};

bool certificate_patch_done() {
    return g_certificate_patch_done.load(std::memory_order_acquire);
}

void set_certificate_patch_done() {
    g_certificate_patch_done.store(true, std::memory_order_release);
}

int recon_fut_event_publishers() {
    static uintptr_t seen[128] = {0};
    static size_t seen_count = 0;
    auto first_time = [](uintptr_t address) {
        for (size_t i = 0; i < seen_count; ++i) {
            if (seen[i] == address) return false;
        }
        if (seen_count < (sizeof(seen) / sizeof(seen[0]))) seen[seen_count++] = address;
        return true;
    };

    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) {
        return 0;
    }
    const uintptr_t base = reinterpret_cast<uintptr_t>(info.lpBaseOfDll);
    const uintptr_t image_end = base + info.SizeOfImage;

    static bool announced = false;
    if (!announced) {
        announced = true;
        log_line("[FUT-EVENTSRC] scanning immediates 0x275D..0x2761, "
                 "FUTLoginComplete=0x27A0, and login trigger=0x0BE7");
    }

    int found = 0;
    static int dumped = 0;
    uintptr_t addr = base;
    while (addr < image_end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        const uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        const uintptr_t region_end = region_start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            region_executable(mbi)) {
            __try {
                auto* p = reinterpret_cast<const unsigned char*>(region_start);
                for (size_t i = 0; i + 5 <= mbi.RegionSize; ++i) {
                    const bool is_mov = p[i] >= 0xB8 && p[i] <= 0xBF;
                    if (!is_mov && p[i] != 0x68) continue;
                    uint32_t value = 0;
                    memcpy(&value, p + i + 1, sizeof(value));
                    if (!((value >= 0x275D && value <= 0x2761) ||
                          value == 0x27A0 || value == 0x0BE7)) {
                        continue;
                    }
                    const uintptr_t site = region_start + i;
                    if (!first_time(site)) continue;
                    found++;
                    log_line("[FUT-EVENTSRC] id 0x%04x %s at 0x%llx (RVA 0x%llx)",
                             value, is_mov ? "mov" : "push",
                             (unsigned long long)site,
                             (unsigned long long)(site - base));
                    if (value == 0x27A0) {
                        static int login_complete_dumped = 0;
                        if (login_complete_dumped < 8) {
                            wchar_t file[80];
                            _snwprintf_s(
                                file, _TRUNCATE,
                                L"fifa17-revival-fut-login-complete-%d.bin",
                                login_complete_dumped);
                            if (dump_va_window(site, 0x10000, 0x10000, file,
                                               "FUT-EVENTSRC",
                                               "FUTLoginComplete")) {
                                login_complete_dumped++;
                            }
                        }
                    }
                    if (value == 0x0BE7) {
                        static int login_trigger_dumped = 0;
                        if (login_trigger_dumped < 8) {
                            wchar_t file[80];
                            _snwprintf_s(
                                file, _TRUNCATE,
                                L"fifa17-revival-fut-login-trigger-%d.bin",
                                login_trigger_dumped);
                            if (dump_va_window(site, 0x10000, 0x10000, file,
                                               "FUT-EVENTSRC",
                                               "login-trigger-0x0BE7")) {
                                login_trigger_dumped++;
                            }
                        }
                    }
                    if (dumped < 24) {
                        wchar_t file[64];
                        _snwprintf_s(file, _TRUNCATE,
                                     L"fifa17-revival-eventsrc-%d.bin", dumped);
                        if (dump_va_window(site, 0x10000, 0x10000, file,
                                           "FUT-EVENTSRC", "eventsrc")) {
                            dumped++;
                        }
                    }
                }
            } __except (EXCEPTION_EXECUTE_HANDLER) {
                log_line("[FUT-EVENTSRC] region 0x%llx changed under the scan; skipped",
                         (unsigned long long)region_start);
            }
        }
        addr = region_end;
    }

    if (found == 0) {
        static int quiet = 0;
        if (++quiet == 1 || quiet % 12 == 0) {
            log_line("[FUT-EVENTSRC] pass %d found no new immediate loads", quiet);
        }
    }
    return found;
}

enum UiRegistryFamily : unsigned char {
    kUiRegistryDataProvider = 0,
    kUiRegistryControl = 1,
    kUiRegistryCount = 2,
};

const char* ui_registry_family_name(unsigned char family) {
    return family == kUiRegistryDataProvider ? "dp" : "control";
}

struct UiRegistryEntry {
    uint32_t id;
    unsigned char family;
    char name[60];
};

constexpr size_t kUiRegistryCapacity = 8192;
UiRegistryEntry g_ui_registry[kUiRegistryCapacity];
size_t g_ui_registry_count = 0;
std::atomic<bool> g_ui_registry_ready{false};

bool ui_registry_read_name(const void* address, char* out, size_t capacity) {
    __try {
        const char* text = reinterpret_cast<const char*>(address);
        size_t i = 0;
        for (; i + 1 < capacity; ++i) {
            const char c = text[i];
            if (c == '\0') break;
            const bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                            (c >= '0' && c <= '9') || c == '_';
            if (!ok) return false;
            out[i] = c;
        }
        if (i < 3 || text[i] != '\0') return false;
        const char first = out[0];
        if (!((first >= 'A' && first <= 'Z') || (first >= 'a' && first <= 'z') ||
              first == '_')) {
            return false;
        }
        out[i] = '\0';
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

void ui_registry_add(uint32_t id, unsigned char family, const char* name) {
    for (size_t i = 0; i < g_ui_registry_count; ++i) {
        if (g_ui_registry[i].id == id && g_ui_registry[i].family == family) {
            if (strcmp(g_ui_registry[i].name, name) != 0) {
                strncpy_s(g_ui_registry[i].name, "<ambiguous>", _TRUNCATE);
            }
            return;
        }
    }
    if (g_ui_registry_count >= kUiRegistryCapacity) return;
    UiRegistryEntry& entry = g_ui_registry[g_ui_registry_count++];
    entry.id = id;
    entry.family = family;
    strncpy_s(entry.name, name, _TRUNCATE);
}

void ui_registry_scan_region(const unsigned char* start, size_t size) {
    if (size < 32) return;
    __try {
        const unsigned char kDpHead[] = {0x48, 0x8B, 0x03, 0x4C, 0x8D, 0x05};
        const unsigned char kDpTail[] = {0x48, 0x89, 0xD9, 0xFF, 0x50, 0x20};
        char name[60];
        for (size_t i = 32; i + 32 < size; ++i) {
            const unsigned char* p = start + i;

            if (p[0] == 0x48 && memcmp(p, kDpHead, sizeof(kDpHead)) == 0 &&
                p[10] == 0xBA && memcmp(p + 15, kDpTail, sizeof(kDpTail)) == 0) {
                int32_t disp = 0;
                uint32_t id = 0;
                memcpy(&disp, p + 6, sizeof(disp));
                memcpy(&id, p + 11, sizeof(id));
                const unsigned char* target = p + 10 + disp;
                if (ui_registry_read_name(target, name, sizeof(name))) {
                    ui_registry_add(id, kUiRegistryDataProvider, name);
                }
            }

            if (p[0] >= 0xB8 && p[0] <= 0xBF) {
                uint32_t id = 0;
                memcpy(&id, p + 1, sizeof(id));
                if (id < 0x0100 || id > 0xFFFF) continue;
                const size_t deltas[] = {27, 23};
                for (size_t d = 0; d < 2; ++d) {
                    if (i < deltas[d]) continue;
                    const unsigned char* field = p - deltas[d];
                    int32_t disp = 0;
                    memcpy(&disp, field, sizeof(disp));
                    const unsigned char* target = field + 4 + disp;
                    if (ui_registry_read_name(target, name, sizeof(name))) {
                        ui_registry_add(id, kUiRegistryControl, name);
                    }
                }
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

int build_ui_registry() {
    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) {
        return 0;
    }
    const uintptr_t base = reinterpret_cast<uintptr_t>(info.lpBaseOfDll);
    const uintptr_t image_end = base + info.SizeOfImage;
    const size_t before = g_ui_registry_count;
    const DWORD started = GetTickCount();

    uintptr_t addr = base;
    while (addr < image_end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        const uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        const uintptr_t region_end = region_start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            region_executable(mbi)) {
            ui_registry_scan_region(
                reinterpret_cast<const unsigned char*>(region_start), mbi.RegionSize);
        }
        addr = region_end;
    }

    const size_t added = g_ui_registry_count - before;
    if (added > 0) {
        size_t dp = 0, control = 0;
        for (size_t i = 0; i < g_ui_registry_count; ++i) {
            if (g_ui_registry[i].family == kUiRegistryDataProvider) dp++;
            else control++;
        }
        log_line("[UI-REGISTRY] pass added %zu entries (%zu total: %zu dp, %zu "
                 "control) in %lu ms",
                 added, g_ui_registry_count, dp, control, GetTickCount() - started);
        g_ui_registry_ready.store(true, std::memory_order_release);
    }
    return (int)added;
}

const char* ui_registry_describe(uint32_t id, char* out, size_t capacity) {
    if (out == nullptr || capacity == 0) return "";
    out[0] = '\0';
    size_t used = 0;
    for (unsigned char family = 0; family < kUiRegistryCount; ++family) {
        for (size_t i = 0; i < g_ui_registry_count; ++i) {
            if (g_ui_registry[i].id != id || g_ui_registry[i].family != family) {
                continue;
            }
            const int written = _snprintf_s(
                out + used, capacity - used, _TRUNCATE, "%s%s=%s",
                used ? " " : "", ui_registry_family_name(family),
                g_ui_registry[i].name);
            if (written > 0) used += (size_t)written;
            break;
        }
    }
    if (out[0] == '\0') {
        strncpy_s(out, capacity, g_ui_registry_ready.load(std::memory_order_acquire)
                                     ? "<unregistered>" : "<registry not built>",
                  _TRUNCATE);
    }
    return out;
}

void write_ui_registry_file() {
    if (!recon_enabled()) return;
    std::wstring path = module_directory() + L"\\fifa17-revival-ui-registry.txt";
    FILE* file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"w") != 0 || file == nullptr) {
        log_line("[UI-REGISTRY] could not write the registry file");
        return;
    }
    fprintf(file,
            "# FIFA 17 UI id -> name registries, resolved from decrypted memory.\n"
            "#\n"
            "# IDS ARE REGISTRY-LOCAL. The same number means different things in\n"
            "# different families; interpret an id in the registry belonging to\n"
            "# the dispatcher that carried it.\n"
            "#\n"
            "# family  id(hex)  id(dec)  name\n");
    for (unsigned char family = 0; family < kUiRegistryCount; ++family) {
        for (size_t i = 0; i < g_ui_registry_count; ++i) {
            const UiRegistryEntry& entry = g_ui_registry[i];
            if (entry.family != family) continue;
            fprintf(file, "%-8s 0x%04X   %6u   %s\n",
                    ui_registry_family_name(family), entry.id, entry.id, entry.name);
        }
    }
    fclose(file);
    log_line("[UI-REGISTRY] wrote %zu entries to fifa17-revival-ui-registry.txt",
             g_ui_registry_count);
}

constexpr unsigned char kFutSignatureKey = 0x5A;

struct FutByteMarker {
    const char* label;
    unsigned int stream_offset;
    unsigned char encoded[48];
};

const FutByteMarker kFutByteMarkers[] = {
    {"CardsLoginHelper.branch", 0xA7C4, {
        0xe3, 0x5e, 0xf8, 0x68, 0x13, 0x48, 0xc7, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a,
        0xda, 0x5a, 0x5a, 0x5a, 0xe3, 0x58, 0xf8, 0x69, 0x14, 0xf8, 0x6e, 0x14,
        0x00, 0xe3, 0x58, 0xf8, 0x6f, 0x14, 0xf8, 0x6c, 0x14, 0xf8, 0x6d, 0x07,
        0x03, 0xe3, 0x58, 0xf8, 0x69, 0x14, 0xf8, 0x62, 0x07, 0x03, 0xf8, 0x58,
    }},
    {"CardsLoginHelper.jump", 0xA854, {
        0x03, 0xe3, 0x5b, 0xf8, 0x18, 0x07, 0xc3, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a,
        0x46, 0x5a, 0x5a, 0x5a, 0xf8, 0x1e, 0xf8, 0x1f, 0x46, 0xf8, 0x1c, 0x14,
        0xf8, 0x1d, 0x14, 0xf8, 0x12, 0x14, 0xef, 0x58, 0xf8, 0x1f, 0x46, 0xf8,
        0x1c, 0x14, 0xf8, 0x13, 0x14, 0xf8, 0x10, 0x07, 0x15, 0xe3, 0x58, 0xf8,
    }},
    {"CardsLoginHelper.header", 0xA560, {
        0x22, 0x0c, 0x6e, 0x48, 0x5a, 0x5a, 0x5a, 0x5a, 0xf8, 0x52, 0x7c, 0xe3,
        0x58, 0xf8, 0x53, 0xe3, 0x5b, 0xf8, 0x50, 0x14, 0xe3, 0x5b, 0xef, 0x58,
        0xf8, 0x51, 0x46, 0xf8, 0x56, 0x14, 0xf8, 0x57, 0x14, 0xf8, 0x54, 0x08,
        0x15, 0xe3, 0x58, 0xf8, 0x55, 0xe3, 0x5b, 0xf8, 0x4a, 0x14, 0xe3, 0x5b,
    }},
};

std::atomic<bool> g_fut_residency_seen{false};
std::atomic<bool> g_fut_bytecode_seen{false};
std::atomic<bool> g_fut_table_dumped{false};
std::atomic<int> g_fut_self_matches{0};
std::atomic<bool> g_fut_residency_requested{false};
std::atomic<int> g_fut_mention_dumps{0};

bool fut_hit_is_self(uintptr_t address, uintptr_t self_begin, uintptr_t self_end,
                     uintptr_t stack_limit, uintptr_t stack_base) {
    const bool is_self =
        (self_end != 0 && address >= self_begin && address < self_end) ||
        (address >= stack_limit && address < stack_base);
    if (is_self) g_fut_self_matches.fetch_add(1, std::memory_order_relaxed);
    return is_self;
}

const char kAptHeaderPartA[] = "Apt Data";
const char kAptHeaderPartB[] = ":1:7:8";

const char kFutTokenPartA[] = "ion_";
const char kFutTokenPartB[] = "fut";

const char kFutPackagePrefixA[] = "external.ion";
const char kFutPackagePrefixB[] = "_fut.";

const char kPackagesPartA[] = "__Pack";
const char kPackagesPartB[] = "ages.";

void request_fut_residency_scan() {
    g_fut_residency_requested.store(true, std::memory_order_release);
}

bool consume_fut_residency_request() {
    return g_fut_residency_requested.exchange(false, std::memory_order_acq_rel);
}

constexpr size_t kAptRegionMemory = 32;
uintptr_t g_apt_regions[kAptRegionMemory];
size_t g_apt_region_count = 0;

constexpr size_t kSeenScreenMax = 384;
char g_seen_screens[kSeenScreenMax][72];
size_t g_seen_screen_count = 0;
CRITICAL_SECTION g_seen_screen_lock;
std::atomic<bool> g_seen_screen_ready{false};

void note_screen(const char* name) {
    if (name == nullptr || name[0] == '\0') return;
    if (!g_seen_screen_ready.load(std::memory_order_acquire)) return;
    EnterCriticalSection(&g_seen_screen_lock);
    bool known = false;
    for (size_t i = 0; i < g_seen_screen_count; ++i) {
        if (strcmp(g_seen_screens[i], name) == 0) { known = true; break; }
    }
    if (!known && g_seen_screen_count < kSeenScreenMax) {
        strncpy_s(g_seen_screens[g_seen_screen_count], name, _TRUNCATE);
        g_seen_screen_count++;
    }
    LeaveCriticalSection(&g_seen_screen_lock);
    if (!known) log_line("[FUT-APT-PACKAGE] + %s", name);
}

void init_screen_tracking() {
    InitializeCriticalSection(&g_seen_screen_lock);
    g_seen_screen_ready.store(true, std::memory_order_release);
}

void remember_apt_region(uintptr_t region) {
    for (size_t i = 0; i < g_apt_region_count; ++i) {
        if (g_apt_regions[i] == region) return;
    }
    if (g_apt_region_count < kAptRegionMemory) {
        g_apt_regions[g_apt_region_count++] = region;
    }
}

bool is_remembered_apt_region(uintptr_t region) {
    for (size_t i = 0; i < g_apt_region_count; ++i) {
        if (g_apt_regions[i] == region) return true;
    }
    return false;
}

struct AptScanCounts {
    int apt;
    int named;
    int fut;
    int mentions;
    int bytecode;
    int control;
    int control_apt;
    int control_fut;
};

void scan_region_for_apt(const unsigned char* base, size_t size,
                         uintptr_t region, DWORD type,
                         const char* apt_needle, size_t apt_length,
                         const char* fut_token, size_t fut_token_length,
                         const char* fut_prefix, size_t fut_prefix_length,
                         const char* packages_needle, size_t packages_length,
                         const char* control_needle, size_t control_length,
                         const unsigned char code_needles[][48], size_t code_count,
                         uintptr_t self_begin, uintptr_t self_end,
                         uintptr_t stack_limit, uintptr_t stack_base,
                         uintptr_t control_page, AptScanCounts* counts) {
    __try {
        if (size >= apt_length) {
            const unsigned char* p = base;
            size_t left = size - apt_length + 1;
            while (left > 0) {
                const unsigned char* found = (const unsigned char*)memchr(
                    p, (unsigned char)apt_needle[0], left);
                if (found == nullptr) break;
                const size_t remain = (size_t)((base + size) - found);
                if (remain >= apt_length &&
                    memcmp(found, apt_needle, apt_length) == 0 &&
                    !fut_hit_is_self(reinterpret_cast<uintptr_t>(found),
                                     self_begin, self_end, stack_limit, stack_base)) {
                    const size_t window = remain < 0x4000 ? remain : 0x4000;

                    char screen[72];
                    screen[0] = 0;
                    size_t packages_at = 0;
                    bool owns_fut_package = false;
                    char extra[2][72];
                    extra[0][0] = 0;
                    extra[1][0] = 0;
                    if (window > packages_length) {
                        const unsigned char* q = found;
                        size_t qleft = window - packages_length + 1;
                        int entry = 0;
                        while (qleft > 0 && entry < 8) {
                            const unsigned char* c = (const unsigned char*)memchr(
                                q, (unsigned char)packages_needle[0], qleft);
                            if (c == nullptr) break;
                            if (memcmp(c, packages_needle, packages_length) == 0) {
                                const unsigned char* name = c + packages_length;
                                const size_t cap = (size_t)((base + size) - name);
                                char text[72];
                                size_t n = 0;
                                while (n + 1 < sizeof(text) && n < cap) {
                                    const char ch = (char)name[n];
                                    if (ch >= 0x20 && ch < 0x7F) text[n++] = ch;
                                    else break;
                                }
                                text[n] = 0;
                                if (entry == 0) {
                                    packages_at = (size_t)(c - found);
                                    strcpy_s(screen, sizeof(screen), text);
                                    note_screen(text);
                                } else if (entry <= 2) {
                                    strcpy_s(extra[entry - 1], sizeof(extra[0]), text);
                                }
                                if (strncmp(text, fut_prefix, fut_prefix_length) == 0) {
                                    owns_fut_package = true;
                                }
                                entry++;
                            }
                            qleft -= (size_t)(c - q) + 1;
                            q = c + 1;
                        }
                    }
                    if (packages_at != 0) counts->named++;

                    size_t fut_at = 0;
                    if (window > fut_token_length) {
                        const unsigned char* q = found;
                        size_t qleft = window - fut_token_length + 1;
                        while (qleft > 0) {
                            const unsigned char* c = (const unsigned char*)memchr(
                                q, (unsigned char)fut_token[0], qleft);
                            if (c == nullptr) break;
                            if (memcmp(c, fut_token, fut_token_length) == 0) {
                                fut_at = (size_t)(c - found);
                                break;
                            }
                            qleft -= (size_t)(c - q) + 1;
                            q = c + 1;
                        }
                    }

                    int code_in_container = 0;
                    const size_t code_window = remain < 0x40000 ? remain : 0x40000;
                    for (size_t m = 0; m < code_count; ++m) {
                        if (code_window <= 48) continue;
                        const unsigned char* q = found;
                        size_t qleft = code_window - 48 + 1;
                        while (qleft > 0) {
                            const unsigned char* c = (const unsigned char*)memchr(
                                q, code_needles[m][0], qleft);
                            if (c == nullptr) break;
                            if (memcmp(c, code_needles[m], 48) == 0) {
                                code_in_container++;
                                counts->bytecode++;
                                break;
                            }
                            qleft -= (size_t)(c - q) + 1;
                            q = c + 1;
                        }
                    }

                    const uintptr_t here = reinterpret_cast<uintptr_t>(found);
                    const bool is_control_container =
                        control_page != 0 && here >= control_page &&
                        here < control_page + 0x1000;
                    if (!is_control_container) counts->apt++;
                    if (is_control_container) {
                        counts->control_apt++;
                        if (owns_fut_package) counts->control_fut++;
                        left -= (size_t)(found - p) + 1;
                        p = found + 1;
                        continue;
                    }

                    const bool mentions_fut = fut_at != 0 || code_in_container > 0;
                    if (mentions_fut) counts->mentions++;
                    if (owns_fut_package) counts->fut++;
                    if (counts->named <= 80 || mentions_fut) {
                        unsigned long long root = 0;
                        if (remain >= 0x18) memcpy(&root, found + 0x10, sizeof(root));
                        log_line("[FUT-RESIDENT] APT #%d at 0x%llx root=0x%llx "
                                 "region=0x%llx type=0x%x futAt=0x%zx bytecode=%d "
                                 "pkg0='%s' pkg1='%s' pkg2='%s'%s",
                                 counts->apt,
                                 (unsigned long long)reinterpret_cast<uintptr_t>(found),
                                 root, (unsigned long long)region, type,
                                 fut_at, code_in_container, screen, extra[0], extra[1],
                                 owns_fut_package ? "   <== IS A FUT PACKAGE"
                                                  : (mentions_fut ? "   (mentions FUT)" : ""));
                    }
                    if (mentions_fut && !owns_fut_package &&
                        g_fut_mention_dumps.load() < 3) {
                        const int index = g_fut_mention_dumps.fetch_add(1);
                        if (index < 3) {
                            wchar_t file[72];
                            _snwprintf_s(file, _TRUNCATE,
                                         L"fifa17-revival-fut-mention-%d.bin", index);
                            dump_va_window(reinterpret_cast<uintptr_t>(found), 0,
                                           0x20000, file, "FUT-RESIDENT",
                                           "fut-mention");
                        }
                    }
                    remember_apt_region(region);
                }
                left -= (size_t)(found - p) + 1;
                p = found + 1;
            }
        }

        if (control_length > 0 && size >= control_length) {
            const unsigned char* p = base;
            size_t left = size - control_length + 1;
            while (left > 0) {
                const unsigned char* found = (const unsigned char*)memchr(
                    p, (unsigned char)control_needle[0], left);
                if (found == nullptr) break;
                if (memcmp(found, control_needle, control_length) == 0 &&
                    !fut_hit_is_self(reinterpret_cast<uintptr_t>(found),
                                     self_begin, self_end, stack_limit, stack_base)) {
                    counts->control++;
                }
                left -= (size_t)(found - p) + 1;
                p = found + 1;
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

constexpr uintptr_t kFutDbRequestSiteRva = 0x7D9DA42;
constexpr unsigned char kFutDbRequestOpcode[3] = {0xFF, 0x50, 0x78};
constexpr uint32_t kFutGateProfilerAction = 10098;
std::atomic<bool> g_futdb_watch_enabled{false};
std::atomic<bool> g_futdb_watch_requested{false};

void set_futdb_watch_enabled(bool enabled) {
    g_futdb_watch_enabled.store(enabled, std::memory_order_release);
}

void request_futdb_watch_from_gate() {
    if (!g_futdb_watch_enabled.load(std::memory_order_acquire)) return;
    if (g_futdb_watch_requested.exchange(true)) return;

    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (base == 0) return;
    const uintptr_t site = base + kFutDbRequestSiteRva;

    unsigned char bytes[3] = {0, 0, 0};
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(reinterpret_cast<void*>(site), mbi) || !region_executable(mbi)) {
        log_line("[FUT-DB] request site 0x%llx is not executable yet; not armed",
                 (unsigned long long)site);
        return;
    }
    __try {
        memcpy(bytes, reinterpret_cast<const void*>(site), sizeof(bytes));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        log_line("[FUT-DB] request site 0x%llx unreadable; not armed",
                 (unsigned long long)site);
        return;
    }
    if (memcmp(bytes, kFutDbRequestOpcode, sizeof(bytes)) != 0) {
        log_line("[FUT-DB] request site 0x%llx holds %02x %02x %02x, not "
                 "call [rax+0x78]; refusing to arm",
                 (unsigned long long)site, bytes[0], bytes[1], bytes[2]);
        return;
    }
    log_line("[FUT-DB] request site validated at 0x%llx (RVA 0x%llx); arming",
             (unsigned long long)site, (unsigned long long)kFutDbRequestSiteRva);
    prepare_futdb_request_watch(site, 1000);
}

int probe_fut_frontend_residency(bool after_fut) {
    return probe_fut_frontend_residency_ex(after_fut, false);
}

int probe_fut_frontend_residency_ex(bool after_fut, bool priority_only) {
    HMODULE self = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCWSTR>(&probe_fut_frontend_residency),
                       &self);
    MODULEINFO self_info = {0};
    uintptr_t self_begin = 0, self_end = 0;
    if (self != nullptr &&
        GetModuleInformation(GetCurrentProcess(), self, &self_info, sizeof(self_info))) {
        self_begin = reinterpret_cast<uintptr_t>(self_info.lpBaseOfDll);
        self_end = self_begin + self_info.SizeOfImage;
    }

    static void* control_page = nullptr;
    static char control_needle[96];
    if (control_page == nullptr) {
        control_page = VirtualAlloc(nullptr, 0x1000, MEM_COMMIT | MEM_RESERVE,
                                    PAGE_READWRITE);
        strcpy_s(control_needle, "external.probe_ctl.classes.");
        strcat_s(control_needle, "ProbeSelfTest");
        if (control_page != nullptr) {
            char* page = static_cast<char*>(control_page);
            memset(page, 0, 0x1000);
            memcpy(page + 0x400, control_needle, strlen(control_needle) + 1);

            char header[32];
            strcpy_s(header, kAptHeaderPartA);
            strcat_s(header, kAptHeaderPartB);
            memcpy(page, header, strlen(header));
            page[strlen(header)] = 0x1A;

            char entry[96];
            strcpy_s(entry, kPackagesPartA);
            strcat_s(entry, kPackagesPartB);
            strcat_s(entry, kFutPackagePrefixA);
            strcat_s(entry, kFutPackagePrefixB);
            strcat_s(entry, "classes.ProbeSelfTest");
            memcpy(page + 0x20, entry, strlen(entry) + 1);
        }
    }
    const size_t control_length = strlen(control_needle);

    char apt_needle[32];
    strcpy_s(apt_needle, kAptHeaderPartA);
    strcat_s(apt_needle, kAptHeaderPartB);
    const size_t apt_length = strlen(apt_needle);

    char fut_token[16];
    strcpy_s(fut_token, kFutTokenPartA);
    strcat_s(fut_token, kFutTokenPartB);
    const size_t fut_token_length = strlen(fut_token);

    char fut_prefix[32];
    strcpy_s(fut_prefix, kFutPackagePrefixA);
    strcat_s(fut_prefix, kFutPackagePrefixB);
    const size_t fut_prefix_length = strlen(fut_prefix);

    char packages_needle[32];
    strcpy_s(packages_needle, kPackagesPartA);
    strcat_s(packages_needle, kPackagesPartB);
    const size_t packages_length = strlen(packages_needle);

    unsigned char code_needles[ARRAYSIZE(kFutByteMarkers)][48];
    for (size_t i = 0; i < ARRAYSIZE(kFutByteMarkers); ++i) {
        for (size_t b = 0; b < 48; ++b) {
            code_needles[i][b] = kFutByteMarkers[i].encoded[b] ^ kFutSignatureKey;
        }
    }

    const uintptr_t stack_base = (uintptr_t)__readgsqword(0x08);
    const uintptr_t stack_limit = (uintptr_t)__readgsqword(0x10);
    const uintptr_t needle_probe = reinterpret_cast<uintptr_t>(&code_needles[0][0]);

    AptScanCounts counts = {0, 0, 0, 0, 0, 0, 0, 0};
    const DWORD started = GetTickCount();
    unsigned long long scanned = 0;
    SYSTEM_INFO si = {0};
    GetSystemInfo(&si);
    const uintptr_t low = reinterpret_cast<uintptr_t>(si.lpMinimumApplicationAddress);
    const uintptr_t limit = reinterpret_cast<uintptr_t>(si.lpMaximumApplicationAddress);

    const bool have_priority = g_apt_region_count > 0;
    const int last_phase = (priority_only && have_priority) ? 1 : 2;
    for (int phase = have_priority ? 0 : 1; phase < last_phase; ++phase) {
        uintptr_t addr = low;
        while (addr < limit) {
            MEMORY_BASIC_INFORMATION mbi;
            if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
            const uintptr_t region = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
            const size_t size = mbi.RegionSize;
            const uintptr_t next = region + size;

            const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                                   PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                                   PAGE_EXECUTE_WRITECOPY;
            const bool is_self_image = region < self_end && next > self_begin;
            const bool is_own_stack = region < stack_base && next > stack_limit;
            const bool holds_needles = region <= needle_probe && next > needle_probe;
            const bool priority = is_remembered_apt_region(region);
            const bool wanted = (phase == 0) ? priority : !priority;

            if (mbi.State == MEM_COMMIT && (mbi.Protect & readable) != 0 &&
                !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
                !is_self_image && !is_own_stack && !holds_needles && wanted) {
                scan_region_for_apt(
                    reinterpret_cast<const unsigned char*>(region), size, region,
                    mbi.Type, apt_needle, apt_length, fut_token, fut_token_length,
                    fut_prefix, fut_prefix_length,
                    packages_needle, packages_length, control_needle, control_length,
                    code_needles, ARRAYSIZE(kFutByteMarkers),
                    self_begin, self_end, stack_limit, stack_base,
                    reinterpret_cast<uintptr_t>(control_page), &counts);
                scanned += size;
            }
            addr = next;
        }
        if (phase == 0) {
            log_line("[FUT-RESIDENT] priority phase done in %lu ms: %d container(s) "
                     "across %zu known APT-bearing region(s), %d of them ARE a FUT "
                     "package. Full sweep follows.",
                     GetTickCount() - started, counts.apt, g_apt_region_count,
                     counts.fut);
        }
    }

    const DWORD elapsed = GetTickCount() - started;
    if (priority_only) return counts.fut;

    if (counts.control == 0) {
        log_line("[FUT-RESIDENT] CONTROL FAILED: the planted marker was not found. "
                 "The scan is not working -- ignore this pass, negatives especially.");
        return -1;
    }
    if (counts.apt == 0) {
        log_line("[FUT-RESIDENT] META-CONTROL FAILED: no APT container anywhere in "
                 "%llu MB, though the planted control was found. APT streams are "
                 "not held verbatim, so every byte-signature result is void.",
                 scanned / (1024 * 1024));
        return -1;
    }
    if (counts.named == 0) {
        log_line("[FUT-RESIDENT] IDENTIFICATION CONTROL FAILED: none of the %d "
                 "resident containers carries a package list within 0x4000 of its "
                 "header, though every extracted stream does. Resident containers "
                 "are not laid out like the extracted ones, so a FUT negative means "
                 "nothing. Do not conclude from this pass.",
                 counts.apt);
        return -1;
    }

    if (counts.control_fut == 0) {
        log_line("[FUT-RESIDENT] isFut CONTROL FAILED: the planted container "
                 "(apt=%d found in the control page) was not recognised as a FUT "
                 "package, so the isFut test does not work and a zero count means "
                 "nothing. Do not conclude from this pass.", counts.control_apt);
        return -1;
    }

    log_line("[FUT-RESIDENT] controls OK (planted FUT container recognised): "
             "%d container(s), %d named, %d ARE a FUT package, %d merely mention one",
             counts.apt, counts.named, counts.fut, counts.mentions);

    if (!after_fut) {
        log_line("[FUT-RESIDENT] baseline reference only -- FUT has not been "
                 "entered yet, so a FUT package being absent means nothing. "
                 "Recorded %d container(s) for comparison.", counts.apt);
    } else if (counts.fut > 0) {
        log_line("[FUT-RESIDENT] VERDICT: a FUT package IS loaded -- %d container(s) "
                 "declare an external FUT package as one of their own leading "
                 "entries. The frontend exists in this process, so the login script "
                 "is stalled rather than missing.", counts.fut);
    } else {
        log_line("[FUT-RESIDENT] VERDICT: NO FUT package is loaded. %d containers "
                 "are resident and %d were named by the same search, so the method "
                 "demonstrably reads package lists -- this negative is measured. "
                 "%d container(s) merely MENTION a FUT name (a class registry does "
                 "that without the package being loaded); dumps of those are beside "
                 "the exe. The spinner is a frontend that never loads.",
                 counts.apt, counts.named, counts.mentions);
    }

    if (counts.bytecode > 0) g_fut_bytecode_seen.store(true);
    if (counts.fut > 0) g_fut_residency_seen.store(true);
    static int pass = 0;
    ++pass;
    log_line("[FUT-RESIDENT] pass %d (%s): apt=%d named=%d isFut=%d mentionsFut=%d "
             "bytecode=%d control=%d selfDiscarded=%d, scanned %llu MB in %lu ms",
             pass, after_fut ? "post-FUT" : "baseline", counts.apt, counts.named,
             counts.fut, counts.mentions, counts.bytecode, counts.control,
             g_fut_self_matches.load(), scanned / (1024 * 1024), elapsed);
    return counts.fut;
}

int recon_users_club_callers() {
    static uintptr_t seen[64] = {0};
    static size_t seen_count = 0;
    auto first_time = [](uintptr_t address) {
        for (size_t i = 0; i < seen_count; ++i) {
            if (seen[i] == address) return false;
        }
        if (seen_count < (sizeof(seen) / sizeof(seen[0]))) seen[seen_count++] = address;
        return true;
    };

    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) {
        return 0;
    }
    const uintptr_t base = reinterpret_cast<uintptr_t>(info.lpBaseOfDll);
    const uintptr_t image_end = base + info.SizeOfImage;

    const uintptr_t target = fut_club_url_builder_address();
    if (target == 0) {
        static bool waiting_logged = false;
        if (!waiting_logged) {
            waiting_logged = true;
            log_line("[FUT-CALLERS] waiting for the users/club builder to be located");
        }
        return 0;
    }

    static bool scanning_logged = false;
    if (!scanning_logged) {
        scanning_logged = true;
        log_line("[FUT-CALLERS] scanning the image for references to 0x%llx "
                 "(RVA 0x%llx)",
                 (unsigned long long)target, (unsigned long long)(target - base));
    }

    int calls = 0;
    int pointers = 0;
    int dumped = 0;
    uintptr_t addr = base;
    while (addr < image_end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        const uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        const uintptr_t region_end = region_start + mbi.RegionSize;
        const bool readable =
            mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));
        if (readable) {
            auto* p = reinterpret_cast<const unsigned char*>(region_start);
            const size_t size = mbi.RegionSize;

            if (region_executable(mbi)) {
                for (size_t i = 0; i + 5 <= size; ++i) {
                    if (p[i] != 0xE8 && p[i] != 0xE9) continue;
                    int32_t rel = 0;
                    memcpy(&rel, p + i + 1, sizeof(rel));
                    const uintptr_t site = region_start + i;
                    if (site + 5 + rel != target) continue;
                    if (!first_time(site)) continue;
                    calls++;
                    log_line("[FUT-CALLERS] %s site at 0x%llx (RVA 0x%llx)",
                             p[i] == 0xE8 ? "call" : "jmp",
                             (unsigned long long)site,
                             (unsigned long long)(site - base));
                    if (dumped < 4) {
                        wchar_t file[64];
                        _snwprintf_s(file, _TRUNCATE,
                                     L"fifa17-revival-club-caller-%d.bin", dumped);
                        if (dump_va_window(site, 0x20000, 0x20000, file,
                                           "FUT-CALLERS", "club-caller")) {
                            dumped++;
                        }
                    }
                }
            }

            for (size_t i = 0; i + sizeof(uintptr_t) <= size; i += sizeof(uintptr_t)) {
                uintptr_t value = 0;
                memcpy(&value, p + i, sizeof(value));
                if (value != target) continue;
                if (!first_time(region_start + i)) continue;
                pointers++;
                const uintptr_t slot = region_start + i;
                log_line("[FUT-CALLERS] pointer at 0x%llx (RVA 0x%llx)",
                         (unsigned long long)slot,
                         (unsigned long long)(slot - base));

                for (int n = -6; n <= 6; ++n) {
                    auto* neighbour = reinterpret_cast<const uintptr_t*>(slot) + n;
                    MEMORY_BASIC_INFORMATION nb;
                    if (!region_ok(const_cast<uintptr_t*>(neighbour), nb)) continue;
                    const uintptr_t entry = *neighbour;
                    const bool in_image = entry >= base && entry < image_end;
                    log_line("[FUT-CALLERS]   [%+d] +0x%02x = 0x%llx%s%s",
                             n, (unsigned)(n * sizeof(uintptr_t)) & 0xFF,
                             (unsigned long long)entry,
                             in_image ? "  (in image, RVA 0x" : "",
                             in_image ? "" : "");
                    if (in_image) {
                        log_line("[FUT-CALLERS]        RVA 0x%llx%s",
                                 (unsigned long long)(entry - base),
                                 entry == target ? "   <== the builder" : "");
                    }
                }
                if (dumped < 4) {
                    wchar_t file[64];
                    _snwprintf_s(file, _TRUNCATE,
                                 L"fifa17-revival-club-vtable-%d.bin", dumped);
                    if (dump_va_window(slot, 0x8000, 0x8000, file, "FUT-CALLERS",
                                       "club-vtable")) {
                        dumped++;
                    }
                }
            }
        }
        addr = region_end;
    }

    if (calls == 0 && pointers == 0) {
        static int quiet_passes = 0;
        if (++quiet_passes == 1 || quiet_passes % 12 == 0) {
            log_line("[FUT-CALLERS] pass %d found no new reference to the builder",
                     quiet_passes);
        }
        return 0;
    }    log_line("[FUT-CALLERS] builder 0x%llx (RVA 0x%llx): %d direct site(s), "
             "%d pointer(s), %d window(s) dumped",
             (unsigned long long)target, (unsigned long long)(target - base),
             calls, pointers, dumped);
    return calls + pointers;
}

namespace {

bool parse_hex_bytes(const std::string& text, std::vector<unsigned char>& out) {
    out.clear();
    if (text.empty() || text.size() % 2 != 0) return false;
    for (size_t i = 0; i < text.size(); i += 2) {
        int value = 0;
        for (int nibble = 0; nibble < 2; ++nibble) {
            const char c = text[i + nibble];
            int digit;
            if (c >= '0' && c <= '9') digit = c - '0';
            else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
            else return false;
            value = (value << 4) | digit;
        }
        out.push_back(static_cast<unsigned char>(value));
    }
    return !out.empty();
}

unsigned char* scan_region_for_bytes(unsigned char* start, size_t size,
                                     const unsigned char* needle, size_t needle_length,
                                     int* matches) {
    unsigned char* first = nullptr;
    __try {
        size_t offset = 0;
        while (offset + needle_length <= size) {
            const size_t searchable = size - offset - (needle_length - 1);
            auto* candidate = reinterpret_cast<unsigned char*>(
                memchr(start + offset, needle[0], searchable));
            if (candidate == nullptr) break;
            const size_t i = static_cast<size_t>(candidate - start);
            offset = i + 1;
            if (memcmp(candidate, needle, needle_length) != 0) continue;
            (*matches)++;
            if (first == nullptr) first = candidate;
            if (*matches > 1) break;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
    return first;
}

int scan_region_collect(unsigned char* start, size_t size,
                        const unsigned char* needle, size_t needle_length,
                        unsigned char** sites, int capacity, int found) {
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
            sites[found++] = candidate;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
    return found;
}

bool parse_apt_patch_spec(const std::string& spec, size_t& offset,
                          std::vector<unsigned char>& before,
                          std::vector<unsigned char>& after) {
    const size_t first = spec.find(':');
    if (first == std::string::npos) return false;
    const size_t second = spec.find(':', first + 1);
    if (second == std::string::npos) return false;

    const std::string offset_text = spec.substr(0, first);
    if (offset_text.empty()) return false;
    char* end = nullptr;
    const unsigned long long parsed =
        strtoull(offset_text.c_str(), &end, offset_text.compare(0, 2, "0x") == 0 ? 16 : 16);
    if (end == nullptr || *end != '\0') return false;
    offset = static_cast<size_t>(parsed);

    if (!parse_hex_bytes(spec.substr(first + 1, second - first - 1), before)) return false;
    if (!parse_hex_bytes(spec.substr(second + 1), after)) return false;
    return before.size() == after.size();
}

}

bool apply_apt_force_patch(const Config& config) {
    static bool applied = false;
    if (applied || config.apt_patch.empty()) return applied;

    size_t offset = 0;
    std::vector<unsigned char> before;
    std::vector<unsigned char> after;
    if (!parse_apt_patch_spec(config.apt_patch, offset, before, after)) {
        static bool complained = false;
        if (!complained) {
            complained = true;
            log_line("[APT-FORCE] cannot parse apt_patch '%s'; expected "
                     "<offsetHex>:<beforeHex>:<afterHex> with equal-length byte "
                     "strings", config.apt_patch.c_str());
        }
        applied = true;
        return false;
    }

    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), main_module, &info, sizeof(info))) {
        return false;
    }
    const uintptr_t image_end =
        reinterpret_cast<uintptr_t>(info.lpBaseOfDll) + info.SizeOfImage;

    const ULONGLONG scan_started = GetTickCount64();
    constexpr int kExpectedSites = 2;
    unsigned char* sites[kExpectedSites] = {nullptr};
    int matches = 0;
    uintptr_t address = 0;
    while (address < image_end + 0x40000000ull && matches < kExpectedSites) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(address), &mbi, sizeof(mbi)) == 0) break;
        const uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        const uintptr_t region_end = region_start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE &&
            !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            mbi.RegionSize >= before.size()) {
            matches = scan_region_collect(
                reinterpret_cast<unsigned char*>(region_start), mbi.RegionSize,
                before.data(), before.size(), sites, kExpectedSites, matches);
        }
        if (matches >= kExpectedSites) break;
        address = region_end;
    }

    {
        static int reported = 0;
        if (reported < 3) {
            reported++;
            log_line("[APT-FORCE] sweep %d: %d match(es) in %llu ms", reported,
                     matches, (unsigned long long)(GetTickCount64() - scan_started));
        }
    }

    if (matches < kExpectedSites) {
        static int incomplete_passes = 0;
        if (++incomplete_passes == 1) {
            log_line("[APT-FORCE] found %d/%d loaded copies on the first pass "
                     "(sweep took %llu ms); probing what of the APT stream is resident",
                     matches, kExpectedSites,
                     (unsigned long long)(GetTickCount64() - scan_started));
            static const char* const kAnchors[] = {
                "CardsLoginHelper", "FinalizeLogin", "GotoFUTSessionEntry",
                "AdvanceUserToSession",
            };
            for (const char* anchor : kAnchors) {
                const size_t length = strlen(anchor);
                int hits = 0;
                unsigned char* first = nullptr;
                uintptr_t probe = 0;
                while (probe < image_end + 0x40000000ull) {
                    MEMORY_BASIC_INFORMATION mbi;
                    if (VirtualQuery(reinterpret_cast<void*>(probe), &mbi, sizeof(mbi)) == 0) {
                        break;
                    }
                    const uintptr_t start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
                    if (mbi.State == MEM_COMMIT &&
                        !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
                        mbi.RegionSize >= length) {
                        unsigned char* hit = scan_region_for_bytes(
                            reinterpret_cast<unsigned char*>(start), mbi.RegionSize,
                            reinterpret_cast<const unsigned char*>(anchor), length, &hits);
                        if (first == nullptr) first = hit;
                    }
                    if (hits > 1) break;
                    probe = start + mbi.RegionSize;
                }
                log_line("[APT-FORCE]   anchor '%s' hits=%s first=0x%llx", anchor,
                         hits > 1 ? ">1" : (hits == 1 ? "1" : "0"),
                         (unsigned long long)reinterpret_cast<uintptr_t>(first));
            }
            int prefix_hits = 0;
            unsigned char* prefix_first = nullptr;
            uintptr_t probe = 0;
            while (probe < image_end + 0x40000000ull && prefix_hits <= 1) {
                MEMORY_BASIC_INFORMATION mbi;
                if (VirtualQuery(reinterpret_cast<void*>(probe), &mbi, sizeof(mbi)) == 0) break;
                const uintptr_t start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
                if (mbi.State == MEM_COMMIT &&
                    !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
                    mbi.RegionSize >= 6) {
                    unsigned char* hit = scan_region_for_bytes(
                        reinterpret_cast<unsigned char*>(start), mbi.RegionSize,
                        before.data(), 6, &prefix_hits);
                    if (prefix_first == nullptr) prefix_first = hit;
                }
                probe = start + mbi.RegionSize;
            }
            log_line("[APT-FORCE]   signature prefix (6 bytes) hits=%s first=0x%llx",
                     prefix_hits > 1 ? ">1" : (prefix_hits == 1 ? "1" : "0"),
                     (unsigned long long)reinterpret_cast<uintptr_t>(prefix_first));
        }
        return false;
    }

    DWORD old_protect[kExpectedSites] = {0};
    int writable = 0;
    for (int i = 0; i < matches; ++i) {
        if (!VirtualProtect(
                sites[i], after.size(), PAGE_EXECUTE_READWRITE, &old_protect[i])) {
            log_line("[APT-FORCE] copy %d at 0x%llx is not writable; no copies changed",
                     i, (unsigned long long)reinterpret_cast<uintptr_t>(sites[i]));
            for (int j = 0; j < writable; ++j) {
                DWORD ignored = 0;
                VirtualProtect(sites[j], after.size(), old_protect[j], &ignored);
            }
            return false;
        }
        writable++;
    }

    for (int i = 0; i < matches; ++i) {
        memcpy(sites[i], after.data(), after.size());
    }
    bool verified = true;
    for (int i = 0; i < matches; ++i) {
        if (memcmp(sites[i], after.data(), after.size()) != 0) verified = false;
    }
    if (!verified) {
        for (int i = 0; i < matches; ++i) {
            memcpy(sites[i], before.data(), before.size());
        }
        log_line("[APT-FORCE] read-back failed; restored both original copies");
    }
    for (int i = 0; i < matches; ++i) {
        FlushInstructionCache(GetCurrentProcess(), sites[i], after.size());
        DWORD ignored = 0;
        VirtualProtect(sites[i], after.size(), old_protect[i], &ignored);
    }
    if (!verified) return false;

    for (int i = 0; i < matches; ++i) {
        log_line("[APT-FORCE] forced APT branch, copy %d at 0x%llx", i,
                 (unsigned long long)reinterpret_cast<uintptr_t>(sites[i]));
    }
    applied = true;
    log_line("[APT-FORCE] patched %d of %d loaded copies (stream offset 0x%zx); "
             "this is a stopgap, not a fix -- the login condition it skips is "
             "still unanswered", matches, matches, offset);
    return true;
}

namespace {

constexpr unsigned char kFluxWaitAnchorEncoded[] = {
    0xfc, 0x1c, 0xa4, 0x0a, 0xb4, 0x1c, 0xa7, 0xeb, 0x0a,
    0xf1, 0x07, 0x0b, 0xf7, 0xd6, 0xec, 0xb7, 0xb7, 0x38,
    0xa5, 0xa5, 0xa7, 0xa5, 0xa5, 0xa5, 0xd3, 0x9b,
};
constexpr unsigned char kFluxWaitAnchorKey = 0xa5;
constexpr size_t kFluxWaitAnchorOffset = 0x17d4;
constexpr size_t kFluxWaitBranchOffset = 0x11;

bool install_flux_apt_method_probe(HMODULE module,
                                   uintptr_t load_movie_operand);

int scan_region_for_flux_wait(unsigned char* base, size_t size,
                              const unsigned char* anchor, size_t anchor_size,
                              unsigned char** sites, int capacity, int found) {
    __try {
        if (size < anchor_size || found >= capacity) return found;
        unsigned char* p = base;
        size_t left = size - anchor_size + 1;
        while (left > 0 && found < capacity) {
            auto* candidate = reinterpret_cast<unsigned char*>(
                memchr(p, anchor[0], left));
            if (candidate == nullptr) break;
            const size_t consumed = static_cast<size_t>(candidate - p) + 1;
            if (memcmp(candidate, anchor, anchor_size) == 0 &&
                candidate >= base + kFluxWaitAnchorOffset) {
                unsigned char* container = candidate - kFluxWaitAnchorOffset;
                static const char header[] = "Apt Data:1:7:8";
                static const char package[] =
                    "__Packages.game.screens.fluxHub.FluxHub";
                const size_t container_offset =
                    static_cast<size_t>(container - base);
                if (container_offset + 0x160 + sizeof(package) <= size &&
                    memcmp(container, header, sizeof(header) - 1) == 0 &&
                    memcmp(container + 0x160, package, sizeof(package) - 1) == 0) {
                    sites[found++] = candidate;
                }
            }
            p = candidate + 1;
            left -= consumed;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
    return found;
}

}

bool apply_flux_components_ready_patch(uintptr_t hint, bool near_only,
                                       bool synchronize_watch) {
    static std::atomic<bool> applied{false};
    if (applied.load(std::memory_order_acquire)) return true;

    unsigned char anchor[ARRAYSIZE(kFluxWaitAnchorEncoded)];
    for (size_t i = 0; i < ARRAYSIZE(anchor); ++i) {
        anchor[i] = kFluxWaitAnchorEncoded[i] ^ kFluxWaitAnchorKey;
    }

    HMODULE self = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCWSTR>(&apply_flux_components_ready_patch),
                       &self);
    MODULEINFO self_info = {0};
    uintptr_t self_begin = 0, self_end = 0;
    if (self != nullptr &&
        GetModuleInformation(GetCurrentProcess(), self, &self_info,
                             sizeof(self_info))) {
        self_begin = reinterpret_cast<uintptr_t>(self_info.lpBaseOfDll);
        self_end = self_begin + self_info.SizeOfImage;
    }

    const uintptr_t stack_base = static_cast<uintptr_t>(__readgsqword(0x08));
    const uintptr_t stack_limit = static_cast<uintptr_t>(__readgsqword(0x10));
    HMODULE main_module = GetModuleHandleW(nullptr);
    MODULEINFO main_info = {0};
    if (main_module == nullptr ||
        !GetModuleInformation(GetCurrentProcess(), main_module, &main_info,
                              sizeof(main_info))) {
        return false;
    }
    const uintptr_t full_scan_limit =
        reinterpret_cast<uintptr_t>(main_info.lpBaseOfDll) +
        main_info.SizeOfImage + 0x40000000ull;
    constexpr uintptr_t kNearRadius = 0x01000000ull;
    const uintptr_t scan_begin =
        hint != 0 && hint > kNearRadius ? hint - kNearRadius : 0;
    uintptr_t scan_limit = full_scan_limit;
    if (hint != 0 && near_only) {
        scan_limit = hint <= UINTPTR_MAX - kNearRadius
                         ? hint + kNearRadius
                         : UINTPTR_MAX;
        if (scan_limit > full_scan_limit) scan_limit = full_scan_limit;
    }

    unsigned char* sites[2] = {nullptr, nullptr};
    int matches = 0;
    const ULONGLONG started = GetTickCount64();
    uintptr_t address = scan_begin;
    while (address < scan_limit && matches < static_cast<int>(ARRAYSIZE(sites))) {
        MEMORY_BASIC_INFORMATION mbi = {0};
        if (VirtualQuery(reinterpret_cast<void*>(address), &mbi, sizeof(mbi)) == 0) {
            break;
        }
        const uintptr_t region = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        const uintptr_t next = region + mbi.RegionSize;
        const uintptr_t clipped_begin = region < scan_begin ? scan_begin : region;
        const uintptr_t clipped_end = next > scan_limit ? scan_limit : next;
        const bool is_self =
            self_end != 0 && clipped_begin < self_end && clipped_end > self_begin;
        const bool is_stack = clipped_begin < stack_base && clipped_end > stack_limit;
        if (mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE &&
            !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            !is_self && !is_stack && clipped_end > clipped_begin &&
            clipped_end - clipped_begin >= ARRAYSIZE(anchor)) {
            matches = scan_region_for_flux_wait(
                reinterpret_cast<unsigned char*>(clipped_begin),
                clipped_end - clipped_begin,
                anchor, ARRAYSIZE(anchor), sites, ARRAYSIZE(sites), matches);
        }
        if (next <= address) break;
        address = next;
    }

    static std::atomic<int> reports{0};
    const int report = reports.fetch_add(1, std::memory_order_relaxed);
    if (report < 4 || matches != 0) {
        log_line("[FUT-FLUX-WAIT] %s sweep %d found %d validated FluxHub wait "
                 "site(s) in %llu ms hint=0x%llx range={0x%llx..0x%llx}",
                 near_only ? "bounded" : "full", report + 1, matches,
                 static_cast<unsigned long long>(GetTickCount64() - started),
                 static_cast<unsigned long long>(hint),
                 static_cast<unsigned long long>(scan_begin),
                 static_cast<unsigned long long>(scan_limit));
    }
    if (matches != 1) {
        if (matches > 1) {
            log_line("[FUT-FLUX-WAIT] ambiguous result; expected exactly one "
                     "FluxHub container, changed nothing");
        }
        return false;
    }

    unsigned char* branch = sites[0] + kFluxWaitBranchOffset;
    if (*branch != 0x9d) {
        log_line("[FUT-FLUX-WAIT] validated site at 0x%llx has branch byte "
                 "0x%02x, expected 0x9d; changed nothing",
                 static_cast<unsigned long long>(
                     reinterpret_cast<uintptr_t>(branch)),
                 static_cast<unsigned>(*branch));
        return false;
    }

    DWORD old_protect = 0;
    if (!VirtualProtect(branch, 1, PAGE_READWRITE, &old_protect)) {
        log_line("[FUT-FLUX-WAIT] VirtualProtect failed at 0x%llx error=%lu",
                 static_cast<unsigned long long>(
                     reinterpret_cast<uintptr_t>(branch)),
                 GetLastError());
        return false;
    }
    *branch = 0x99;
    const bool verified = *branch == 0x99;
    if (!verified) *branch = 0x9d;
    DWORD ignored = 0;
    VirtualProtect(branch, 1, old_protect, &ignored);
    FlushInstructionCache(GetCurrentProcess(), branch, 1);
    if (!verified) {
        log_line("[FUT-FLUX-WAIT] write verification failed; original byte restored");
        return false;
    }

    applied.store(true, std::memory_order_release);
    log_line("[FUT-FLUX-WAIT] APPLIED at 0x%llx: FluxHub DAT+0x17e5 "
             "branchIfTrue(0x9d) -> jump(0x99); restart restores original",
             static_cast<unsigned long long>(
                 reinterpret_cast<uintptr_t>(branch)));

    constexpr uintptr_t kAptDispatchTableRva = 0x437fc38;
    constexpr uintptr_t kCallConstantMethodPopOpcode = 0xb2;
    uintptr_t call_constant_method_pop = 0;
    __try {
        auto* entry = reinterpret_cast<const uintptr_t*>(
            reinterpret_cast<uintptr_t>(main_module) + kAptDispatchTableRva +
            kCallConstantMethodPopOpcode * 16);
        call_constant_method_pop = *entry;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        call_constant_method_pop = 0;
    }
    MEMORY_BASIC_INFORMATION handler_mbi = {0};
    if (call_constant_method_pop != 0 &&
        region_ok(reinterpret_cast<void*>(call_constant_method_pop), handler_mbi) &&
        region_executable(handler_mbi)) {
        log_line("[FUT-APT-DISPATCH] opcode=0xb2 tableRva=0x437fc38 "
                 "entryRva=0x4380758 handler=0x%llx handlerRva=0x%llx",
                 static_cast<unsigned long long>(call_constant_method_pop),
                 static_cast<unsigned long long>(
                     call_constant_method_pop -
                     reinterpret_cast<uintptr_t>(main_module)));
        dump_va_window(call_constant_method_pop, 0x20000, 0x20000,
                       L"fifa17-revival-apt-b2-handler.bin",
                       "FUT-APT-DISPATCH", "opcode-b2-handler");
    } else {
        log_line("[FUT-APT-DISPATCH] opcode=0xb2 handler unavailable or "
                 "non-executable: 0x%llx",
                 static_cast<unsigned long long>(call_constant_method_pop));
    }

    constexpr size_t kLoadMovieOpcodeBack = 0x17d4 - 0x15bc;
    constexpr size_t kInitializeScreenOpcodeDelta = 0x1897 - 0x17d4;
    const uintptr_t load_movie_opcode =
        reinterpret_cast<uintptr_t>(sites[0] - kLoadMovieOpcodeBack);
    install_flux_apt_method_probe(main_module, load_movie_opcode + 1);
    prepare_flux_opcode_watch(
        load_movie_opcode,
        reinterpret_cast<uintptr_t>(sites[0] + kInitializeScreenOpcodeDelta),
        synchronize_watch ? 1000 : 0);
    return true;
}

const unsigned char kFifaPointsOriginal[kFifaPointsPatchLength] = {
    0x48, 0x8B, 0x0D, 0xCE, 0xB1, 0x1F, 0x00,
    0xE8, 0xC9, 0x1C, 0xF3, 0xFF,
    0x89, 0x43, 0x08,
};

const unsigned char kFifaPointsReplacement[kFifaPointsPatchLength] = {
    0x48, 0x8B, 0x07,
    0x48, 0x8B, 0xCF,
    0xFF, 0x90, 0x90, 0x05, 0x00, 0x00,
    0x89, 0x43, 0x08,
};

PointsSite classify_fifa_points_site(const unsigned char* bytes, size_t length) {
    if (bytes == nullptr || length != kFifaPointsPatchLength) {
        return PointsSite::Unrecognised;
    }
    if (memcmp(bytes, kFifaPointsReplacement, kFifaPointsPatchLength) == 0) {
        return PointsSite::AlreadyPatched;
    }
    if (memcmp(bytes, kFifaPointsOriginal, kFifaPointsPatchLength) == 0) {
        return PointsSite::Original;
    }
    return PointsSite::Unrecognised;
}

namespace {

bool within_text_section(const unsigned char* base, uint32_t rva, size_t length) {
    auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    const IMAGE_SECTION_HEADER* section = IMAGE_FIRST_SECTION(nt);
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++section) {
        if (memcmp(section->Name, ".text", 5) != 0) continue;
        const uint32_t begin = section->VirtualAddress;
        const uint32_t end = begin + section->Misc.VirtualSize;
        return rva >= begin && rva + length <= end;
    }
    log_line("[FIFA POINTS] CardsDLL has no .text section; refusing to patch");
    return false;
}

bool g_fifa_points_logged_missing = false;

}

bool apply_fifa_points_patch() {
    auto* base = reinterpret_cast<unsigned char*>(
        GetModuleHandleW(L"CardsDLL_Win64_retail.dll"));
    if (base == nullptr) {
        if (!g_fifa_points_logged_missing) {
            g_fifa_points_logged_missing = true;
            log_line("[FIFA POINTS] waiting for CardsDLL_Win64_retail.dll");
        }
        return false;
    }

    auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        log_line("[FIFA POINTS] CardsDLL has an unreadable PE header");
        return false;
    }
    auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) {
        log_line("[FIFA POINTS] CardsDLL has an unreadable PE header");
        return false;
    }

    const uint32_t stamp = nt->FileHeader.TimeDateStamp;
    const uint32_t image_size = nt->OptionalHeader.SizeOfImage;
    if (stamp != kCardsDllTimeDateStamp || image_size != kCardsDllSizeOfImage) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            log_line(
                "[FIFA POINTS] unsupported CardsDLL build (timestamp 0x%08X size "
                "0x%08X; expected 0x%08X / 0x%08X); refusing to patch",
                stamp, image_size, kCardsDllTimeDateStamp, kCardsDllSizeOfImage);
        }
        return false;
    }

    if (!within_text_section(base, kFifaPointsPatchRva, kFifaPointsPatchLength)) {
        log_line("[FIFA POINTS] patch site lies outside .text; refusing to patch");
        return false;
    }

    unsigned char* site = base + kFifaPointsPatchRva;
    switch (classify_fifa_points_site(site, kFifaPointsPatchLength)) {
        case PointsSite::AlreadyPatched:
            return true;
        case PointsSite::Unrecognised:
            log_line(
                "[FIFA POINTS] patch site does not hold the expected retail bytes "
                "(base=0x%llx rva=0x%X); refusing to patch",
                (unsigned long long)reinterpret_cast<uintptr_t>(base),
                kFifaPointsPatchRva);
            return false;
        case PointsSite::Original:
            break;
    }

    DWORD old_protect = 0;
    if (!VirtualProtect(site, kFifaPointsPatchLength, PAGE_EXECUTE_READWRITE,
                        &old_protect)) {
        log_line("[FIFA POINTS] could not make the patch site writable");
        return false;
    }
    memcpy(site, kFifaPointsReplacement, kFifaPointsPatchLength);
    DWORD ignored = 0;
    VirtualProtect(site, kFifaPointsPatchLength, old_protect, &ignored);
    FlushInstructionCache(GetCurrentProcess(), site, kFifaPointsPatchLength);

    if (classify_fifa_points_site(site, kFifaPointsPatchLength) !=
        PointsSite::AlreadyPatched) {
        log_line("[FIFA POINTS] replacement verification failed");
        return false;
    }

    log_line("[FIFA POINTS] CardsDLL_Win64_retail.dll base=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(base));
    log_line(
        "[FIFA POINTS] redirected the DIME balance at RVA 0x%X to "
        "FutDataManager::GetUserPointsBalance (+0x590)",
        kFifaPointsPatchRva);
    log_line("[FIFA POINTS] DIME bypass active; the balance no longer waits on "
             "Origin commerce");
    return true;
}

bool recon_online_verdict() {
    static bool already = false;
    if (already) return false;

    struct Anchor { const char* text; const wchar_t* file; const char* tag; };
    const Anchor anchors[] = {
        {"OSDK_ONLINE_OUTDATED_PATCH", L"fifa17-revival-verdict-outdated.bin", "outdated"},
        {"Client/server version mismatch!", L"fifa17-revival-verdict-mismatch.bin", "mismatch"},
        {"SV_ENABLE_SERVER_VERSIONING", L"fifa17-revival-verdict-svkey.bin", "sv-key"},
        {"GetPrivPol", L"fifa17-revival-verdict-loginstate.bin", "login-state"},
        {"loadFUTDatabase", L"fifa17-revival-futdb-load.bin", "futdb-load"},
        {"isFUTRosterXMLAvailable", L"fifa17-revival-futdb-rosterxml.bin", "futdb-rosterxml"},
        {"isFUTSquadAvailable", L"fifa17-revival-futdb-squad.bin", "futdb-squad"},
        {"FailToEnterFUT", L"fifa17-revival-futdb-fail.bin", "futdb-fail"},
    };
    const uintptr_t pad = 0x40000;

    static bool captured[ARRAYSIZE(anchors)] = {false};
    int dumped = 0;
    size_t outstanding = 0;
    for (size_t i = 0; i < ARRAYSIZE(anchors); ++i) {
        const Anchor& a = anchors[i];
        if (captured[i]) continue;
        uintptr_t fn = find_anchor_function(a.text);
        if (fn == 0) {
            outstanding++;
            static int quiet[ARRAYSIZE(anchors)] = {0};
            if (++quiet[i] == 1 || quiet[i] % 60 == 0) {
                log_line("[VERDICT] anchor '%s' not referenced by decrypted code yet",
                         a.text);
            }
            continue;
        }
        log_line("[VERDICT] anchor '%s' referenced from fn=0x%llx", a.text,
                 (unsigned long long)fn);
        if (dump_va_window(fn, pad, pad, a.file, "VERDICT", a.tag)) {
            captured[i] = true;
            dumped++;
        } else {
            outstanding++;
        }
    }
    if (dumped > 0) {
        log_line("[VERDICT] captured %d window(s) this pass; %zu anchor(s) still "
                 "waiting to decrypt", dumped, outstanding);
    }
    if (outstanding > 0) return false;
    already = true;
    log_line("[VERDICT] every anchor captured; disassemble the branch that selects "
             "the string to name the condition and the command feeding it");
    return true;
}

bool recon_authentication_dump() {
    static bool already = false;
    if (already) return false;

    uintptr_t fn = find_anchor_function("AuthenticationComponent");
    const char* anchor = "AuthenticationComponent";
    if (fn == 0) {
        fn = find_anchor_function("AUTHENTICATIONInstance");
        anchor = "AUTHENTICATIONInstance";
    }
    if (fn == 0) return false;

    log_line("[AUTH-RECON] anchor '%s' fn=0x%llx", anchor, (unsigned long long)fn);
    if (!dump_va_window(fn, 0x100000, 0x100000,
                        L"fifa17-revival-auth-component.bin", "AUTH-RECON",
                        "auth-component")) {
        return false;
    }
    already = true;
    log_line("[AUTH-RECON] Authentication registration window captured; derive command "
             "IDs from constructor calls before assigning a schema to command 70");
    return true;
}

bool recon_util_dump() {
    static bool already = false;
    if (already) return false;

    uintptr_t fn = find_anchor_function("UtilComponent");
    const char* anchor = "UtilComponent";
    if (fn == 0) {
        fn = find_anchor_function("UTILInstance");
        anchor = "UTILInstance";
    }
    if (fn == 0) return false;

    log_line("[UTIL-RECON] anchor '%s' fn=0x%llx", anchor,
             (unsigned long long)fn);
    if (!dump_va_window(fn, 0x100000, 0x100000,
                        L"fifa17-revival-util-component.bin", "UTIL-RECON",
                        "util-component")) {
        return false;
    }
    already = true;
    log_line("[UTIL-RECON] Util registration/type window captured; derive command 8's "
             "PostAuthResponse directly from the generated descriptor");
    return true;
}

bool recon_census_dump() {
    static bool already = false;
    if (already) return false;

    uintptr_t fn = find_anchor_function("CensusDataComponent");
    const char* anchor = "CensusDataComponent";
    if (fn == 0) {
        fn = find_anchor_function("CENSUSDATAInstance");
        anchor = "CENSUSDATAInstance";
    }
    if (fn == 0) return false;

    log_line("[CENSUS-RECON] anchor '%s' fn=0x%llx", anchor,
             (unsigned long long)fn);
    if (!dump_va_window(fn, 0x100000, 0x100000,
                        L"fifa17-revival-census-component.bin", "CENSUS-RECON",
                        "census-component")) {
        return false;
    }

    HMODULE module = GetModuleHandleW(nullptr);
    if (module != nullptr) {
        uintptr_t member_table = reinterpret_cast<uintptr_t>(module) + 0x4c11bf0;
        if (!dump_va_window(member_table, 0x1000, 0x3000,
                            L"fifa17-revival-census-descriptors.bin",
                            "CENSUS-RECON", "census-descriptors")) {
            log_line("[CENSUS-RECON] command-5 MemberInfo table was not readable");
        }
    }
    already = true;
    log_line("[CENSUS-RECON] CensusData registration/type window captured; derive command "
             "5's response and notification directly from generated descriptors");
    return true;
}

bool recon_fut_dump() {
    static bool already = false;
    if (already) return false;

    uintptr_t fn = find_anchor_function("userClubList");
    if (fn == 0) return false;

    log_line("[FUT-RECON] parser anchor 'userClubList' fn=0x%llx",
             (unsigned long long)fn);
    if (!dump_va_window(fn, 0x800000, 0x800000,
                        L"fifa17-revival-fut-accountinfo.bin", "FUT-RECON",
                        "accountinfo-parser")) {
        return false;
    }
    already = true;
    log_line("[FUT-RECON] accountinfo code window captured; inspect the response "
             "completion path and users/club transition");
    return true;
}

namespace {

bool write_code(unsigned char* dest, const unsigned char* src, size_t len) {
    DWORD old_protect = 0;
    if (!VirtualProtect(dest, len, PAGE_EXECUTE_READWRITE, &old_protect)) return false;
    memcpy(dest, src, len);
    VirtualProtect(dest, len, old_protect, &old_protect);
    FlushInstructionCache(GetCurrentProcess(), dest, len);
    return true;
}

using FutParser = void(__fastcall *)(void* completion, const char* json, int length);
using FutParserCallback = void(__fastcall *)(
    bool parsed, bool valid_club, bool returning_user, const char* club_name,
    uint32_t established, uint32_t asset_id);
using FutRegistration = void(__fastcall *)(void* owner, FutParserCallback callback);
using FutReadinessPredicate = bool(__fastcall *)();
using FutUiEventDispatcher = void*(__fastcall *)(void* owner, uint32_t event_id);
using FutClubUrlBuilder = uintptr_t(__fastcall *)(
    void* context, void* output, int32_t argument);
using FutUiModelPublish = uintptr_t(__fastcall *)(
    void* model, uint32_t event_id, void* payload);
using FutScriptPublishBridge = uintptr_t(__fastcall *)(
    void* context, void* namespace_name, void* function_name, void* payload,
    void* resolved_event);
using FutUiRouter = void(__fastcall *)(
    void* router, uint32_t event_id, void* payload);
using FutUiSendAction = void(__fastcall *)(
    void* controller, uint32_t view_type, uint32_t view_id,
    uint32_t action_id, void* action_param);
using FutViewManagerProcessAction = uintptr_t(__fastcall *)(
    void* manager, uint32_t action_id, void* action_payload);
using FutAptActionBridge = void(__fastcall *)(
    void* manager, uint32_t action_id, void* apt_payload);
using FutAptCallMethodPop = void(__fastcall *)(
    void* interpreter, uint32_t opcode, void* operation);
using FutModernAptCallConstantMethod = void(__fastcall *)(
    void* interpreter, void** instruction_cursor);
using FutModernAptGetMember = void(__fastcall *)(void* interpreter);
using FutModernAptInvokeCallable = void(__fastcall *)(
    void* interpreter, void* receiver, void* callable, uint32_t argument_count,
    void* call_context, void* result_target, bool preserve_result);
using FutModernAptResolveMoviePath = uintptr_t(__fastcall *)(
    void* receiver, void** path_holder, uint32_t mode);
using FutModernAptLoadMovieDispatch = uintptr_t(__fastcall *)(
    void* manager, void** original_path_holder, void** resolved_path_holder,
    void* callback);
using FutAptVmStateGetter = void*(__fastcall *)();
using FutUiListHandler = uintptr_t(__fastcall *)(
    void* handler, uint32_t event_id, void* payload_list);
using FutSaveDecoder = void(__fastcall *)(void* owner, void* operation);
using FutLoginFlowHandler = uintptr_t(__fastcall *)(
    void* owner, uint32_t event_id, void* payload);

FutParser g_fut_parser_original = nullptr;
FutParserCallback g_fut_callback_original = nullptr;
FutParserCallback g_fut_downstream_original = nullptr;
FutRegistration g_fut_registration_original = nullptr;
FutUiEventDispatcher g_fut_ui_event_dispatcher_original = nullptr;
FutClubUrlBuilder g_fut_club_url_builder_original = nullptr;

using FutClubSubmit = uintptr_t(__fastcall *)(void*, void*);
FutClubSubmit g_fut_club_submit_original = nullptr;

using FutPhaseHandler = uintptr_t(__fastcall *)(void*);
FutPhaseHandler g_fut_phase_handler_original = nullptr;
FutUiModelPublish g_fut_ui_model_publish_original = nullptr;
FutScriptPublishBridge g_fut_script_publish_bridge_original = nullptr;
FutUiRouter g_fut_ui_router_original = nullptr;
FutUiSendAction g_fut_ui_send_action_original = nullptr;
FutViewManagerProcessAction g_fut_view_manager_process_action_original = nullptr;
FutAptActionBridge g_fut_apt_action_bridge_original = nullptr;
FutAptCallMethodPop g_fut_apt_call_method_pop_original = nullptr;
FutModernAptCallConstantMethod g_flux_apt_method_original = nullptr;
FutModernAptGetMember g_transfer_pile_get_member_original = nullptr;
std::atomic<uint32_t> g_transfer_pile_capacity_hits{0};
FutModernAptInvokeCallable g_flux_apt_callable_original = nullptr;
FutModernAptResolveMoviePath g_flux_apt_resolve_path_original = nullptr;
FutModernAptLoadMovieDispatch g_flux_apt_load_dispatch_original = nullptr;
std::atomic<uintptr_t> g_flux_load_movie_operand{0};
std::atomic<bool> g_flux_callable_dispatch_dumped{false};
thread_local unsigned g_flux_load_movie_dispatch_depth = 0;
thread_local unsigned g_flux_callable_capture_count = 0;
std::atomic<bool> g_fut_apt_vm_probe_enabled{false};
std::atomic<uint32_t> g_fut_apt_vm_probe_count{0};
std::atomic<void*> g_fut_apt_manager{nullptr};
std::atomic<bool> g_fut_force_profile_advance_enabled{false};
std::atomic<bool> g_fut_force_profile_advance_fired{false};
std::atomic<bool> g_fut_profile_state_consumed{false};
std::atomic<bool> g_fut_profile_publish_succeeded{false};
std::atomic<bool> g_fut_script_publish_probe_enabled{false};
std::atomic<uint32_t> g_fut_script_publish_probe_count{0};
std::atomic<unsigned long long> g_fut_action_trace_sequence{0};
std::atomic<ULONGLONG> g_squad_input_capture_until{0};
std::atomic<bool> g_flux_components_ready_enabled{false};
std::atomic<bool> g_flux_components_ready_requested{false};
FutUiListHandler g_fut_ui_list_handler_original = nullptr;
std::atomic<bool> g_fut_ui_list_handler_installed{false};
FutSaveDecoder g_fut_save_decoder_original = nullptr;
FutLoginFlowHandler g_fut_login_flow_handler_original = nullptr;
std::atomic<bool> g_fut_registration_deferred{false};
std::atomic<void*> g_fut_deferred_owner{nullptr};
std::atomic<uintptr_t> g_fut_deferred_callback{0};

constexpr uintptr_t kFutDownstreamCallbackRva = 0x48a2840;
constexpr uintptr_t kFutValidClubRva = 0x43309e0;
constexpr uintptr_t kFutReturningUserRva = 0x43309e1;
constexpr uintptr_t kFutClubNameRva = 0x43309e2;
constexpr uintptr_t kFutEstablishedRva = 0x4330a00;
constexpr uintptr_t kFutAssetIdRva = 0x4330a20;
constexpr uintptr_t kFutDataReadyRva = 0x48a2221;
constexpr uintptr_t kFutCompletionRva = 0x4330a24;
constexpr uintptr_t kFutRegistrationRva = 0x6ec9ad0;
constexpr uintptr_t kFutFrontendReadyRva = 0x71a5da0;
constexpr uintptr_t kFutOnlineReadyRva = 0x6f38ef0;
constexpr uintptr_t kFutFrontendOwnerRva = 0x4b86bf8;
constexpr uintptr_t kFutFrontendBlockedRva = 0x4b86bdf;
constexpr uintptr_t kFutStateConsumerRva = 0x6ec8b80;
constexpr uintptr_t kFutClubUrlBuilderRva = 0x6ec7320;
constexpr uintptr_t kFutClubSubmitRva = 0x6ec9ba0;

constexpr uintptr_t kFutPhaseHandlerRva = 0x7d4e090;
constexpr uintptr_t kFutPhaseFieldOffset = 0x1fc;
constexpr uintptr_t kFutPhaseBusyOffset = 0x1f8;
constexpr uintptr_t kFutPhasePendingOffset = 0x1f9;
constexpr uintptr_t kFutUiEventDispatcherRva = 0x7d36680;

constexpr uintptr_t kFutConditionDispatcherRva = 0x7DBF910;
constexpr uintptr_t kFutUiEventJumpTableRva = 0x2933f1c;
constexpr uintptr_t kFutUiModelPublishRva = 0x80d00a0;
constexpr uintptr_t kFutUiModelVtableRva = 0x3bb3bb8;
constexpr uintptr_t kFutScriptPublishBridgeRva = 0x7577600;
constexpr uintptr_t kFutUiRouterWrapperRva = 0x80d6030;
constexpr uintptr_t kFutUiRouterRva = 0x80d6040;
constexpr uintptr_t kFutUiSendActionRva = 0x80d23c0;
constexpr uintptr_t kFutViewManagerProcessActionRva = 0x80cf590;
constexpr uintptr_t kFutAptActionBridgeRva = 0x80cf5f0;
constexpr uintptr_t kFutAptCallMethodPopRva = 0x7aa5610;
constexpr uintptr_t kFutAptVmStateGetterRva = 0x6f2ae20;
constexpr uint32_t kFutNavAdvanceAction = 2;
constexpr uint32_t kFutNavConditionAction = 29;
constexpr uint32_t kFutSquadNameAction = 30003;
constexpr uintptr_t kFutSaveDecoderRva = 0x68ca9a0;
constexpr uintptr_t kFutLoginFlowHandlerRva = 0x7dbc6f0;
constexpr uint32_t kFutLoginFlowTriggerEvent = 0x0be7;

bool install_fut_ui_event_dispatcher_probe(HMODULE module);
bool install_fut_condition_dispatch_probe(HMODULE module);
bool install_fut_roster_available_patch(HMODULE module);
bool install_fut_club_url_builder_probe(HMODULE module);
bool install_fut_club_submit_probe(HMODULE module);
bool install_fut_phase_handler_probe(HMODULE module);
bool install_fut_ui_model_publish_probe(HMODULE module);
bool install_fut_script_publish_bridge_probe(HMODULE module);
bool install_fut_ui_router_probe(HMODULE module);
bool install_fut_navigation_probes(HMODULE module);
bool install_fut_ui_list_handler_probe(void* handler);
bool install_fut_save_decoder_probe(HMODULE module);
bool install_fut_login_flow_handler_probe(HMODULE module);

bool exchange_callback(void** slot, void* replacement, void** previous) {
    DWORD old_protect = 0;
    if (!VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old_protect)) return false;
    *previous = InterlockedExchangePointer(
        reinterpret_cast<PVOID volatile*>(slot), replacement);
    DWORD ignored = 0;
    VirtualProtect(slot, sizeof(*slot), old_protect, &ignored);
    return true;
}

void __fastcall fut_downstream_probe(
    bool parsed, bool valid_club, bool returning_user, const char* club_name,
    uint32_t established, uint32_t asset_id) {
    log_line(
        "[FUT-PROBE] downstream entered target=0x%llx parsed=%u validClub=%u "
        "returningUser=%u clubName='%.30s' established=%u assetId=%u",
        (unsigned long long)reinterpret_cast<uintptr_t>(g_fut_downstream_original),
        parsed ? 1u : 0u, valid_club ? 1u : 0u, returning_user ? 1u : 0u,
        club_name != nullptr ? club_name : "", established, asset_id);
    if (g_fut_downstream_original != nullptr) {
        g_fut_downstream_original(
            parsed, valid_club, returning_user, club_name, established, asset_id);
    }
    log_line("[FUT-PROBE] downstream returned normally");
}

void maybe_force_post_profile_advance(uint32_t event_id) {
    if (event_id != 0x2763 ||
        !g_fut_profile_state_consumed.load() ||
        !g_fut_profile_publish_succeeded.load() ||
        !g_fut_force_profile_advance_enabled.load() ||
        g_fut_force_profile_advance_fired.load()) {
        return;
    }

    void* manager = g_fut_apt_manager.load();
    FutAptActionBridge bridge = g_fut_apt_action_bridge_original;
    if (manager == nullptr || bridge == nullptr) {
        log_line(
            "[FUT-FORCE] post-profile advance pending: manager=0x%llx "
            "bridge=0x%llx",
            (unsigned long long)reinterpret_cast<uintptr_t>(manager),
            (unsigned long long)reinterpret_cast<uintptr_t>(bridge));
        return;
    }

    bool expected = false;
    if (!g_fut_force_profile_advance_fired.compare_exchange_strong(
            expected, true)) {
        return;
    }
    log_line(
        "[FUT-FORCE] injecting one-shot advance after successful 0x2763 "
        "route manager=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(manager));
    bridge(manager, kFutNavAdvanceAction, nullptr);
    log_line("[FUT-FORCE] one-shot advance returned normally");
}

uint32_t __fastcall fut_state_consumer_probe(void* owner, void* output) {
    void* caller = _ReturnAddress();
    HMODULE module = GetModuleHandleW(nullptr);
    auto base = reinterpret_cast<uintptr_t>(module);
    if (g_fut_ui_event_dispatcher_original == nullptr) {
        install_fut_ui_event_dispatcher_probe(module);
        install_fut_condition_dispatch_probe(module);
    }
    install_fut_roster_available_patch(module);
    if (g_fut_club_url_builder_original == nullptr) {
        install_fut_club_url_builder_probe(module);
    }
    if (g_fut_ui_router_original == nullptr) {
        install_fut_ui_router_probe(module);
    }
    auto* data_ready = reinterpret_cast<unsigned char*>(base + kFutDataReadyRva);
    const unsigned was_ready = static_cast<unsigned>(*data_ready);
    log_line(
        "[FUT-PROBE] state consumer entered owner=0x%llx output=0x%llx "
        "dataReady=%u caller=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(output),
        was_ready,
        (unsigned long long)reinterpret_cast<uintptr_t>(caller));
    capture_fut_runtime_callsite("state-consumer", caller);
    uint32_t result = 0;
    if (output != nullptr) {
        memcpy(output, reinterpret_cast<const void*>(base + kFutValidClubRva), 0x4c);
        memcpy(&result,
               reinterpret_cast<const void*>(base + kFutValidClubRva + 0x48),
               sizeof(result));
        *data_ready = 0;
        const auto* copied = reinterpret_cast<const unsigned char*>(output);
        if (was_ready != 0 && copied[0] != 0 && copied[1] != 0) {
            g_fut_profile_state_consumed.store(true);
            if (g_fut_force_profile_advance_enabled.load()) {
                log_line(
                    "[FUT-FORCE] accepted returning-user state consumed; "
                    "waiting for successful 0x2763 publish");
            }
        }
        log_line(
            "[FUT-PROBE] state consumer returned validClub=%u returningUser=%u "
            "clubName='%.30s' dataReady=%u",
            static_cast<unsigned>(copied[0]), static_cast<unsigned>(copied[1]),
            reinterpret_cast<const char*>(copied + 2),
            static_cast<unsigned>(*data_ready));
    }
    return result;
}

const char* fut_named_id(uint32_t id);

void __fastcall fut_ui_router_probe(
    void* router, void* payload, uint32_t event_id) {
    void* caller = _ReturnAddress();
    log_line(
        "[FUT-ROUTER] input id=0x%x (%u) [%s] router=0x%llx payload=0x%llx "
        "caller=0x%llx",
        event_id, event_id, fut_named_id(event_id),
        (unsigned long long)reinterpret_cast<uintptr_t>(router),
        (unsigned long long)reinterpret_cast<uintptr_t>(payload),
        (unsigned long long)reinterpret_cast<uintptr_t>(caller));
    if (event_id == 0x138a &&
        g_flux_components_ready_enabled.load(std::memory_order_acquire)) {
        const bool was_requested =
            g_flux_components_ready_requested.exchange(true, std::memory_order_acq_rel);
        if (!was_requested) {
            log_line("[FUT-FLUX-WAIT] FLUX_COMPONENTS_DP observed; patch scan requested");
        }
        if (apply_flux_components_ready_patch(
                reinterpret_cast<uintptr_t>(payload), true, true)) {
            g_flux_components_ready_requested.store(false,
                                                     std::memory_order_release);
            log_line("[FUT-FLUX-WAIT] bounded patch completed before original "
                     "FLUX_COMPONENTS_DP router call");
        }
    }
    if (g_fut_ui_router_original != nullptr) {
        g_fut_ui_router_original(router, event_id, payload);
    }
    log_line("[FUT-ROUTER] returned id=0x%x", event_id);
    maybe_force_post_profile_advance(event_id);
}

const char* fut_nav_action_name(uint32_t action_id) {
    if (action_id == kFutNavAdvanceAction) return "advance";
    if (action_id == kFutNavConditionAction) return "condition";
    return "";
}

const char* fut_named_id(uint32_t id) {
    static thread_local char described[160];
    const char* compiled = fut_nav_action_name(id);
    if (compiled[0] != '\0') return compiled;
    return ui_registry_describe(id, described, sizeof(described));
}

bool copy_fut_action_param(void* action_param, char* output, size_t capacity) {
    if (output == nullptr || capacity == 0) return false;
    output[0] = '\0';
    const char* text = nullptr;
    __try {
        if (action_param != nullptr) {
            text = *reinterpret_cast<const char* const*>(action_param);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
    return copy_ansi_path(text, output, capacity);
}

void __fastcall fut_ui_send_action_probe(
    void* controller, uint32_t view_type, uint32_t view_id,
    uint32_t action_id, void* action_param) {
    char param[192] = {0};
    const bool has_param = copy_fut_action_param(action_param, param, sizeof(param));
    log_line(
        "[FUT-NAV] SendAction viewType=%u viewId=%u action=%u name='%s' "
        "param=%s%s%s wrapper=0x%llx",
        view_type, view_id, action_id,
        fut_nav_action_name(action_id),
        has_param ? "'" : "<unreadable>", has_param ? param : "",
        has_param ? "'" : "",
        (unsigned long long)reinterpret_cast<uintptr_t>(action_param));
    if (g_fut_ui_send_action_original != nullptr) {
        g_fut_ui_send_action_original(
            controller, view_type, view_id, action_id, action_param);
    }
}

bool payload_readable(const void* pointer, size_t bytes) {
    if (pointer == nullptr || bytes == 0) return false;
    const uintptr_t address = reinterpret_cast<uintptr_t>(pointer);
    if (address < 0x10000 || address >= 0x0000800000000000ull) return false;
    if (address + bytes < address) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!region_ok(const_cast<void*>(pointer), mbi)) return false;
    const uintptr_t region_end =
        reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    return address + bytes <= region_end;
}

size_t payload_read_ascii(const void* pointer, char* out, size_t capacity) {
    if (capacity < 2 || !payload_readable(pointer, 2)) return 0;
    const char* source = reinterpret_cast<const char*>(pointer);
    size_t length = 0;
    __try {
        while (length + 1 < capacity && length < 63) {
            const unsigned char character = static_cast<unsigned char>(source[length]);
            if (character == 0) break;
            if (character < 0x20 || character > 0x7E) return 0;
            out[length++] = static_cast<char>(character);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
    if (length < 3) return 0;
    out[length] = '\0';
    return length;
}

size_t payload_read_utf16(const void* pointer, char* out, size_t capacity) {
    if (capacity < 2 || !payload_readable(pointer, 4)) return 0;
    const wchar_t* source = reinterpret_cast<const wchar_t*>(pointer);
    size_t length = 0;
    __try {
        while (length + 1 < capacity && length < 63) {
            const wchar_t character = source[length];
            if (character == 0) break;
            if (character < 0x20 || character > 0x7E) return 0;
            out[length++] = static_cast<char>(character);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
    if (length < 3) return 0;
    out[length] = '\0';
    return length;
}

size_t payload_read_text(const void* pointer, char* out, size_t capacity) {
    const size_t narrow = payload_read_ascii(pointer, out, capacity);
    if (narrow != 0) return narrow;
    return payload_read_utf16(pointer, out, capacity);
}

bool payload_text_is_allocator_tag(const char* text) {
    static const char* const kTags[] = {
        "UIFramework::",
        "EA::RawString",
        "EASTLICA",
        "EASTL",
        "FeFlow",
    };
    for (const char* tag : kTags) {
        if (strstr(text, tag) != nullptr) return true;
    }
    return false;
}

void describe_action_payload(void* payload, char* out, size_t capacity) {
    if (capacity == 0) return;
    out[0] = '\0';
    if (!payload_readable(payload, sizeof(void*))) return;

    char text[72];
    size_t used = 0;
    int found = 0;
    auto append = [&](const char* what) {
        if (found >= 8 || used + 3 >= capacity) return;
        if (payload_text_is_allocator_tag(what)) return;
        if (used != 0 && strstr(out, what) != nullptr) return;
        const int written = _snprintf_s(out + used, capacity - used, _TRUNCATE,
                                        "%s%s", used ? "|" : "", what);
        if (written > 0) {
            used += static_cast<size_t>(written);
            found++;
        }
    };

    if (payload_read_text(payload, text, sizeof(text))) append(text);

    void* const* words = reinterpret_cast<void* const*>(payload);
    for (int i = 0; i < 32 && found < 8; ++i) {
        if (!payload_readable(words + i, sizeof(void*))) break;
        void* first = words[i];
        if (payload_read_text(first, text, sizeof(text))) {
            append(text);
            continue;
        }
        if (!payload_readable(first, sizeof(void*))) continue;
        void* const* inner = reinterpret_cast<void* const*>(first);
        for (int j = 0; j < 12 && found < 8; ++j) {
            if (!payload_readable(inner + j, sizeof(void*))) break;
            void* second = inner[j];
            if (payload_read_text(second, text, sizeof(text))) {
                append(text);
                continue;
            }
            if (i >= 16 || !payload_readable(second, sizeof(void*))) continue;
            void* const* third = reinterpret_cast<void* const*>(second);
            for (int k = 0; k < 6 && found < 8; ++k) {
                if (!payload_readable(third + k, sizeof(void*))) break;
                if (payload_read_text(third[k], text, sizeof(text))) append(text);
            }
        }
    }
}

void log_apt_value_vector(uint32_t action_id, void* payload) {
    if (!payload_readable(payload, 6 * sizeof(void*))) return;
    void* const* words = reinterpret_cast<void* const*>(payload);
    auto begin = reinterpret_cast<void* const*>(words[2]);
    auto end = reinterpret_cast<void* const*>(words[3]);
    if (begin == nullptr || end == nullptr || end < begin) return;
    const size_t span = reinterpret_cast<const unsigned char*>(end) -
                        reinterpret_cast<const unsigned char*>(begin);
    if (span == 0 || span % sizeof(void*) != 0 || span > 64 * sizeof(void*)) return;
    const size_t count = span / sizeof(void*);
    if (!payload_readable(begin, span)) return;

    char text[72];
    for (size_t i = 0; i < count && i < 8; ++i) {
        void* element = begin[i];
        if (payload_read_text(element, text, sizeof(text)) &&
            !payload_text_is_allocator_tag(text)) {
            log_line("[FUT-NAV] aptValue[%zu] action=%u text='%s'", i, action_id, text);
            continue;
        }
        if (!payload_readable(element, 4 * sizeof(void*))) {
            log_line("[FUT-NAV] aptValue[%zu] action=%u raw=0x%llx", i, action_id,
                     (unsigned long long)reinterpret_cast<uintptr_t>(element));
            continue;
        }
        void* const* fields = reinterpret_cast<void* const*>(element);
        log_line("[FUT-NAV] aptValue[%zu] action=%u fields={%llx,%llx,%llx,%llx}",
                 i, action_id,
                 (unsigned long long)reinterpret_cast<uintptr_t>(fields[0]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(fields[1]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(fields[2]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(fields[3]));
        for (int f = 0; f < 4; ++f) {
            if (payload_read_text(fields[f], text, sizeof(text)) &&
                !payload_text_is_allocator_tag(text)) {
                log_line("[FUT-NAV] aptValue[%zu].f%d action=%u text='%s'",
                         i, f, action_id, text);
            }
        }
    }
}

void log_squad_action_payload(const char* boundary,
                              unsigned long long sequence,
                              uint32_t action_id, void* payload) {
    if (action_id != kFutSquadNameAction) return;
    uintptr_t words[16] = {};
    bool readable = false;
    __try {
        if (payload != nullptr) {
            memcpy(words, payload, sizeof(words));
            readable = true;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        readable = false;
    }
    log_line(
        "[SQUAD-ACTION] seq=%llu tid=%lu boundary=%s payload=0x%llx "
        "readable=%u words={%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx,"
        "%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx}",
        sequence, GetCurrentThreadId(), boundary,
        (unsigned long long)reinterpret_cast<uintptr_t>(payload),
        readable ? 1u : 0u,
        (unsigned long long)words[0], (unsigned long long)words[1],
        (unsigned long long)words[2], (unsigned long long)words[3],
        (unsigned long long)words[4], (unsigned long long)words[5],
        (unsigned long long)words[6], (unsigned long long)words[7],
        (unsigned long long)words[8], (unsigned long long)words[9],
        (unsigned long long)words[10], (unsigned long long)words[11],
        (unsigned long long)words[12], (unsigned long long)words[13],
        (unsigned long long)words[14], (unsigned long long)words[15]);
    if (!readable) return;

    for (int i = 0; i < 8; ++i) {
        const uintptr_t target = words[i];
        if (target < 0x10000 || target > 0x7FFFFFFFFFFFull) continue;
        uintptr_t target_words[8] = {};
        bool target_readable = false;
        __try {
            memcpy(target_words, reinterpret_cast<const void*>(target),
                   sizeof(target_words));
            target_readable = true;
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            target_readable = false;
        }
        if (!target_readable) continue;
        log_line(
            "[SQUAD-ACTION] seq=%llu boundary=%s w%d->0x%llx "
            "words={%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx}",
            sequence, boundary, i, (unsigned long long)target,
            (unsigned long long)target_words[0],
            (unsigned long long)target_words[1],
            (unsigned long long)target_words[2],
            (unsigned long long)target_words[3],
            (unsigned long long)target_words[4],
            (unsigned long long)target_words[5],
            (unsigned long long)target_words[6],
            (unsigned long long)target_words[7]);
    }
}

void log_payload_fields(uint32_t action_id, void* payload) {
    if (!payload_readable(payload, 6 * sizeof(void*))) return;
    void* const* words = reinterpret_cast<void* const*>(payload);
    char text[72];
    for (int i = 1; i <= 4; ++i) {
        void* field = words[i];
        if (!payload_readable(field, 4 * sizeof(void*))) continue;
        void* const* inner = reinterpret_cast<void* const*>(field);
        log_line("[FUT-NAV] payload.w%d action=%u at=0x%llx {%llx,%llx,%llx,%llx}",
                 i, action_id, (unsigned long long)reinterpret_cast<uintptr_t>(field),
                 (unsigned long long)reinterpret_cast<uintptr_t>(inner[0]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(inner[1]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(inner[2]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(inner[3]));
        if (payload_read_text(field, text, sizeof(text)) &&
            !payload_text_is_allocator_tag(text)) {
            log_line("[FUT-NAV] payload.w%d action=%u inlineText='%s'", i, action_id, text);
        }
        for (int j = 0; j < 4; ++j) {
            if (payload_read_text(inner[j], text, sizeof(text)) &&
                !payload_text_is_allocator_tag(text)) {
                log_line("[FUT-NAV] payload.w%d.f%d action=%u text='%s'",
                         i, j, action_id, text);
                continue;
            }
            if (j != 3 || !payload_readable(inner[j], 4 * sizeof(void*))) continue;
            void* const* data = reinterpret_cast<void* const*>(inner[j]);
            log_line("[FUT-NAV] payload.w%d.data action=%u at=0x%llx {%llx,%llx,%llx,%llx}",
                     i, action_id,
                     (unsigned long long)reinterpret_cast<uintptr_t>(inner[j]),
                     (unsigned long long)reinterpret_cast<uintptr_t>(data[0]),
                     (unsigned long long)reinterpret_cast<uintptr_t>(data[1]),
                     (unsigned long long)reinterpret_cast<uintptr_t>(data[2]),
                     (unsigned long long)reinterpret_cast<uintptr_t>(data[3]));
            if (payload_read_text(inner[j], text, sizeof(text)) &&
                !payload_text_is_allocator_tag(text)) {
                log_line("[FUT-NAV] payload.w%d.data action=%u inline='%s'",
                         i, action_id, text);
            }
            for (int k = 0; k < 4; ++k) {
                if (payload_read_text(data[k], text, sizeof(text)) &&
                    !payload_text_is_allocator_tag(text)) {
                    log_line("[FUT-NAV] payload.w%d.data.f%d action=%u text='%s'",
                             i, k, action_id, text);
                }
            }
        }
    }
}

uintptr_t __fastcall fut_view_manager_process_action_probe(
    void* manager, uint32_t action_id, void* action_payload) {
    const unsigned long long sequence =
        g_fut_action_trace_sequence.fetch_add(1, std::memory_order_relaxed) + 1;
    const DWORD thread_id = GetCurrentThreadId();
    void* caller = _ReturnAddress();
    HMODULE module = GetModuleHandleW(nullptr);
    uintptr_t caller_rva = 0;
    if (module != nullptr) {
        const uintptr_t base = reinterpret_cast<uintptr_t>(module);
        const uintptr_t address = reinterpret_cast<uintptr_t>(caller);
        if (address >= base) caller_rva = address - base;
    }
    char payload_text[192];
    describe_action_payload(action_payload, payload_text, sizeof(payload_text));
    if (action_id == 30004 && strstr(payload_text, "{\"squad\":[") != nullptr) {
        g_squad_input_capture_until.store(
            GetTickCount64() + 10 * 60 * 1000, std::memory_order_release);
        log_line("[SQUAD-INPUT] capture armed by squad-list payload");
    } else if (action_id == 30051) {
        g_squad_input_capture_until.store(0, std::memory_order_release);
        log_line("[SQUAD-INPUT] capture disarmed by FUT widget unload");
    }
    if (action_id == kFutGateProfilerAction) request_futdb_watch_from_gate();

    log_line(
        "[FUT-NAV] seq=%llu tid=%lu ProcessAction action=%u name='%s' payloadText='%s' "
        "payload=0x%llx manager=0x%llx caller=0x%llx callerRva=0x%llx",
        sequence, thread_id, action_id, fut_named_id(action_id), payload_text,
        (unsigned long long)reinterpret_cast<uintptr_t>(action_payload),
        (unsigned long long)reinterpret_cast<uintptr_t>(manager),
        (unsigned long long)reinterpret_cast<uintptr_t>(caller),
        (unsigned long long)caller_rva);
    if (payload_readable(action_payload, 8 * sizeof(void*))) {
        void* const* words = reinterpret_cast<void* const*>(action_payload);
        log_line("[FUT-NAV] payload words={%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx}",
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[0]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[1]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[2]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[3]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[4]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[5]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[6]),
                 (unsigned long long)reinterpret_cast<uintptr_t>(words[7]));
    }
    log_apt_value_vector(action_id, action_payload);
    log_payload_fields(action_id, action_payload);
    log_squad_action_payload("process", sequence, action_id, action_payload);
    if (action_id == kFutNavAdvanceAction) {
        capture_fut_runtime_callsite("process-action-advance", caller);
    } else if (action_id == 3113) {
        capture_fut_runtime_callsite("process-action-3113", caller);
    } else if (action_id == kFutSquadNameAction) {
        capture_fut_runtime_callsite("process-action-30003", caller);
    }
    if (g_fut_view_manager_process_action_original == nullptr) return 0;
    return g_fut_view_manager_process_action_original(
        manager, action_id, action_payload);
}

void log_fut_apt_action_context(
    uint32_t action_id, void* caller, void* apt_payload,
    unsigned long long sequence) {
    if (action_id != kFutNavAdvanceAction && action_id != 3113 &&
        action_id != kFutSquadNameAction) return;

    void* frames[10] = {0};
    USHORT frame_count = CaptureStackBackTrace(0, 10, frames, nullptr);
    HMODULE module = GetModuleHandleW(nullptr);
    const uintptr_t base = reinterpret_cast<uintptr_t>(module);
    for (USHORT i = 0; i < frame_count; ++i) {
        const uintptr_t address = reinterpret_cast<uintptr_t>(frames[i]);
        const uintptr_t rva = address >= base ? address - base : 0;
        log_line(
            "[FUT-APT] seq=%llu tid=%lu action=%u stack[%u]=0x%llx rva=0x%llx",
            sequence, GetCurrentThreadId(), action_id, i,
            (unsigned long long)address,
            (unsigned long long)rva);
    }

    uintptr_t words[8] = {0};
    bool readable = false;
    __try {
        if (apt_payload != nullptr) {
            memcpy(words, apt_payload, sizeof(words));
            readable = true;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        readable = false;
    }
    if (readable) {
        log_line(
            "[FUT-APT] seq=%llu tid=%lu action=%u sourcePayload=0x%llx words="
            "{%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx}",
            sequence, GetCurrentThreadId(), action_id,
            (unsigned long long)reinterpret_cast<uintptr_t>(apt_payload),
            (unsigned long long)words[0], (unsigned long long)words[1],
            (unsigned long long)words[2], (unsigned long long)words[3],
            (unsigned long long)words[4], (unsigned long long)words[5],
            (unsigned long long)words[6], (unsigned long long)words[7]);
    } else {
        log_line(
            "[FUT-APT] seq=%llu tid=%lu action=%u sourcePayload=0x%llx "
            "unreadable-or-null",
            sequence, GetCurrentThreadId(), action_id,
            (unsigned long long)reinterpret_cast<uintptr_t>(apt_payload));
    }

    const char* label = action_id == kFutNavAdvanceAction
                            ? "apt-action-advance"
                            : (action_id == kFutSquadNameAction
                                   ? "apt-action-30003"
                                   : "apt-action-3113");
    capture_fut_runtime_callsite(label, caller);
}

void log_flux_apt_stack(const char* phase, void* interpreter) {
    int32_t count = -1;
    int32_t capacity = -1;
    void** values = nullptr;
    __try {
        if (interpreter != nullptr) {
            const auto* bytes = reinterpret_cast<const unsigned char*>(interpreter);
            count = *reinterpret_cast<const int32_t*>(bytes);
            capacity = *reinterpret_cast<const int32_t*>(bytes + 4);
            values = *reinterpret_cast<void***>(
                const_cast<unsigned char*>(bytes) + 8);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        count = capacity = -1;
        values = nullptr;
    }

    log_line(
        "[FUT-APT-LOADMOVIE] %s interpreter=0x%llx count=%d capacity=%d "
        "values=0x%llx",
        phase,
        (unsigned long long)reinterpret_cast<uintptr_t>(interpreter), count,
        capacity, (unsigned long long)reinterpret_cast<uintptr_t>(values));
    if (count <= 0 || count > 0x10000 || capacity < count ||
        !payload_readable(values, static_cast<size_t>(count) * sizeof(void*))) {
        return;
    }

    const int captured = count < 6 ? count : 6;
    for (int depth = 0; depth < captured; ++depth) {
        void* object = values[count - 1 - depth];
        uintptr_t words[8] = {};
        bool readable = false;
        __try {
            if (object != nullptr) {
                memcpy(words, object, sizeof(words));
                readable = true;
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            readable = false;
        }
        log_line(
            "[FUT-APT-LOADMOVIE] %s top-%d object=0x%llx readable=%u "
            "words={%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx}",
            phase, depth,
            (unsigned long long)reinterpret_cast<uintptr_t>(object),
            readable ? 1u : 0u,
            (unsigned long long)words[0], (unsigned long long)words[1],
            (unsigned long long)words[2], (unsigned long long)words[3],
            (unsigned long long)words[4], (unsigned long long)words[5],
            (unsigned long long)words[6], (unsigned long long)words[7]);
    }
}

void __fastcall flux_apt_method_probe(
    void* interpreter, void** instruction_cursor) {
    uintptr_t cursor = 0;
    __try {
        if (instruction_cursor != nullptr) {
            cursor = reinterpret_cast<uintptr_t>(*instruction_cursor);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        cursor = 0;
    }
    const bool is_load_movie =
        cursor != 0 &&
        cursor == g_flux_load_movie_operand.load(std::memory_order_acquire);
    if (is_load_movie) {
        log_line(
            "[FUT-APT-LOADMOVIE] shared method dispatcher entered "
            "cursor=0x%llx thread=%lu",
            (unsigned long long)cursor, GetCurrentThreadId());
        log_flux_apt_stack("before", interpreter);
    }

    if (is_load_movie) ++g_flux_load_movie_dispatch_depth;
    if (g_flux_apt_method_original != nullptr) {
        g_flux_apt_method_original(interpreter, instruction_cursor);
    }
    if (is_load_movie && g_flux_load_movie_dispatch_depth != 0) {
        --g_flux_load_movie_dispatch_depth;
    }

    if (is_load_movie) {
        log_flux_apt_stack("after", interpreter);
        log_line("[FUT-APT-LOADMOVIE] shared method dispatcher returned normally");

        bool expected = false;
        if (g_flux_callable_dispatch_dumped.compare_exchange_strong(
                expected, true, std::memory_order_acq_rel)) {
            HMODULE module = GetModuleHandleW(nullptr);
            if (module != nullptr) {
                constexpr uintptr_t kCallableDispatchRva = 0x77e08f0;
                dump_va_window(
                    reinterpret_cast<uintptr_t>(module) + kCallableDispatchRva,
                    0x20000, 0x20000,
                    L"fifa17-revival-apt-callable-dispatch.bin",
                    "FUT-APT-LOADMOVIE", "callable-dispatch");
            }
        }
    }
}

void __fastcall transfer_pile_get_member_probe(void* interpreter) {
    bool is_transfer_pile_size = false;
    __try {
        auto* vm = reinterpret_cast<unsigned char*>(interpreter);
        const int32_t count = *reinterpret_cast<int32_t*>(vm);
        auto** values = *reinterpret_cast<unsigned char***>(vm + 8);
        if (count > 0 && values != nullptr) {
            unsigned char* member_value = values[count - 1];
            const uint32_t flags =
                *reinterpret_cast<uint32_t*>(member_value + 8);
            constexpr uint32_t kStringType = 1;
            if ((flags >> 25) == kStringType) {
                unsigned char* string_record =
                    *reinterpret_cast<unsigned char**>(member_value + 0x10);
                constexpr char kMember[] = "TRADE_PILE_SIZE";
                constexpr uint16_t kMemberLength =
                    static_cast<uint16_t>(sizeof(kMember) - 1);
                if (string_record != nullptr &&
                    *reinterpret_cast<uint16_t*>(string_record + 2) ==
                        kMemberLength &&
                    memcmp(string_record + 8, kMember, kMemberLength) == 0) {
                    is_transfer_pile_size = true;
                }
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        is_transfer_pile_size = false;
    }

    if (g_transfer_pile_get_member_original != nullptr) {
        g_transfer_pile_get_member_original(interpreter);
    }
    if (!is_transfer_pile_size) return;

    __try {
        auto* vm = reinterpret_cast<unsigned char*>(interpreter);
        const int32_t count = *reinterpret_cast<int32_t*>(vm);
        auto** values = *reinterpret_cast<unsigned char***>(vm + 8);
        if (count <= 0 || values == nullptr) return;
        unsigned char* result = values[count - 1];
        const uint32_t flags = *reinterpret_cast<uint32_t*>(result + 8);
        constexpr uint32_t kIntegerType = 7;
        auto* payload = reinterpret_cast<int32_t*>(result + 0x10);
        if ((flags >> 25) != kIntegerType || *payload != 0) return;

        constexpr int32_t kFallbackCapacity = 100;
        *payload = kFallbackCapacity;
        const uint32_t hit = g_transfer_pile_capacity_hits.fetch_add(
                                 1, std::memory_order_relaxed) + 1;
        if (hit <= 4 || hit % 25 == 0) {
            log_line(
                "[FUT-PILE-SIZE] corrected TRADE_PILE_SIZE 0 -> %d "
                "(hit=%u)",
                kFallbackCapacity, hit);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        static std::atomic<bool> logged{false};
        if (!logged.exchange(true)) {
            log_line(
                "[FUT-PILE-SIZE] exact member matched but its result was "
                "unreadable; leaving it unchanged");
        }
    }
}

void log_flux_apt_object(const char* label, void* object) {
    uintptr_t words[12] = {};
    bool readable = false;
    __try {
        if (object != nullptr) {
            memcpy(words, object, sizeof(words));
            readable = true;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        readable = false;
    }
    log_line(
        "[FUT-APT-CALLABLE] %s=0x%llx readable=%u words="
        "{%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx,%llx}",
        label, (unsigned long long)reinterpret_cast<uintptr_t>(object),
        readable ? 1u : 0u,
        (unsigned long long)words[0], (unsigned long long)words[1],
        (unsigned long long)words[2], (unsigned long long)words[3],
        (unsigned long long)words[4], (unsigned long long)words[5],
        (unsigned long long)words[6], (unsigned long long)words[7],
        (unsigned long long)words[8], (unsigned long long)words[9],
        (unsigned long long)words[10], (unsigned long long)words[11]);
}

void __fastcall flux_apt_callable_probe(
    void* interpreter, void* receiver, void* callable, uint32_t argument_count,
    void* call_context, void* result_target, bool preserve_result) {
    const bool capture = g_flux_load_movie_dispatch_depth != 0 &&
                         g_flux_callable_capture_count < 32;
    const unsigned sequence = capture ? ++g_flux_callable_capture_count : 0;
    if (capture) {
        uintptr_t vtable = 0;
        uintptr_t invoke_88 = 0;
        uint32_t type_flags = 0;
        __try {
            if (callable != nullptr) {
                vtable = *reinterpret_cast<const uintptr_t*>(callable);
                type_flags = *reinterpret_cast<const uint32_t*>(
                    reinterpret_cast<const unsigned char*>(callable) + 8);
                if (vtable != 0) {
                    invoke_88 = *reinterpret_cast<const uintptr_t*>(vtable + 0x88);
                }
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            vtable = invoke_88 = 0;
            type_flags = 0;
        }
        const int apt_type = static_cast<int32_t>(type_flags) >> 25;
        log_line(
            "[FUT-APT-CALLABLE] entered sequence=%u argc=%u type=%d "
            "flags=0x%08x callable=0x%llx vtable=0x%llx invoke+0x88=0x%llx "
            "receiver=0x%llx context=0x%llx resultTarget=0x%llx preserve=%u",
            sequence, argument_count, apt_type, type_flags,
            (unsigned long long)reinterpret_cast<uintptr_t>(callable),
            (unsigned long long)vtable, (unsigned long long)invoke_88,
            (unsigned long long)reinterpret_cast<uintptr_t>(receiver),
            (unsigned long long)reinterpret_cast<uintptr_t>(call_context),
            (unsigned long long)reinterpret_cast<uintptr_t>(result_target),
            preserve_result ? 1u : 0u);
        log_flux_apt_object("callable", callable);
        log_flux_apt_object("receiver", receiver);
        log_flux_apt_stack("callable-before", interpreter);
    }

    if (g_flux_apt_callable_original != nullptr) {
        g_flux_apt_callable_original(
            interpreter, receiver, callable, argument_count, call_context,
            result_target, preserve_result);
    }

    if (capture) {
        log_flux_apt_stack("callable-after", interpreter);
        log_line("[FUT-APT-CALLABLE] returned sequence=%u", sequence);
    }
}

bool copy_flux_internal_string(
    void** holder, uintptr_t* block_address, char* output, size_t capacity) {
    if (block_address != nullptr) *block_address = 0;
    if (output == nullptr || capacity == 0) return false;
    output[0] = '\0';
    void* block = nullptr;
    __try {
        if (holder != nullptr) block = *holder;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
    if (block_address != nullptr) {
        *block_address = reinterpret_cast<uintptr_t>(block);
    }
    if (block == nullptr) return false;
    return payload_read_ascii(
               reinterpret_cast<const unsigned char*>(block) + 8,
               output, capacity) != 0;
}

void log_flux_movie_path(const char* stage, void** holder) {
    uintptr_t block = 0;
    char path[320] = {0};
    const bool readable =
        copy_flux_internal_string(holder, &block, path, sizeof(path));
    log_line(
        "[FUT-MOVIE-PATH] %s holder=0x%llx block=0x%llx readable=%u path='%s'",
        stage, (unsigned long long)reinterpret_cast<uintptr_t>(holder),
        (unsigned long long)block, readable ? 1u : 0u, path);
}

uintptr_t __fastcall flux_apt_resolve_path_probe(
    void* receiver, void** path_holder, uint32_t mode) {
    const bool capture = g_flux_load_movie_dispatch_depth != 0;
    if (capture) {
        log_line(
            "[FUT-MOVIE-PATH] resolver entered receiver=0x%llx mode=%u",
            (unsigned long long)reinterpret_cast<uintptr_t>(receiver), mode);
        log_flux_movie_path("resolver-before", path_holder);
        log_flux_apt_object("resolver-receiver-before", receiver);
    }
    uintptr_t result = 0;
    if (g_flux_apt_resolve_path_original != nullptr) {
        result = g_flux_apt_resolve_path_original(receiver, path_holder, mode);
    }
    if (capture) {
        log_flux_movie_path("resolver-after", path_holder);
        log_flux_apt_object("resolver-receiver-after", receiver);
        log_line("[FUT-MOVIE-PATH] resolver returned rax=0x%llx",
                 (unsigned long long)result);
    }
    return result;
}

uintptr_t __fastcall flux_apt_load_dispatch_probe(
    void* manager, void** original_path_holder, void** resolved_path_holder,
    void* callback) {
    const bool capture = g_flux_load_movie_dispatch_depth != 0;
    if (capture) {
        log_line(
            "[FUT-MOVIE-LOAD] dispatch entered manager=0x%llx callback=0x%llx",
            (unsigned long long)reinterpret_cast<uintptr_t>(manager),
            (unsigned long long)reinterpret_cast<uintptr_t>(callback));
        log_flux_movie_path("dispatch-original", original_path_holder);
        log_flux_movie_path("dispatch-resolved", resolved_path_holder);
        log_flux_apt_object("dispatch-manager-before", manager);
    }
    uintptr_t result = 0;
    if (g_flux_apt_load_dispatch_original != nullptr) {
        result = g_flux_apt_load_dispatch_original(
            manager, original_path_holder, resolved_path_holder, callback);
    }
    if (capture) {
        log_flux_movie_path("dispatch-original-after", original_path_holder);
        log_flux_movie_path("dispatch-resolved-after", resolved_path_holder);
        log_flux_apt_object("dispatch-manager-after", manager);
        log_line("[FUT-MOVIE-LOAD] dispatch returned rax=0x%llx",
                 (unsigned long long)result);
    }
    return result;
}

void __fastcall fut_apt_call_method_pop_probe(
    void* interpreter, uint32_t opcode, void* operation) {
    constexpr uint32_t kCaptureLimit = 4096;
    const uint32_t sequence =
        g_fut_apt_vm_probe_count.fetch_add(1, std::memory_order_relaxed) + 1;

    if (sequence <= kCaptureLimit) {
        uintptr_t operation_words[4] = {};
        uintptr_t stack_words[12] = {};
        void* vm_state = nullptr;
        int32_t top = INT32_MIN;
        unsigned alternate = 0;
        unsigned captured = 0;
        __try {
            if (operation != nullptr) {
                memcpy(operation_words, operation, sizeof(operation_words));
            }

            HMODULE module = GetModuleHandleW(nullptr);
            auto getter = reinterpret_cast<FutAptVmStateGetter>(
                reinterpret_cast<uintptr_t>(module) + kFutAptVmStateGetterRva);
            vm_state = getter();
            if (vm_state != nullptr) {
                auto* bytes = reinterpret_cast<const unsigned char*>(vm_state);
                alternate = bytes[8] != 0 ? 1u : 0u;
                const uintptr_t index_offset = alternate ? 0x2c50 : 0x1560;
                const uintptr_t values_offset = alternate ? 0x2c58 : 0x1568;
                top = *reinterpret_cast<const int32_t*>(bytes + index_offset);
                if (top >= 0 && top < 0x10000) {
                    for (int i = 0; i < 6 && top - i >= 0; ++i) {
                        const auto* entry = reinterpret_cast<const uintptr_t*>(
                            bytes + values_offset +
                            static_cast<uintptr_t>(top - i) * 16);
                        stack_words[i * 2] = entry[0];
                        stack_words[i * 2 + 1] = entry[1];
                        captured++;
                    }
                }
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            captured = 0;
        }

        log_line(
            "[APT-VM] #%u opcode=0x%x interpreter=0x%llx operation=0x%llx "
            "op={%llx,%llx,%llx,%llx} vm=0x%llx alternate=%u top=%d "
            "captured=%u stack="
            "{%llx/%llx,%llx/%llx,%llx/%llx,%llx/%llx,%llx/%llx,%llx/%llx}",
            sequence, opcode,
            (unsigned long long)reinterpret_cast<uintptr_t>(interpreter),
            (unsigned long long)reinterpret_cast<uintptr_t>(operation),
            (unsigned long long)operation_words[0],
            (unsigned long long)operation_words[1],
            (unsigned long long)operation_words[2],
            (unsigned long long)operation_words[3],
            (unsigned long long)reinterpret_cast<uintptr_t>(vm_state),
            alternate, top, captured,
            (unsigned long long)stack_words[0],
            (unsigned long long)stack_words[1],
            (unsigned long long)stack_words[2],
            (unsigned long long)stack_words[3],
            (unsigned long long)stack_words[4],
            (unsigned long long)stack_words[5],
            (unsigned long long)stack_words[6],
            (unsigned long long)stack_words[7],
            (unsigned long long)stack_words[8],
            (unsigned long long)stack_words[9],
            (unsigned long long)stack_words[10],
            (unsigned long long)stack_words[11]);
    } else if (sequence == kCaptureLimit + 1) {
        log_line("[APT-VM] capture limit reached at %u calls", kCaptureLimit);
    }

    if (g_fut_apt_call_method_pop_original != nullptr) {
        g_fut_apt_call_method_pop_original(interpreter, opcode, operation);
    }
}

void __fastcall fut_apt_action_bridge_probe(
    void* manager, uint32_t action_id, void* apt_payload) {
    const unsigned long long sequence =
        g_fut_action_trace_sequence.fetch_add(1, std::memory_order_relaxed) + 1;
    const DWORD thread_id = GetCurrentThreadId();
    void* caller = _ReturnAddress();
    HMODULE module = GetModuleHandleW(nullptr);
    const uintptr_t base = reinterpret_cast<uintptr_t>(module);
    const uintptr_t address = reinterpret_cast<uintptr_t>(caller);
    const uintptr_t caller_rva = address >= base ? address - base : 0;
    char payload_text[192];
    describe_action_payload(apt_payload, payload_text, sizeof(payload_text));
    log_line(
        "[FUT-APT] seq=%llu tid=%lu bridge action=%u name='%s' payloadText='%s' manager=0x%llx "
        "sourcePayload=0x%llx caller=0x%llx callerRva=0x%llx",
        sequence, thread_id, action_id, fut_nav_action_name(action_id), payload_text,
        (unsigned long long)reinterpret_cast<uintptr_t>(manager),
        (unsigned long long)reinterpret_cast<uintptr_t>(apt_payload),
        (unsigned long long)address, (unsigned long long)caller_rva);
    if (manager != nullptr) {
        void* previous = g_fut_apt_manager.exchange(manager);
        if (g_fut_force_profile_advance_enabled.load() && previous != manager) {
            log_line(
                "[FUT-FORCE] captured APT manager=0x%llx from action=%u",
                (unsigned long long)reinterpret_cast<uintptr_t>(manager),
                action_id);
        }
    }
    log_squad_action_payload("bridge", sequence, action_id, apt_payload);
    log_fut_apt_action_context(action_id, caller, apt_payload, sequence);
    if (g_fut_apt_action_bridge_original != nullptr) {
        g_fut_apt_action_bridge_original(manager, action_id, apt_payload);
    }
}

uintptr_t __fastcall fut_login_flow_handler_probe(
    void* owner, uint32_t event_id, void* payload) {
    unsigned state_18d = 0;
    unsigned state_18e = 0;
    unsigned state_18f = 0;
    unsigned state_190 = 0;
    __try {
        if (owner != nullptr) {
            const auto* bytes = reinterpret_cast<const unsigned char*>(owner);
            state_18d = bytes[0x18d];
            state_18e = bytes[0x18e];
            state_18f = bytes[0x18f];
            state_190 = bytes[0x190];
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        state_18d = state_18e = state_18f = state_190 = 0xff;
    }
    log_line(
        "[FUT-LOGIN-FLOW] entered id=0x%x (%u)%s owner=0x%llx "
        "payload=0x%llx state={18d:%u,18e:%u,18f:%u,190:%u}",
        event_id, event_id,
        event_id == kFutLoginFlowTriggerEvent ? " <== 0x27A0 trigger" : "",
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(payload),
        state_18d, state_18e, state_18f, state_190);

    uintptr_t result = 0;
    if (g_fut_login_flow_handler_original != nullptr) {
        result = g_fut_login_flow_handler_original(owner, event_id, payload);
    }

    __try {
        if (owner != nullptr) {
            const auto* bytes = reinterpret_cast<const unsigned char*>(owner);
            state_18d = bytes[0x18d];
            state_18e = bytes[0x18e];
            state_18f = bytes[0x18f];
            state_190 = bytes[0x190];
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        state_18d = state_18e = state_18f = state_190 = 0xff;
    }
    log_line(
        "[FUT-LOGIN-FLOW] returned id=0x%x result=0x%llx "
        "state={18d:%u,18e:%u,18f:%u,190:%u}",
        event_id, (unsigned long long)result,
        state_18d, state_18e, state_18f, state_190);
    return result;
}

uintptr_t __fastcall fut_ui_list_handler_probe(
    void* handler, uint32_t event_id, void* payload_list) {
    uintptr_t begin = 0;
    uintptr_t end = 0;
    uintptr_t capacity = 0;
    __try {
        if (payload_list != nullptr) {
            auto* words = reinterpret_cast<uintptr_t*>(payload_list);
            begin = words[0];
            end = words[1];
            capacity = words[2];
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        begin = end = capacity = 0;
    }
    size_t count = 0;
    if (begin != 0 && end >= begin && end - begin <= 0x10000) {
        count = (end - begin) / sizeof(uintptr_t);
    }
    log_line(
        "[FUT-HANDLER] list method entered id=0x%x handler=0x%llx "
        "list=0x%llx begin=0x%llx end=0x%llx capacity=0x%llx count=%zu",
        event_id, (unsigned long long)reinterpret_cast<uintptr_t>(handler),
        (unsigned long long)reinterpret_cast<uintptr_t>(payload_list),
        (unsigned long long)begin, (unsigned long long)end,
        (unsigned long long)capacity, count);
    uintptr_t result = 0;
    if (g_fut_ui_list_handler_original != nullptr) {
        result = g_fut_ui_list_handler_original(handler, event_id, payload_list);
    }
    log_line("[FUT-HANDLER] list method returned id=0x%x result=0x%llx",
             event_id, (unsigned long long)result);
    return result;
}

bool install_fut_ui_list_handler_probe(void* handler) {
    if (handler == nullptr || g_fut_ui_list_handler_installed.load()) return false;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(handler, mbi)) return false;
    uintptr_t table = *reinterpret_cast<uintptr_t*>(handler);
    if (table == 0 || !region_ok(reinterpret_cast<void*>(table + 0x20), mbi)) {
        return false;
    }
    auto* slot = reinterpret_cast<uintptr_t*>(table + 0x18);
    uintptr_t original = *slot;
    if (original == 0 || original == reinterpret_cast<uintptr_t>(&fut_ui_list_handler_probe)) {
        return false;
    }

    uintptr_t entries[5] = {0};
    __try {
        for (size_t i = 0; i < 5; ++i) {
            entries[i] = *reinterpret_cast<uintptr_t*>(table + i * 8);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        memset(entries, 0, sizeof(entries));
    }
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    log_line(
        "[FUT-HANDLER] table=0x%llx methods={0x%llx,0x%llx,0x%llx,0x%llx,0x%llx} "
        "listMethodRva=0x%llx",
        (unsigned long long)table,
        (unsigned long long)entries[0], (unsigned long long)entries[1],
        (unsigned long long)entries[2], (unsigned long long)entries[3],
        (unsigned long long)entries[4],
        (unsigned long long)(original >= base ? original - base : original));
    dump_va_window(original, 0x20000, 0x20000,
                   L"fifa17-revival-ui-list-handler.bin", "FUT-HANDLER",
                   "ui-list-handler");

    g_fut_ui_list_handler_original = reinterpret_cast<FutUiListHandler>(original);
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_ui_list_handler_probe);
    if (!write_code(reinterpret_cast<unsigned char*>(slot),
                    reinterpret_cast<const unsigned char*>(&hook), sizeof(hook))) {
        g_fut_ui_list_handler_original = nullptr;
        return false;
    }
    g_fut_ui_list_handler_installed.store(true);
    log_line("[FUT-HANDLER] list-method hook installed slot=0x%llx original=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(slot),
             (unsigned long long)original);
    return true;
}

void* __fastcall fut_ui_event_dispatcher_probe(void* owner, uint32_t event_id) {
    void* caller = _ReturnAddress();
    capture_fut_runtime_callsite("ui-event", caller);
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    const unsigned valid = *reinterpret_cast<unsigned char*>(base + kFutValidClubRva);
    const unsigned complete = *reinterpret_cast<uint32_t*>(base + kFutCompletionRva);
    const unsigned ready = *reinterpret_cast<unsigned char*>(base + kFutDataReadyRva);
    log_line(
        "[FUT-EVENT] dispatch entered id=0x%x (%u) [%s] owner=0x%llx caller=0x%llx "
        "validClub=%u completion=%u dataReady=%u",
        event_id, event_id, fut_named_id(event_id),
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(caller), valid, complete,
        ready);
    void* result = nullptr;
    if (g_fut_ui_event_dispatcher_original != nullptr) {
        result = g_fut_ui_event_dispatcher_original(owner, event_id);
    }
    uintptr_t vtable = 0;
    uintptr_t list_method = 0;
    uintptr_t payload_method = 0;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (result != nullptr && region_ok(result, mbi)) {
        vtable = *reinterpret_cast<const uintptr_t*>(result);
        if (vtable != 0 && region_ok(reinterpret_cast<const void*>(vtable + 0x20), mbi)) {
            list_method = *reinterpret_cast<const uintptr_t*>(vtable + 0x18);
            payload_method = *reinterpret_cast<const uintptr_t*>(vtable + 0x20);
        }
    }
    if (event_id == 0x9c97 && result != nullptr) {
        install_fut_ui_list_handler_probe(result);
    }
    if (event_id == 0x2763 && g_fut_ui_model_publish_original == nullptr) {
        install_fut_ui_model_publish_probe(GetModuleHandleW(nullptr));
    }
    log_line(
        "[FUT-EVENT] dispatch returned id=0x%x result=0x%llx table=0x%llx "
        "listMethod=0x%llx payloadMethod=0x%llx",
        event_id, (unsigned long long)reinterpret_cast<uintptr_t>(result),
        (unsigned long long)vtable, (unsigned long long)list_method,
        (unsigned long long)payload_method);
    return result;
}

uintptr_t __fastcall fut_ui_model_publish_probe(
    void* model, uint32_t event_id, void* payload) {
    log_line(
        "[FUT-MODEL] PublishToObject entered id=0x%x [%s] model=0x%llx payload=0x%llx",
        event_id, fut_named_id(event_id),
        (unsigned long long)reinterpret_cast<uintptr_t>(model),
        (unsigned long long)reinterpret_cast<uintptr_t>(payload));
    uintptr_t result = 0;
    if (g_fut_ui_model_publish_original != nullptr) {
        result = g_fut_ui_model_publish_original(model, event_id, payload);
    }
    log_line("[FUT-MODEL] PublishToObject returned id=0x%x result=0x%llx",
             event_id, (unsigned long long)result);

    if (event_id == 0x2763 && result != 0 &&
        g_fut_profile_state_consumed.load()) {
        g_fut_profile_publish_succeeded.store(true);
    }
    return result;
}

uintptr_t __fastcall fut_script_publish_bridge_probe(
    void* context, void* namespace_name, void* function_name, void* payload,
    void* resolved_event) {
    const uint32_t sequence =
        g_fut_script_publish_probe_count.fetch_add(1) + 1;
    void* caller = _ReturnAddress();
    log_line(
        "[FUT-SCRIPT] bridge #%u event=0x2763 context=0x%llx "
        "namespace=0x%llx function=0x%llx payload=0x%llx "
        "resolved=0x%llx caller=0x%llx",
        sequence,
        (unsigned long long)reinterpret_cast<uintptr_t>(context),
        (unsigned long long)reinterpret_cast<uintptr_t>(namespace_name),
        (unsigned long long)reinterpret_cast<uintptr_t>(function_name),
        (unsigned long long)reinterpret_cast<uintptr_t>(payload),
        (unsigned long long)reinterpret_cast<uintptr_t>(resolved_event),
        (unsigned long long)reinterpret_cast<uintptr_t>(caller));
    const uintptr_t result = g_fut_script_publish_bridge_original(
        context, namespace_name, function_name, payload, resolved_event);
    log_line("[FUT-SCRIPT] bridge #%u returned result=0x%llx", sequence,
             (unsigned long long)result);
    return result;
}

uintptr_t __fastcall fut_phase_handler_probe(void* object) {
    void* caller = _ReturnAddress();
    auto* bytes = reinterpret_cast<unsigned char*>(object);
    uint32_t phase = 0xFFFFFFFF;
    unsigned busy = 0;
    unsigned pending = 0;
    MEMORY_BASIC_INFORMATION mbi;
    const bool readable = object != nullptr && region_ok(object, mbi);
    if (readable) {
        memcpy(&phase, bytes + kFutPhaseFieldOffset, sizeof(phase));
        busy = bytes[kFutPhaseBusyOffset];
        pending = bytes[kFutPhasePendingOffset];
    }
    log_line(
        "[FUT-PHASE] entered object=0x%llx phase=%u busy=%u pending=%u "
        "caller=0x%llx (RVA 0x%llx)",
        (unsigned long long)reinterpret_cast<uintptr_t>(object), phase, busy,
        pending, (unsigned long long)reinterpret_cast<uintptr_t>(caller),
        (unsigned long long)(reinterpret_cast<uintptr_t>(caller) -
                             reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr))));

    uintptr_t result = 0;
    if (g_fut_phase_handler_original != nullptr) {
        result = g_fut_phase_handler_original(object);
    }

    uint32_t phase_after = 0xFFFFFFFF;
    unsigned busy_after = 0;
    unsigned pending_after = 0;
    if (readable) {
        memcpy(&phase_after, bytes + kFutPhaseFieldOffset, sizeof(phase_after));
        busy_after = bytes[kFutPhaseBusyOffset];
        pending_after = bytes[kFutPhasePendingOffset];
    }
    log_line(
        "[FUT-PHASE] returned phase=%u busy=%u pending=%u result=0x%llx",
        phase_after, busy_after, pending_after, (unsigned long long)result);
    return result;
}

uintptr_t __fastcall fut_club_submit_probe(void* owner, void* argument) {
    void* caller = _ReturnAddress();
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto frontend_ready_fn =
        reinterpret_cast<FutReadinessPredicate>(base + kFutFrontendReadyRva);
    auto online_ready_fn =
        reinterpret_cast<FutReadinessPredicate>(base + kFutOnlineReadyRva);
    const bool frontend_ready = frontend_ready_fn();
    const bool online_ready = frontend_ready && online_ready_fn();

    log_line(
        "[FUT-SUBMIT] users/club submit entered owner=0x%llx argument=0x%llx "
        "frontendReady=%u onlineReady=%u caller=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(argument),
        frontend_ready ? 1u : 0u, online_ready ? 1u : 0u,
        (unsigned long long)reinterpret_cast<uintptr_t>(caller));
    if (!frontend_ready || !online_ready) {
        log_line("[FUT-SUBMIT] gated: %s returned false, so no users/club "
                 "request will be built",
                 !frontend_ready ? "the frontend predicate" : "the online predicate");
    }

    uintptr_t result = 0;
    if (g_fut_club_submit_original != nullptr) {
        result = g_fut_club_submit_original(owner, argument);
    }
    log_line("[FUT-SUBMIT] users/club submit returned result=0x%llx",
             (unsigned long long)result);
    return result;
}

uintptr_t __fastcall fut_club_url_builder_probe(
    void* context, void* output, int32_t argument) {
    void* caller = _ReturnAddress();
    log_line(
        "[FUT-URL] users/club builder entered context=0x%llx output=0x%llx "
        "argument=%d caller=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(context),
        (unsigned long long)reinterpret_cast<uintptr_t>(output), argument,
        (unsigned long long)reinterpret_cast<uintptr_t>(caller));
    uintptr_t result = 0;
    if (g_fut_club_url_builder_original != nullptr) {
        result = g_fut_club_url_builder_original(context, output, argument);
    }
    log_line("[FUT-URL] users/club builder returned result=0x%llx",
             (unsigned long long)result);
    return result;
}

void __fastcall fut_save_decoder_probe(void* owner, void* operation) {
    uint32_t kind = 0;
    uint32_t type = 0;
    uintptr_t source = 0;
    unsigned mode = 0;
    unsigned cleanup = 0;
    __try {
        if (operation != nullptr) {
            const auto* bytes = reinterpret_cast<const unsigned char*>(operation);
            memcpy(&kind, bytes + 0x08, sizeof(kind));
            memcpy(&type, bytes + 0x0c, sizeof(type));
            memcpy(&source, bytes + 0x38, sizeof(source));
            mode = bytes[0x78];
            cleanup = bytes[0x7c];
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        kind = type = 0;
        source = 0;
        mode = cleanup = 0;
    }

    log_line(
        "[FUT-SAVE] decoder entered owner=0x%llx operation=0x%llx "
        "kind=0x%x type=0x%x source=0x%llx mode=%u cleanup=%u",
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(operation), kind, type,
        (unsigned long long)source, mode, cleanup);

    static std::atomic<bool> event_bus_dumped{false};
    bool expected = false;
    if (event_bus_dumped.compare_exchange_strong(expected, true)) {
        auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
        dump_va_window(base + 0x53b2a10, 0x20000, 0x20000,
                       L"fifa17-revival-event-bus.bin", "FUT-SAVE",
                       "completion-event-bus");
    }

    ULONGLONG started = GetTickCount64();
    if (g_fut_save_decoder_original != nullptr) {
        g_fut_save_decoder_original(owner, operation);
    }
    log_line("[FUT-SAVE] decoder returned elapsedMs=%llu",
             (unsigned long long)(GetTickCount64() - started));
}

void __fastcall fut_registration_probe(void* owner, FutParserCallback callback) {
    void* registration_caller = _ReturnAddress();
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto** downstream_slot = reinterpret_cast<void**>(
        base + kFutDownstreamCallbackRva);
    void* frontend_owner = *reinterpret_cast<void**>(base + kFutFrontendOwnerRva);
    unsigned frontend_blocked = *reinterpret_cast<unsigned char*>(
        base + kFutFrontendBlockedRva);

    auto frontend_ready_fn = reinterpret_cast<FutReadinessPredicate>(
        base + kFutFrontendReadyRva);
    auto online_ready_fn = reinterpret_cast<FutReadinessPredicate>(
        base + kFutOnlineReadyRva);
    bool frontend_ready = frontend_ready_fn();
    bool online_ready = frontend_ready && online_ready_fn();
    log_line(
        "[FUT-PROBE] registration entered owner=0x%llx callback=0x%llx "
        "slotBefore=0x%llx frontendOwner=0x%llx frontendBlocked=%u "
        "frontendReady=%u onlineReady=%u caller=0x%llx (RVA 0x%llx)",
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(callback),
        (unsigned long long)reinterpret_cast<uintptr_t>(*downstream_slot),
        (unsigned long long)reinterpret_cast<uintptr_t>(frontend_owner),
        frontend_blocked, frontend_ready ? 1u : 0u, online_ready ? 1u : 0u,
        (unsigned long long)reinterpret_cast<uintptr_t>(registration_caller),
        (unsigned long long)(reinterpret_cast<uintptr_t>(registration_caller) - base));
    capture_fut_runtime_callsite("registration", registration_caller);
    if (frontend_ready && !online_ready) {
        g_fut_deferred_owner.store(owner, std::memory_order_release);
        g_fut_deferred_callback.store(
            reinterpret_cast<uintptr_t>(callback), std::memory_order_release);
        g_fut_registration_deferred.store(true, std::memory_order_release);
        log_line("[FUT-FIX] registration deferred until onlineReady=1");
    } else if (online_ready) {
        g_fut_registration_deferred.store(false, std::memory_order_release);
    }
    if (g_fut_registration_original != nullptr) {
        g_fut_registration_original(owner, callback);
    }
    log_line("[FUT-PROBE] registration returned slotAfter=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(*downstream_slot));
}

void __fastcall fut_callback_probe(
    bool parsed, bool valid_club, bool returning_user, const char* club_name,
    uint32_t established, uint32_t asset_id) {
    log_line(
        "[FUT-PROBE] callback parsed=%u validClub=%u returningUser=%u "
        "clubName='%.30s' established=%u assetId=%u target=0x%llx",
        parsed ? 1u : 0u, valid_club ? 1u : 0u, returning_user ? 1u : 0u,
        club_name != nullptr ? club_name : "", established, asset_id,
        (unsigned long long)reinterpret_cast<uintptr_t>(g_fut_callback_original));

    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto** downstream_slot = reinterpret_cast<void**>(
        base + kFutDownstreamCallbackRva);
    void* downstream_before = *downstream_slot;
    bool downstream_wrapped = false;
    if (downstream_before != nullptr &&
        downstream_before != reinterpret_cast<void*>(&fut_downstream_probe)) {
        void* previous = nullptr;
        downstream_wrapped = exchange_callback(
            downstream_slot, reinterpret_cast<void*>(&fut_downstream_probe), &previous);
        if (downstream_wrapped) {
            g_fut_downstream_original = reinterpret_cast<FutParserCallback>(previous);
        }
    }
    log_line(
        "[FUT-PROBE] downstream slot before callback=0x%llx wrapped=%u",
        (unsigned long long)reinterpret_cast<uintptr_t>(downstream_before),
        downstream_wrapped ? 1u : 0u);

    if (g_fut_callback_original != nullptr) {
        g_fut_callback_original(
            parsed, valid_club, returning_user, club_name, established, asset_id);
    }

    if (downstream_wrapped &&
        *downstream_slot == reinterpret_cast<void*>(&fut_downstream_probe)) {
        void* ignored = nullptr;
        exchange_callback(
            downstream_slot, reinterpret_cast<void*>(g_fut_downstream_original), &ignored);
    }

    const auto* valid = reinterpret_cast<const unsigned char*>(base + kFutValidClubRva);
    const auto* returning = reinterpret_cast<const unsigned char*>(base + kFutReturningUserRva);
    const auto* stored_club = reinterpret_cast<const char*>(base + kFutClubNameRva);
    const auto* stored_established = reinterpret_cast<const char*>(base + kFutEstablishedRva);
    const auto* stored_asset = reinterpret_cast<const uint32_t*>(base + kFutAssetIdRva);
    const auto* data_ready = reinterpret_cast<const unsigned char*>(base + kFutDataReadyRva);
    const auto* completion = reinterpret_cast<const unsigned char*>(base + kFutCompletionRva);
    log_line(
        "[FUT-PROBE] stored state validClub=%u returningUser=%u clubName='%.30s' "
        "established='%.15s' assetId=%u dataReady=%u completion=%u "
        "downstreamAfter=0x%llx",
        static_cast<unsigned>(*valid), static_cast<unsigned>(*returning), stored_club,
        stored_established, *stored_asset, static_cast<unsigned>(*data_ready),
        static_cast<unsigned>(*completion),
        (unsigned long long)reinterpret_cast<uintptr_t>(*downstream_slot));
    request_fut_residency_scan();
}

void __fastcall fut_parser_probe(void* completion, const char* json, int length) {
    void** callback_slot = completion != nullptr
        ? reinterpret_cast<void**>(reinterpret_cast<unsigned char*>(completion) + 8)
        : nullptr;
    log_line("[FUT-PROBE] parser entered completion=0x%llx length=%d callback=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(completion), length,
             callback_slot != nullptr
                 ? (unsigned long long)reinterpret_cast<uintptr_t>(*callback_slot)
                 : 0ull);

    prepare_apt_byte_watch_for_profile(30000);

    void* previous = nullptr;
    bool wrapped = callback_slot != nullptr && exchange_callback(
        callback_slot, reinterpret_cast<void*>(&fut_callback_probe), &previous);
    if (wrapped) {
        g_fut_callback_original = reinterpret_cast<FutParserCallback>(previous);
    } else {
        log_line("[FUT-PROBE] callback slot could not be wrapped; parser entry only");
    }

    g_fut_parser_original(completion, json, length);

    if (wrapped) {
        void* ignored = nullptr;
        exchange_callback(callback_slot, previous, &ignored);
    }
    log_line("[FUT-PROBE] parser returned");
}

uintptr_t find_code_signature(const unsigned char* sig, size_t len) {
    HMODULE m = GetModuleHandleW(nullptr);
    MODULEINFO mi = {0};
    if (!GetModuleInformation(GetCurrentProcess(), m, &mi, sizeof(mi))) return 0;
    uintptr_t a = reinterpret_cast<uintptr_t>(mi.lpBaseOfDll);
    uintptr_t end = a + mi.SizeOfImage;
    while (a < end) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == 0) break;
        uintptr_t rend = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            region_executable(mbi)) {
            auto* p = reinterpret_cast<unsigned char*>(a);
            for (size_t i = 0; i + len <= mbi.RegionSize; ++i) {
                if (memcmp(p + i, sig, len) == 0) return a + i;
            }
        }
        a = rend;
    }
    return 0;
}

bool install_fut_registration_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x48, 0x89, 0x5c, 0x24, 0x08, 0x57, 0x48, 0x83, 0xec, 0x30,
        0x48, 0x83, 0x3d, 0x5e, 0x8d, 0x9d, 0xfd, 0x00,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) + kFutRegistrationRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-PROBE] registration signature not available");
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    size_t cursor = 0;
    constexpr size_t kNonRelativePrologueSize = 10;
    memcpy(trampoline + cursor, signature, kNonRelativePrologueSize);
    cursor += kNonRelativePrologueSize;
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t slot = reinterpret_cast<uintptr_t>(module) + kFutDownstreamCallbackRva;
    memcpy(trampoline + cursor, &slot, sizeof(slot));
    cursor += sizeof(slot);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0x83;
    trampoline[cursor++] = 0x38;
    trampoline[cursor++] = 0x00;
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);
    g_fut_registration_original = reinterpret_cast<FutRegistration>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_registration_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_registration_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    log_line("[FUT-PROBE] registration detour installed at 0x%llx; trampoline=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

bool install_fut_state_consumer_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x0f, 0x28, 0x05, 0x59, 0x7e, 0x46, 0xfd,
        0x0f, 0x11, 0x02, 0x0f, 0x28,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) + kFutStateConsumerRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-PROBE] state-consumer signature not available");
        return false;
    }
    unsigned char detour[sizeof(signature)] = {0x48, 0xb8};
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_state_consumer_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) return false;
    log_line("[FUT-PROBE] state-consumer detour installed at 0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target));
    return true;
}

bool install_fut_save_decoder_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x48, 0x89, 0xe0,
        0x55,
        0x41, 0x54,
        0x41, 0x55,
        0x41, 0x56,
        0x41, 0x57,
        0x48, 0x8d, 0xa8, 0x88, 0xfc, 0xff, 0xff,
    };
    static_assert(sizeof(signature) == 19, "decoder signature size changed");
    auto* target = reinterpret_cast<unsigned char*>(module) + kFutSaveDecoderRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-SAVE] decoder signature not available");
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) {
        log_line("[FUT-SAVE] could not allocate decoder trampoline");
        return false;
    }
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0x25;
    memset(trampoline + cursor, 0, 4);
    cursor += 4;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);
    g_fut_save_decoder_original = reinterpret_cast<FutSaveDecoder>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0xff;
    detour[1] = 0x25;
    memset(detour + 2, 0, 4);
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_save_decoder_probe);
    memcpy(detour + 6, &hook, sizeof(hook));
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_save_decoder_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        log_line("[FUT-SAVE] could not install decoder detour");
        return false;
    }
    log_line(
        "[FUT-SAVE] decoder detour installed at 0x%llx; trampoline=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(target),
        (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

using FutConditionDispatcher = uintptr_t(__fastcall *)(void*, void*, void*, void*);
FutConditionDispatcher g_fut_condition_dispatcher_original = nullptr;

bool read_condition_name(void* argument, char* out, size_t capacity) {
    constexpr char kNul = '\0';
    out[0] = kNul;
    if (argument == nullptr) return false;
    __try {
        const char* direct = reinterpret_cast<const char*>(argument);
        size_t i = 0;
        bool printable = true;
        for (; i + 1 < capacity; ++i) {
            const char c = direct[i];
            if (c == kNul) break;
            if (c < 0x20 || c > 0x7e) { printable = false; break; }
            out[i] = c;
        }
        if (printable && i >= 3) {
            out[i] = kNul;
            return true;
        }

        const char* indirect = *reinterpret_cast<const char* const*>(argument);
        if (indirect == nullptr) {
            out[0] = kNul;
            return false;
        }
        for (i = 0; i + 1 < capacity; ++i) {
            const char c = indirect[i];
            if (c == kNul) break;
            if (c < 0x20 || c > 0x7e) {
                out[0] = kNul;
                return false;
            }
            out[i] = c;
        }
        out[i] = kNul;
        return i >= 3;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        out[0] = kNul;
        return false;
    }
}

uintptr_t __fastcall fut_condition_dispatch_probe(void* self, void* a2,
                                                 void* a3, void* a4) {
    char name[80] = {0};
    read_condition_name(a3, name, sizeof(name));
    if (!name[0] && a3 != nullptr) {
        __try {
            void* const* words = reinterpret_cast<void* const*>(a3);
            for (int i = 0; i < 6 && !name[0]; ++i) {
                read_condition_name(words[i], name, sizeof(name));
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) {
        }
    }

    static uintptr_t recent[32] = {};
    static size_t cursor = 0;
    const uintptr_t key = reinterpret_cast<uintptr_t>(a2);
    bool seen = false;
    for (uintptr_t value : recent) {
        if (value == key) { seen = true; break; }
    }
    if (!seen) recent[cursor++ % 32] = key;
    if (!seen) {
        const uint32_t id =
            static_cast<uint32_t>(reinterpret_cast<uintptr_t>(a2) & 0xffffffffu);
        log_line("[FUT-COND] dispatch id=0x%04X (%u) [%s] param='%s' "
                 "self=0x%llx payload=0x%llx",
                 id, id, fut_named_id(id),
                 name[0] ? name : "",
                 (unsigned long long)reinterpret_cast<uintptr_t>(self),
                 (unsigned long long)reinterpret_cast<uintptr_t>(a3));
    }
    if (g_fut_condition_dispatcher_original == nullptr) return 0;
    return g_fut_condition_dispatcher_original(self, a2, a3, a4);
}

constexpr uintptr_t kFutRosterFlagGetterRva = 0x73EE5C0;
constexpr uintptr_t kFutRosterFlagOffset = 0x374;

constexpr uintptr_t kFutRosterCheckBeginRva = 0x7D989D0;
constexpr uintptr_t kFutRosterCheckEndRva = 0x7D98B4B;

uintptr_t g_fut_roster_check_begin = 0;
uintptr_t g_fut_roster_check_end = 0;

extern "C" uint32_t __fastcall fut_roster_flag_getter(void* self) {
    const uintptr_t caller = reinterpret_cast<uintptr_t>(_ReturnAddress());
    if (caller >= g_fut_roster_check_begin && caller < g_fut_roster_check_end) {
        return 1;
    }
    if (self == nullptr) return 0;
    return *(reinterpret_cast<const unsigned char*>(self) + kFutRosterFlagOffset);
}

unsigned char* allocate_near(unsigned char* near_address) {
    SYSTEM_INFO info = {0};
    GetSystemInfo(&info);
    const uintptr_t granularity = info.dwAllocationGranularity;
    const uintptr_t origin = reinterpret_cast<uintptr_t>(near_address);
    for (uintptr_t delta = granularity; delta < 0x40000000; delta += granularity) {
        for (int direction = 0; direction < 2; ++direction) {
            const uintptr_t candidate =
                direction == 0 ? origin + delta : origin - delta;
            if (candidate < granularity) continue;
            auto* page = reinterpret_cast<unsigned char*>(VirtualAlloc(
                reinterpret_cast<void*>(candidate & ~(granularity - 1)), 64,
                MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
            if (page != nullptr) return page;
        }
    }
    return nullptr;
}

bool install_fut_roster_available_patch(HMODULE module) {
    static std::atomic<bool> applied{false};
    if (applied.load()) return true;

    const unsigned char signature[] = {
        0x0F, 0xB6, 0x81, 0x74, 0x03, 0x00, 0x00,
        0xC3,
    };
    auto* base = reinterpret_cast<unsigned char*>(module);
    auto* target = base + kFutRosterFlagGetterRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi)) {
        return false;
    }
    if (memcmp(target, signature, sizeof(signature)) != 0) {
        static std::atomic<bool> warned{false};
        if (!warned.exchange(true)) {
            log_line("[FUT-ROSTER] accessor signature mismatch at 0x%llx; "
                     "not patching (expected movzx eax,[rcx+0x374]; ret)",
                     (unsigned long long)reinterpret_cast<uintptr_t>(target));
        }
        return false;
    }

    g_fut_roster_check_begin =
        reinterpret_cast<uintptr_t>(base) + kFutRosterCheckBeginRva;
    g_fut_roster_check_end =
        reinterpret_cast<uintptr_t>(base) + kFutRosterCheckEndRva;

    auto* stub = allocate_near(target);
    if (stub == nullptr) {
        log_line("[FUT-ROSTER] no executable page within reach of 0x%llx",
                 (unsigned long long)reinterpret_cast<uintptr_t>(target));
        return false;
    }
    size_t cursor = 0;
    stub[cursor++] = 0x48;
    stub[cursor++] = 0xB8;
    const uintptr_t handler =
        reinterpret_cast<uintptr_t>(&fut_roster_flag_getter);
    memcpy(stub + cursor, &handler, sizeof(handler));
    cursor += sizeof(handler);
    stub[cursor++] = 0xFF;
    stub[cursor++] = 0xE0;
    FlushInstructionCache(GetCurrentProcess(), stub, 64);

    const intptr_t relative = reinterpret_cast<intptr_t>(stub) -
                              (reinterpret_cast<intptr_t>(target) + 5);
    if (relative > INT32_MAX || relative < INT32_MIN) {
        log_line("[FUT-ROSTER] stub at 0x%llx is out of rel32 range",
                 (unsigned long long)reinterpret_cast<uintptr_t>(stub));
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }
    unsigned char detour[sizeof(signature)];
    memset(detour, 0xCC, sizeof(detour));
    detour[0] = 0xE9;
    const int32_t displacement = static_cast<int32_t>(relative);
    memcpy(detour + 1, &displacement, sizeof(displacement));
    if (!write_code(target, detour, sizeof(detour))) {
        log_line("[FUT-ROSTER] failed to write the accessor detour at 0x%llx",
                 (unsigned long long)reinterpret_cast<uintptr_t>(target));
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }
    applied.store(true);
    log_line("[FUT-ROSTER] accessor redirected at 0x%llx -> stub 0x%llx; "
             "reports true only to callers in 0x%llx..0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(stub),
             (unsigned long long)g_fut_roster_check_begin,
             (unsigned long long)g_fut_roster_check_end);
    return true;
}

volatile uint32_t* g_squad_guard_hits = nullptr;
void* volatile* g_squad_guard_object = nullptr;

constexpr uintptr_t kSquadNullLoadRva = 0x71B864D;
constexpr uintptr_t kSquadNullResumeRva = 0x71B8654;

bool install_squad_null_guard_patch_impl(HMODULE module) {
    static std::atomic<bool> applied{false};
    if (applied.load()) return true;

    const unsigned char signature[] = {
        0x49, 0x8B, 0x41, 0x28,
        0x4C, 0x8B, 0x08,
    };
    auto* base = reinterpret_cast<unsigned char*>(module);
    auto* target = base + kSquadNullLoadRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi)) {
        return false;
    }
    if (memcmp(target, signature, sizeof(signature)) != 0) {
        static std::atomic<bool> warned{false};
        if (!warned.exchange(true)) {
            log_line("[SQUAD-GUARD] signature mismatch at 0x%llx; not patching "
                     "(expected mov rax,[r9+0x28]; mov r9,[rax])",
                     (unsigned long long)reinterpret_cast<uintptr_t>(target));
        }
        return false;
    }

    auto* stub = allocate_near(target);
    if (stub == nullptr) {
        log_line("[SQUAD-GUARD] no executable page within reach of 0x%llx",
                 (unsigned long long)reinterpret_cast<uintptr_t>(target));
        return false;
    }
    constexpr unsigned char body[] = {
        0x49, 0x8B, 0x41, 0x28,
        0x48, 0x85, 0xC0,
        0x74, 0x05,
        0x4C, 0x8B, 0x08,
        0xEB, 0x15,
        0x4C, 0x89, 0x0D, 0x33, 0x00, 0x00, 0x00,
        0xF0, 0xFF, 0x05, 0x24, 0x00, 0x00, 0x00,
        0x4C, 0x8D, 0x0D, 0x2D, 0x00, 0x00, 0x00,
        0xFF, 0x25, 0x00, 0x00, 0x00, 0x00,
    };
    static_assert(sizeof(body) == 41, "squad guard stub layout changed");
    static_assert(body[12] == 0xEB && body[13] == 0x15,
                  "non-null branch encoding changed");
    static_assert(0x0E + 0x15 == 0x23,
                  "non-null branch must land on the resume jump");
    memcpy(stub, body, sizeof(body));
    g_squad_guard_hits = reinterpret_cast<volatile uint32_t*>(stub + 0x40);
    g_squad_guard_object = reinterpret_cast<void* volatile*>(stub + 0x48);
    *g_squad_guard_hits = 0;
    *g_squad_guard_object = nullptr;
    memset(stub + 0x50, 0, 0x20);
    const uintptr_t resume =
        reinterpret_cast<uintptr_t>(base) + kSquadNullResumeRva;
    memcpy(stub + sizeof(body), &resume, sizeof(resume));
    FlushInstructionCache(GetCurrentProcess(), stub, 64);

    const intptr_t relative = reinterpret_cast<intptr_t>(stub) -
                              (reinterpret_cast<intptr_t>(target) + 5);
    if (relative > INT32_MAX || relative < INT32_MIN) {
        log_line("[SQUAD-GUARD] stub at 0x%llx is out of rel32 range",
                 (unsigned long long)reinterpret_cast<uintptr_t>(stub));
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }
    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0xE9;
    const int32_t displacement = static_cast<int32_t>(relative);
    memcpy(detour + 1, &displacement, sizeof(displacement));
    if (!write_code(target, detour, sizeof(detour))) {
        log_line("[SQUAD-GUARD] failed to write the guard detour at 0x%llx",
                 (unsigned long long)reinterpret_cast<uintptr_t>(target));
        VirtualFree(stub, 0, MEM_RELEASE);
        return false;
    }
    applied.store(true);
    log_line("[SQUAD-GUARD] null check installed at 0x%llx -> stub 0x%llx; "
             "[r9+0x28]==0 now supplies an empty value instead of faulting",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(stub));
    return true;
}

bool install_fut_condition_dispatch_probe(HMODULE module) {
    if (g_fut_condition_dispatcher_original != nullptr) return true;
    const unsigned char signature[] = {
        0x48, 0x89, 0x5C, 0x24, 0x10,
        0x55,
        0x56,
        0x57,
        0x41, 0x54,
        0x41, 0x55,
        0x41, 0x56,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) +
                   kFutConditionDispatcherRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    const uintptr_t resume =
        reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    FlushInstructionCache(GetCurrentProcess(), trampoline, 64);
    g_fut_condition_dispatcher_original =
        reinterpret_cast<FutConditionDispatcher>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    const uintptr_t hook =
        reinterpret_cast<uintptr_t>(&fut_condition_dispatch_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_condition_dispatcher_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    log_line("[FUT-COND] condition dispatcher detour installed at 0x%llx; "
             "trampoline=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

bool install_fut_ui_event_dispatcher_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x48, 0x89, 0x5c, 0x24, 0x08,
        0x57,
        0x48, 0x83, 0xec, 0x20,
        0x31, 0xdb,
        0x89, 0xd7,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) +
                   kFutUiEventDispatcherRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-EVENT] dispatcher signature not available");
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);
    g_fut_ui_event_dispatcher_original =
        reinterpret_cast<FutUiEventDispatcher>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_ui_event_dispatcher_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_ui_event_dispatcher_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }

    auto base = reinterpret_cast<uintptr_t>(module);
    const auto* jump_table = reinterpret_cast<const uint32_t*>(
        base + kFutUiEventJumpTableRva);
    for (uint32_t index = 0; index <= 0x0c; ++index) {
        log_line("[FUT-EVENT] jump id=0x%x -> rva=0x%x",
                 0x275d + index, jump_table[index]);
    }
    log_line("[FUT-EVENT] dispatcher detour installed at 0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target));
    return true;
}

bool install_fut_ui_router_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x44, 0x89, 0xc0,
        0x49, 0x89, 0xd0,
        0x89, 0xc2,
        0xeb, 0x06,
        0xcc, 0xcc, 0xcc,
    };
    auto base = reinterpret_cast<uintptr_t>(module);
    auto* target = reinterpret_cast<unsigned char*>(
        base + kFutUiRouterWrapperRva);
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-ROUTER] wrapper signature not available");
        return false;
    }

    g_fut_ui_router_original = reinterpret_cast<FutUiRouter>(
        base + kFutUiRouterRva);
    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_ui_router_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_ui_router_original = nullptr;
        return false;
    }
    log_line(
        "[FUT-ROUTER] wrapper detour installed at 0x%llx; router=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(target),
        (unsigned long long)reinterpret_cast<uintptr_t>(g_fut_ui_router_original));
    return true;
}

using FutDetourPublisher = void (*)(void* trampoline);

void publish_fut_apt_call_method_pop_trampoline(void* trampoline) {
    g_fut_apt_call_method_pop_original =
        reinterpret_cast<FutAptCallMethodPop>(trampoline);
    MemoryBarrier();
}

void* install_fut_navigation_detour(
    HMODULE module, uintptr_t rva, const unsigned char* signature,
    size_t signature_size, void* hook, const char* label,
    FutDetourPublisher publish_before_detour = nullptr) {
    auto* target = reinterpret_cast<unsigned char*>(module) + rva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (signature == nullptr || hook == nullptr || signature_size < 14 ||
        signature_size > 32 || !region_ok(target, mbi) ||
        !region_executable(mbi) ||
        memcmp(target, signature, signature_size) != 0) {
        return nullptr;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, signature_size + 14, MEM_COMMIT | MEM_RESERVE,
        PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return nullptr;
    memcpy(trampoline, signature, signature_size);
    size_t cursor = signature_size;
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0x25;
    memset(trampoline + cursor, 0, 4);
    cursor += 4;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + signature_size;
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);

    if (publish_before_detour != nullptr) {
        publish_before_detour(trampoline);
    }

    unsigned char detour[32];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0xff;
    detour[1] = 0x25;
    memset(detour + 2, 0, 4);
    uintptr_t hook_address = reinterpret_cast<uintptr_t>(hook);
    memcpy(detour + 6, &hook_address, sizeof(hook_address));
    if (!write_code(target, detour, signature_size)) {
        if (publish_before_detour != nullptr) publish_before_detour(nullptr);
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return nullptr;
    }
    log_line(
        "[FUT-NAV] %s detour installed at 0x%llx; trampoline=0x%llx",
        label,
        (unsigned long long)reinterpret_cast<uintptr_t>(target),
        (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return trampoline;
}

void publish_transfer_pile_get_member_trampoline(void* trampoline) {
    g_transfer_pile_get_member_original =
        reinterpret_cast<FutModernAptGetMember>(trampoline);
    MemoryBarrier();
}

bool install_transfer_pile_capacity_patch_impl(HMODULE module) {
    if (module == nullptr) return false;
    if (g_transfer_pile_get_member_original != nullptr) return true;

    constexpr uintptr_t kGetMemberRva = 0x77a82b0;
    const unsigned char signature[] = {
        0x56,
        0x57,
        0x41, 0x56,
        0x48, 0x83, 0xec, 0x50,
        0x48, 0xc7, 0x44, 0x24, 0x40,
        0xfe, 0xff, 0xff, 0xff,
    };
    void* trampoline = install_fut_navigation_detour(
        module, kGetMemberRva, signature, sizeof(signature),
        reinterpret_cast<void*>(&transfer_pile_get_member_probe),
        "TRADE_PILE_SIZE zero-only fallback",
        &publish_transfer_pile_get_member_trampoline);
    if (trampoline == nullptr) return false;

    log_line(
        "[FUT-PILE-SIZE] exact getMember fallback installed at "
        "FIFA17.exe+0x%llX; non-zero values remain untouched",
        (unsigned long long)kGetMemberRva);
    return true;
}

void publish_flux_apt_method_trampoline(void* trampoline) {
    g_flux_apt_method_original =
        reinterpret_cast<FutModernAptCallConstantMethod>(trampoline);
    MemoryBarrier();
}

void publish_flux_apt_callable_trampoline(void* trampoline) {
    g_flux_apt_callable_original =
        reinterpret_cast<FutModernAptInvokeCallable>(trampoline);
    MemoryBarrier();
}

void publish_flux_apt_resolve_path_trampoline(void* trampoline) {
    g_flux_apt_resolve_path_original =
        reinterpret_cast<FutModernAptResolveMoviePath>(trampoline);
    MemoryBarrier();
}

void publish_flux_apt_load_dispatch_trampoline(void* trampoline) {
    g_flux_apt_load_dispatch_original =
        reinterpret_cast<FutModernAptLoadMovieDispatch>(trampoline);
    MemoryBarrier();
}

bool install_flux_apt_method_probe(HMODULE module,
                                   uintptr_t load_movie_operand) {
    if (module == nullptr || load_movie_operand == 0) return false;
    g_flux_load_movie_operand.store(load_movie_operand,
                                    std::memory_order_release);
    if (g_flux_apt_method_original == nullptr) {
        constexpr uintptr_t kModernCallConstantMethodRva = 0x77a8a30;
        const unsigned char signature[] = {
            0x48, 0x89, 0x54, 0x24, 0x10,
            0x53, 0x55, 0x56, 0x57,
            0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kModernCallConstantMethodRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&flux_apt_method_probe),
            "FluxHub loadMovie method dispatcher",
            &publish_flux_apt_method_trampoline);
        if (trampoline == nullptr) {
            log_line(
                "[FUT-APT-LOADMOVIE] RVA 0x77a8a30 signature unavailable; "
                "method probe not installed");
            return false;
        }
    }

    if (g_flux_apt_callable_original == nullptr) {
        constexpr uintptr_t kModernInvokeCallableRva = 0x77e08f0;
        const unsigned char signature[] = {
            0x48, 0x89, 0x5c, 0x24, 0x10,
            0x55, 0x56, 0x57,
            0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kModernInvokeCallableRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&flux_apt_callable_probe),
            "FluxHub loadMovie callable dispatcher",
            &publish_flux_apt_callable_trampoline);
        if (trampoline == nullptr) {
            log_line(
                "[FUT-APT-CALLABLE] RVA 0x77e08f0 signature unavailable; "
                "callable probe not installed");
            return false;
        }
    }

    if (g_flux_apt_resolve_path_original == nullptr) {
        constexpr uintptr_t kResolveMoviePathRva = 0x77deaf0;
        const unsigned char signature[] = {
            0x55, 0x56, 0x57,
            0x48, 0x83, 0xec, 0x60,
            0x48, 0xc7, 0x44, 0x24, 0x38, 0xfe, 0xff, 0xff, 0xff,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kResolveMoviePathRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&flux_apt_resolve_path_probe),
            "FluxHub loadMovie path resolver",
            &publish_flux_apt_resolve_path_trampoline);
        if (trampoline == nullptr) {
            log_line(
                "[FUT-MOVIE-PATH] RVA 0x77deaf0 signature unavailable; "
                "path probe not installed");
            return false;
        }
    }
    if (g_flux_apt_load_dispatch_original == nullptr) {
        constexpr uintptr_t kLoadMovieDispatchRva = 0x77cb070;
        const unsigned char signature[] = {
            0x48, 0x89, 0xe0,
            0x55,
            0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57,
            0x48, 0x8d, 0x68, 0xa1,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kLoadMovieDispatchRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&flux_apt_load_dispatch_probe),
            "FluxHub loadMovie dispatch",
            &publish_flux_apt_load_dispatch_trampoline);
        if (trampoline == nullptr) {
            log_line(
                "[FUT-MOVIE-LOAD] RVA 0x77cb070 signature unavailable; "
                "load probe not installed");
            return false;
        }
    }
    log_line(
        "[FUT-APT-LOADMOVIE] filtered probe armed operand=0x%llx "
        "dispatcherRva=0x77a8a30 callableRva=0x77e08f0 "
        "resolverRva=0x77deaf0 loadRva=0x77cb070 rawReadsOnly=1",
        (unsigned long long)load_movie_operand);
    return g_flux_apt_method_original != nullptr &&
           g_flux_apt_callable_original != nullptr &&
           g_flux_apt_resolve_path_original != nullptr &&
           g_flux_apt_load_dispatch_original != nullptr;
}

bool install_fut_script_publish_bridge_probe(HMODULE module) {
    if (g_fut_script_publish_bridge_original != nullptr) return true;

    const unsigned char signature[] = {
        0x4c, 0x89, 0x44, 0x24, 0x18,
        0x4c, 0x89, 0x4c, 0x24, 0x20,
        0x48, 0x83, 0xec, 0x28,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) +
                   kFutScriptPublishBridgeRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        return false;
    }

    constexpr size_t kTrampolineOffset = 0;
    constexpr size_t kGateOffset = 32;
    constexpr size_t kAllocationSize = 96;
    auto* block = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, kAllocationSize, MEM_COMMIT | MEM_RESERVE,
        PAGE_EXECUTE_READWRITE));
    if (block == nullptr) return false;
    auto* trampoline = block + kTrampolineOffset;
    auto* gate = block + kGateOffset;

    auto emit_absolute_jump = [](unsigned char* output, uintptr_t destination) {
        output[0] = 0xff;
        output[1] = 0x25;
        memset(output + 2, 0, 4);
        memcpy(output + 6, &destination, sizeof(destination));
    };

    memcpy(trampoline, signature, sizeof(signature));
    emit_absolute_jump(
        trampoline + sizeof(signature),
        reinterpret_cast<uintptr_t>(target) + sizeof(signature));

    size_t cursor = 0;
    gate[cursor++] = 0x41;
    gate[cursor++] = 0x81;
    gate[cursor++] = 0xfe;
    const uint32_t event_id = 0x2763;
    memcpy(gate + cursor, &event_id, sizeof(event_id));
    cursor += sizeof(event_id);
    gate[cursor++] = 0x74;
    gate[cursor++] = 0x0e;
    emit_absolute_jump(gate + cursor,
                       reinterpret_cast<uintptr_t>(trampoline));
    cursor += 14;
    emit_absolute_jump(
        gate + cursor,
        reinterpret_cast<uintptr_t>(&fut_script_publish_bridge_probe));
    cursor += 14;
    FlushInstructionCache(GetCurrentProcess(), block, kAllocationSize);

    g_fut_script_publish_bridge_original =
        reinterpret_cast<FutScriptPublishBridge>(trampoline);
    MemoryBarrier();

    unsigned char detour[sizeof(signature)] = {};
    emit_absolute_jump(detour, reinterpret_cast<uintptr_t>(gate));
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_script_publish_bridge_original = nullptr;
        MemoryBarrier();
        VirtualFree(block, 0, MEM_RELEASE);
        return false;
    }

    log_line(
        "[FUT-SCRIPT] inline bridge observer installed; "
        "gate=0x%llx trampoline=0x%llx firstFilter='cmp r14d,0x2763' "
        "(no hardware breakpoint)",
        (unsigned long long)reinterpret_cast<uintptr_t>(gate),
        (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

bool install_fut_navigation_probes(HMODULE module) {
    if (g_fut_ui_send_action_original == nullptr) {
        const unsigned char signature[] = {
            0x48, 0x89, 0xe0,
            0x56, 0x57,
            0x41, 0x54,
            0x41, 0x56,
            0x41, 0x57,
            0x48, 0x81, 0xec, 0x80, 0x00, 0x00, 0x00,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kFutUiSendActionRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&fut_ui_send_action_probe), "SendAction");
        g_fut_ui_send_action_original =
            reinterpret_cast<FutUiSendAction>(trampoline);
    }

    if (g_fut_view_manager_process_action_original == nullptr) {
        const unsigned char signature[] = {
            0x48, 0x89, 0x5c, 0x24, 0x08,
            0x48, 0x89, 0x74, 0x24, 0x10,
            0x57,
            0x48, 0x83, 0xec, 0x30,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kFutViewManagerProcessActionRva, signature,
            sizeof(signature),
            reinterpret_cast<void*>(&fut_view_manager_process_action_probe),
            "ProcessAction");
        g_fut_view_manager_process_action_original =
            reinterpret_cast<FutViewManagerProcessAction>(trampoline);
    }

    if (g_fut_apt_action_bridge_original == nullptr) {
        const unsigned char signature[] = {
            0x48, 0x89, 0xe0,
            0x56, 0x57,
            0x41, 0x56,
            0x48, 0x83, 0xec, 0x70,
            0x48, 0xc7, 0x40, 0x98, 0xfe, 0xff, 0xff, 0xff,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kFutAptActionBridgeRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&fut_apt_action_bridge_probe),
            "AptActionBridge");
        g_fut_apt_action_bridge_original =
            reinterpret_cast<FutAptActionBridge>(trampoline);
    }

    if (g_fut_apt_vm_probe_enabled.load() &&
        g_fut_apt_call_method_pop_original == nullptr) {
        const unsigned char signature[] = {
            0x55, 0x57, 0x41, 0x56,
            0x48, 0x8d, 0xac, 0x24, 0x90, 0xfe, 0xff, 0xff,
            0x48, 0x81, 0xec, 0x70, 0x02, 0x00, 0x00,
        };
        void* trampoline = install_fut_navigation_detour(
            module, kFutAptCallMethodPopRva, signature, sizeof(signature),
            reinterpret_cast<void*>(&fut_apt_call_method_pop_probe),
            "AptCallMethodPop",
            &publish_fut_apt_call_method_pop_trampoline);
        g_fut_apt_call_method_pop_original =
            reinterpret_cast<FutAptCallMethodPop>(trampoline);
    }

    return g_fut_ui_send_action_original != nullptr &&
           g_fut_view_manager_process_action_original != nullptr &&
           g_fut_apt_action_bridge_original != nullptr &&
           (!g_fut_apt_vm_probe_enabled.load() ||
            g_fut_apt_call_method_pop_original != nullptr);
}

bool install_fut_login_flow_handler_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x48, 0x89, 0xe0,
        0x57,
        0x48, 0x81, 0xec, 0xa0, 0x00, 0x00, 0x00,
        0x48, 0xc7, 0x40, 0xd8, 0xfe, 0xff, 0xff, 0xff,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) +
                   kFutLoginFlowHandlerRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            log_line("[FUT-LOGIN-FLOW] handler not decrypted yet; retrying");
        }
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0x25;
    memset(trampoline + cursor, 0, 4);
    cursor += 4;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);
    g_fut_login_flow_handler_original =
        reinterpret_cast<FutLoginFlowHandler>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0xff;
    detour[1] = 0x25;
    memset(detour + 2, 0, 4);
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_login_flow_handler_probe);
    memcpy(detour + 6, &hook, sizeof(hook));
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_login_flow_handler_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    log_line(
        "[FUT-LOGIN-FLOW] handler detour installed at 0x%llx; "
        "0x0BE7 -> FUTLoginComplete 0x27A0; trampoline=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(target),
        (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

bool install_fut_ui_model_publish_probe(HMODULE module) {
    auto base = reinterpret_cast<uintptr_t>(module);
    auto** slot = reinterpret_cast<void**>(base + kFutUiModelVtableRva + 0x20);
    auto* expected = reinterpret_cast<void*>(base + kFutUiModelPublishRva);
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(slot, mbi)) {
        log_line("[FUT-MODEL] PublishToObject vtable slot is not readable");
        return false;
    }
    if (*slot != expected) {
        log_line(
            "[FUT-MODEL] PublishToObject vtable slot not available "
            "actual=0x%llx expected=0x%llx",
            (unsigned long long)reinterpret_cast<uintptr_t>(*slot),
            (unsigned long long)reinterpret_cast<uintptr_t>(expected));
        return false;
    }
    void* previous = nullptr;
    if (!exchange_callback(
            slot, reinterpret_cast<void*>(&fut_ui_model_publish_probe), &previous)) {
        g_fut_ui_model_publish_original = nullptr;
        return false;
    }
    g_fut_ui_model_publish_original = reinterpret_cast<FutUiModelPublish>(previous);
    log_line(
        "[FUT-MODEL] PublishToObject vtable hook installed slot=0x%llx "
        "original=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(slot),
        (unsigned long long)reinterpret_cast<uintptr_t>(previous));
    return true;
}

bool install_fut_phase_handler_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x57,
        0x48, 0x83, 0xec, 0x40,
        0x48, 0xc7, 0x44, 0x24, 0x20, 0xfe, 0xff, 0xff, 0xff,
        0x48, 0x89, 0x5c, 0x24, 0x58,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) + kFutPhaseHandlerRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            log_line("[FUT-PHASE] phase handler not decrypted yet; retrying");
        }
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    g_fut_phase_handler_original = reinterpret_cast<FutPhaseHandler>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_phase_handler_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_phase_handler_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    log_line("[FUT-PHASE] phase handler detour installed at 0x%llx; trampoline=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

bool install_fut_club_submit_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x48, 0x89, 0x5c, 0x24, 0x08,
        0x57,
        0x48, 0x83, 0xec, 0x20,
        0x48, 0x89, 0xd7,
        0x48, 0x89, 0xcb,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) + kFutClubSubmitRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-SUBMIT] users/club submit signature not available");
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    g_fut_club_submit_original = reinterpret_cast<FutClubSubmit>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_club_submit_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_club_submit_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    log_line("[FUT-SUBMIT] users/club submit detour installed at 0x%llx; "
             "trampoline=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

bool install_fut_club_url_builder_probe(HMODULE module) {
    const unsigned char signature[] = {
        0x57,
        0x48, 0x83, 0xec, 0x60,
        0x48, 0xc7, 0x44, 0x24, 0x20,
        0xfe, 0xff, 0xff, 0xff,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) +
                   kFutClubUrlBuilderRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        log_line("[FUT-URL] users/club builder signature not available");
        return false;
    }
    g_fut_club_url_builder_va.store(reinterpret_cast<uintptr_t>(target),
                                    std::memory_order_release);

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) return false;
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);
    g_fut_club_url_builder_original = reinterpret_cast<FutClubUrlBuilder>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_club_url_builder_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        g_fut_club_url_builder_original = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    log_line("[FUT-URL] users/club builder detour installed at 0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target));
    return true;
}

bool patch_skip_cert_alert() {
    const unsigned char sig[] = {0x41, 0x8d, 0x55, 0x02, 0x45, 0x8d, 0x45, 0x2e, 0x48, 0x89, 0xe9};
    uintptr_t setup = find_code_signature(sig, sizeof(sig));
    if (setup == 0) {
        log_line("[PATCH] alert-46 site not found; skipping name-check patch");
        return false;
    }
    auto* je = reinterpret_cast<unsigned char*>(setup - 6);
    if (je[0] != 0x0F || je[1] != 0x84) {
        log_line("[PATCH] expected je at 0x%llx, found %02x %02x; aborting name-check patch",
                 (unsigned long long)(setup - 6), je[0], je[1]);
        return false;
    }
    int32_t rel = *reinterpret_cast<int32_t*>(je + 2);
    unsigned char stub[6] = {0xE9, 0, 0, 0, 0, 0x90};
    int32_t jmp_rel = rel + 1;
    memcpy(stub + 1, &jmp_rel, 4);
    if (!write_code(je, stub, sizeof(stub))) {
        log_line("[PATCH] could not write name-check patch");
        return false;
    }
    log_line("[PATCH] name check at 0x%llx: je -> jmp accept (skips certificate_unknown)",
             (unsigned long long)(setup - 6));
    return true;
}

bool patch_cn_verify_accept() {
    uintptr_t fn = find_anchor_function("gosca.ea.com");
    if (fn == 0) return false;
    auto* base = reinterpret_cast<unsigned char*>(fn);
    const unsigned char prologue[] = {0x48, 0x89, 0x5c, 0x24, 0x08};
    uintptr_t entry = 0;
    for (int i = 0; i < 16; ++i) {
        if (memcmp(base + i, prologue, sizeof(prologue)) == 0) { entry = fn + i; break; }
    }
    if (entry == 0) {
        log_line("[PATCH] CN-verify prologue not found near 0x%llx", (unsigned long long)fn);
        return false;
    }
    const unsigned char stub[3] = {0x31, 0xC0, 0xC3};
    if (!write_code(reinterpret_cast<unsigned char*>(entry), stub, sizeof(stub))) return false;
    log_line("[PATCH] CN verify at 0x%llx forced to return 0 (accept)", (unsigned long long)entry);
    return true;
}

}

bool apply_transfer_pile_capacity_patch() {
    return install_transfer_pile_capacity_patch_impl(GetModuleHandleW(nullptr));
}

void configure_fut_profile_advance(bool enabled) {
    g_fut_apt_manager.store(nullptr);
    g_fut_force_profile_advance_fired.store(false);
    g_fut_profile_state_consumed.store(false);
    g_fut_profile_publish_succeeded.store(false);
    g_fut_force_profile_advance_enabled.store(enabled);
    log_line(
        "[FUT-FORCE] post-profile advance %s ([Patch] "
        "force_profile_advance=%d)",
        enabled ? "armed" : "disabled", enabled ? 1 : 0);
}

void configure_fut_apt_vm_probe(bool enabled) {
    g_fut_apt_vm_probe_count.store(0);
    g_fut_apt_vm_probe_enabled.store(enabled);
    log_line("[APT-VM] callMethodPop probe %s ([Patch] apt_vm_probe=%d)",
             enabled ? "armed" : "disabled", enabled ? 1 : 0);
}

void configure_fut_script_publish_probe(bool enabled) {
    g_fut_script_publish_probe_count.store(0);
    g_fut_script_publish_probe_enabled.store(enabled);
    log_line(
        "[FUT-SCRIPT] inline bridge observer %s ([Patch] "
        "script_publish_watch=%d)",
        enabled ? "armed" : "disabled", enabled ? 1 : 0);
}

bool install_squad_null_guard_patch(HMODULE module) {
    return install_squad_null_guard_patch_impl(module);
}

uint32_t squad_guard_hits() {
    return g_squad_guard_hits != nullptr ? *g_squad_guard_hits : 0;
}

void* squad_guard_object() {
    return g_squad_guard_object != nullptr ? *g_squad_guard_object : nullptr;
}

bool squad_input_capture_active() {
    const ULONGLONG until =
        g_squad_input_capture_until.load(std::memory_order_acquire);
    return until != 0 && GetTickCount64() <= until;
}

void finish_squad_input_capture() {
    g_squad_input_capture_until.store(0, std::memory_order_release);
}

void configure_flux_components_ready(bool enabled) {
    g_flux_components_ready_requested.store(false, std::memory_order_release);
    g_flux_components_ready_enabled.store(enabled, std::memory_order_release);
    log_line("[FUT-FLUX-WAIT] workaround %s ([Patch] "
             "force_flux_components_ready=%d)",
             enabled ? "armed" : "disabled", enabled ? 1 : 0);
}

bool consume_flux_components_ready_request() {
    return g_flux_components_ready_requested.exchange(
        false, std::memory_order_acq_rel);
}

bool apply_fut_phase_probe() {
    static bool installed = false;
    if (installed) return true;
    HMODULE module = GetModuleHandleW(nullptr);
    if (module == nullptr) return false;
    if (!install_fut_phase_handler_probe(module)) return false;
    installed = true;
    return true;
}

bool apply_fut_login_flow_probe() {
    static bool installed = false;
    if (installed) return true;
    HMODULE module = GetModuleHandleW(nullptr);
    if (module == nullptr) return false;
    if (!install_fut_login_flow_handler_probe(module)) return false;
    installed = true;
    return true;
}

bool apply_fut_navigation_probe() {
    static bool waiting_logged = false;
    HMODULE module = GetModuleHandleW(nullptr);
    if (module == nullptr) return false;
    if (!install_fut_navigation_probes(module)) {
        if (!waiting_logged) {
            waiting_logged = true;
            log_line("[FUT-NAV] waiting for SendAction/ProcessAction code to decrypt");
        }
        return false;
    }
    return true;
}

bool apply_fut_script_publish_probe() {
    if (!g_fut_script_publish_probe_enabled.load()) return true;
    if (g_fut_script_publish_bridge_original != nullptr) return true;

    static bool waiting_logged = false;
    HMODULE module = GetModuleHandleW(nullptr);
    if (module == nullptr) return false;
    if (!install_fut_script_publish_bridge_probe(module)) {
        if (!waiting_logged) {
            waiting_logged = true;
            log_line("[FUT-SCRIPT] waiting for bridge code to decrypt");
        }
        return false;
    }
    return true;
}

bool apply_fut_accountinfo_probe() {
    static bool installed = false;
    if (installed) return true;

    HMODULE module = GetModuleHandleW(nullptr);
    if (module == nullptr) return false;

    constexpr uintptr_t kParserRva = 0x6ec9d80;
    const unsigned char signature[] = {
        0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41,
        0x57, 0x48, 0x8d, 0xac, 0x24, 0x20, 0xff, 0xff, 0xff,
    };
    auto* target = reinterpret_cast<unsigned char*>(module) + kParserRva;
    MEMORY_BASIC_INFORMATION mbi = {0};
    if (!region_ok(target, mbi) || !region_executable(mbi) ||
        memcmp(target, signature, sizeof(signature)) != 0) {
        return false;
    }

    auto* trampoline = reinterpret_cast<unsigned char*>(VirtualAlloc(
        nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) {
        log_line("[FUT-PROBE] could not allocate parser trampoline");
        return false;
    }
    memcpy(trampoline, signature, sizeof(signature));
    size_t cursor = sizeof(signature);
    trampoline[cursor++] = 0x48;
    trampoline[cursor++] = 0xb8;
    uintptr_t resume = reinterpret_cast<uintptr_t>(target) + sizeof(signature);
    memcpy(trampoline + cursor, &resume, sizeof(resume));
    cursor += sizeof(resume);
    trampoline[cursor++] = 0xff;
    trampoline[cursor++] = 0xe0;
    FlushInstructionCache(GetCurrentProcess(), trampoline, cursor);
    g_fut_parser_original = reinterpret_cast<FutParser>(trampoline);

    unsigned char detour[sizeof(signature)];
    memset(detour, 0x90, sizeof(detour));
    detour[0] = 0x48;
    detour[1] = 0xb8;
    uintptr_t hook = reinterpret_cast<uintptr_t>(&fut_parser_probe);
    memcpy(detour + 2, &hook, sizeof(hook));
    detour[10] = 0xff;
    detour[11] = 0xe0;
    if (!write_code(target, detour, sizeof(detour))) {
        VirtualFree(trampoline, 0, MEM_RELEASE);
        g_fut_parser_original = nullptr;
        log_line("[FUT-PROBE] could not install parser detour");
        return false;
    }

    if (!install_fut_registration_probe(module)) {
        log_line("[FUT-PROBE] parser probe active without registration probe");
    }
    if (!install_fut_state_consumer_probe(module)) {
        log_line("[FUT-PROBE] parser probe active without state-consumer probe");
    }
    if (!install_fut_ui_event_dispatcher_probe(module)) {
        log_line("[FUT-PROBE] parser probe active without UI-event probe");
    }
    if (!install_fut_club_url_builder_probe(module)) {
        log_line("[FUT-PROBE] parser probe active without users/club URL probe");
    }
    if (!install_fut_club_submit_probe(module)) {
        log_line("[FUT-PROBE] parser probe active without users/club submit probe");
    }
    if (!install_fut_phase_handler_probe(module)) {
        log_line("[FUT-PROBE] parser probe active without phase-handler probe");
    }
    if (!apply_fut_login_flow_probe()) {
        log_line("[FUT-PROBE] parser probe active without login-flow probe");
    }
    installed = true;
    log_line("[FUT-PROBE] parser detour installed at 0x%llx; trampoline=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(target),
             (unsigned long long)reinterpret_cast<uintptr_t>(trampoline));
    return true;
}

void log_fut_gate_state(const char* phase) {
    HMODULE module = GetModuleHandleW(nullptr);
    MODULEINFO mi = {0};
    if (module == nullptr ||
        !GetModuleInformation(GetCurrentProcess(), module, &mi, sizeof(mi))) {
        return;
    }
    constexpr uintptr_t kLargestObservedRva = kFutFrontendReadyRva;
    if (mi.SizeOfImage <= kLargestObservedRva + 32) return;

    const unsigned char online_signature[] = {
        0x48, 0x83, 0xec, 0x28, 0xe8, 0xb7, 0x06, 0x26, 0x00,
        0x48, 0x85, 0xc0, 0x74, 0x1e,
    };
    auto* online_target = reinterpret_cast<unsigned char*>(module) + kFutOnlineReadyRva;
    if (memcmp(online_target, online_signature, sizeof(online_signature)) != 0) return;

    auto base = reinterpret_cast<uintptr_t>(module);
    auto frontend_ready_fn = reinterpret_cast<FutReadinessPredicate>(
        base + kFutFrontendReadyRva);
    auto online_ready_fn = reinterpret_cast<FutReadinessPredicate>(
        base + kFutOnlineReadyRva);
    bool frontend_ready = frontend_ready_fn();
    bool online_ready = frontend_ready && online_ready_fn();

    using SingletonGetter = void*(__fastcall *)();
    constexpr uintptr_t kOnlineSingletonGetterRva = 0x71995b0;
    auto getter = reinterpret_cast<SingletonGetter>(base + kOnlineSingletonGetterRva);
    void* singleton = getter();
    void* vtable = singleton != nullptr ? *reinterpret_cast<void**>(singleton) : nullptr;
    void* online_method = vtable != nullptr
        ? *reinterpret_cast<void**>(reinterpret_cast<unsigned char*>(vtable) + 0x138)
        : nullptr;

    constexpr uintptr_t kProfileConsumerRva = 0x48acf60;
    const auto* profile_consumer = reinterpret_cast<const unsigned char*>(
        base + kProfileConsumerRva);
    log_line(
        "[FUT-GATE] phase=%s frontendReady=%u onlineReady=%u singleton=0x%llx "
        "vtable=0x%llx onlineMethod=0x%llx profileAvailable=%u profilePending=%u "
        "dataReady=%u",
        phase != nullptr ? phase : "", frontend_ready ? 1u : 0u,
        online_ready ? 1u : 0u,
        (unsigned long long)reinterpret_cast<uintptr_t>(singleton),
        (unsigned long long)reinterpret_cast<uintptr_t>(vtable),
        (unsigned long long)reinterpret_cast<uintptr_t>(online_method),
        static_cast<unsigned>(profile_consumer[0x13]),
        static_cast<unsigned>(profile_consumer[0x18]),
        static_cast<unsigned>(*reinterpret_cast<unsigned char*>(
            base + kFutDataReadyRva)));
}

void retry_deferred_fut_registration() {
    if (!g_fut_registration_deferred.load(std::memory_order_acquire) ||
        g_fut_registration_original == nullptr) {
        return;
    }

    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto frontend_ready_fn = reinterpret_cast<FutReadinessPredicate>(
        base + kFutFrontendReadyRva);
    auto online_ready_fn = reinterpret_cast<FutReadinessPredicate>(
        base + kFutOnlineReadyRva);
    if (!frontend_ready_fn() || !online_ready_fn()) return;

    if (!g_fut_registration_deferred.exchange(false, std::memory_order_acq_rel)) {
        return;
    }
    void* owner = g_fut_deferred_owner.load(std::memory_order_acquire);
    auto callback = reinterpret_cast<FutParserCallback>(
        g_fut_deferred_callback.load(std::memory_order_acquire));
    auto** downstream_slot = reinterpret_cast<void**>(
        base + kFutDownstreamCallbackRva);
    log_line(
        "[FUT-FIX] retrying deferred registration owner=0x%llx callback=0x%llx "
        "slotBefore=0x%llx",
        (unsigned long long)reinterpret_cast<uintptr_t>(owner),
        (unsigned long long)reinterpret_cast<uintptr_t>(callback),
        (unsigned long long)reinterpret_cast<uintptr_t>(*downstream_slot));
    g_fut_registration_original(owner, callback);
    log_line("[FUT-FIX] deferred registration returned slotAfter=0x%llx",
             (unsigned long long)reinterpret_cast<uintptr_t>(*downstream_slot));
}

void capture_fut_runtime_callsite(const char* label, void* caller) {
    if (label == nullptr || caller == nullptr) return;
    static std::atomic<bool> profile_dumped{false};
    static std::atomic<uintptr_t> first_state_caller{0};
    static std::atomic<uintptr_t> second_state_caller{0};
    static std::atomic<bool> ui_event_dumped{false};
    static std::atomic<bool> process_action_advance_dumped{false};
    static std::atomic<bool> process_action_3113_dumped{false};
    static std::atomic<bool> process_action_30003_dumped{false};
    static std::atomic<bool> apt_action_advance_dumped{false};
    static std::atomic<bool> apt_action_3113_dumped{false};
    static std::atomic<bool> apt_action_30003_dumped{false};
    static std::atomic<bool> squad_reader_dumped{false};
    static std::atomic<bool> squad_caller_dumped{false};
    std::atomic<bool>* boolean_guard = nullptr;
    const wchar_t* filename = nullptr;
    const char* tag = nullptr;
    uintptr_t address = reinterpret_cast<uintptr_t>(caller);
    if (strcmp(label, "profile") == 0) {
        boolean_guard = &profile_dumped;
        filename = L"fifa17-revival-profile-caller.bin";
        tag = "profile-caller";
    } else if (strcmp(label, "state-consumer") == 0) {
        uintptr_t expected = 0;
        if (first_state_caller.compare_exchange_strong(
                expected, address, std::memory_order_acq_rel)) {
            filename = L"fifa17-revival-state-consumer-caller.bin";
            tag = "state-consumer-caller-1";
        } else if (expected == address) {
            return;
        } else {
            expected = 0;
            if (second_state_caller.compare_exchange_strong(
                    expected, address, std::memory_order_acq_rel)) {
                filename = L"fifa17-revival-state-consumer-caller-2.bin";
                tag = "state-consumer-caller-2";
            } else {
                return;
            }
        }
    } else if (strcmp(label, "ui-event") == 0) {
        boolean_guard = &ui_event_dumped;
        filename = L"fifa17-revival-ui-event-caller.bin";
        tag = "ui-event-caller";
    } else if (strcmp(label, "registration") == 0) {
        static std::atomic<bool> registration_dumped{false};
        boolean_guard = &registration_dumped;
        filename = L"fifa17-revival-registration-caller.bin";
        tag = "registration-caller";
    } else if (strcmp(label, "process-action-advance") == 0) {
        boolean_guard = &process_action_advance_dumped;
        filename = L"fifa17-revival-process-action-advance-caller.bin";
        tag = "process-action-advance-caller";
    } else if (strcmp(label, "process-action-3113") == 0) {
        boolean_guard = &process_action_3113_dumped;
        filename = L"fifa17-revival-process-action-3113-caller.bin";
        tag = "process-action-3113-caller";
    } else if (strcmp(label, "process-action-30003") == 0) {
        boolean_guard = &process_action_30003_dumped;
        filename = L"fifa17-revival-process-action-30003-caller.bin";
        tag = "process-action-30003-caller";
    } else if (strcmp(label, "apt-action-advance") == 0) {
        boolean_guard = &apt_action_advance_dumped;
        filename = L"fifa17-revival-apt-action-advance-caller.bin";
        tag = "apt-action-advance-caller";
    } else if (strcmp(label, "apt-action-3113") == 0) {
        boolean_guard = &apt_action_3113_dumped;
        filename = L"fifa17-revival-apt-action-3113-caller.bin";
        tag = "apt-action-3113-caller";
    } else if (strcmp(label, "apt-action-30003") == 0) {
        boolean_guard = &apt_action_30003_dumped;
        filename = L"fifa17-revival-apt-action-30003-caller.bin";
        tag = "apt-action-30003-caller";
    } else if (strcmp(label, "squad-reader") == 0) {
        boolean_guard = &squad_reader_dumped;
        filename = L"fifa17-revival-squad-reader.bin";
        tag = "squad-reader";
    } else if (strcmp(label, "squad-caller") == 0) {
        boolean_guard = &squad_caller_dumped;
        filename = L"fifa17-revival-squad-caller.bin";
        tag = "squad-caller";
    } else {
        return;
    }
    if (boolean_guard != nullptr &&
        boolean_guard->exchange(true, std::memory_order_acq_rel)) {
        return;
    }
    if (!dump_va_window(address, 0x20000, 0x20000, filename, "FUT-CALLER", tag)) {
        if (boolean_guard != nullptr) {
            boolean_guard->store(false, std::memory_order_release);
        }
    }
}

void capture_squad_guard_runtime_callsites() {
    const uintptr_t base =
        reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (base == 0) return;
    capture_fut_runtime_callsite(
        "squad-reader", reinterpret_cast<void*>(base + 0x71B8640));
    capture_fut_runtime_callsite(
        "squad-caller", reinterpret_cast<void*>(base + 0x7155020));
}

bool apply_protossl_accept_patch() {
    static bool already = false;
    if (already) return false;
    already = true;
    bool a = patch_skip_cert_alert();
    bool b = patch_cn_verify_accept();
    log_line("[PATCH] cert-accept patches applied: name-check=%s cn-verify=%s",
             a ? "yes" : "no", b ? "yes" : "no");
    return a || b;
}

namespace {

struct OriginMarkerPatch {
    const char* marker;
    const char* name;
    uintptr_t target;
    bool installed;
};

uintptr_t find_marker_function(const char* marker) {
    HMODULE module = GetModuleHandleW(nullptr);
    MODULEINFO info = {0};
    if (!GetModuleInformation(GetCurrentProcess(), module, &info, sizeof(info))) return 0;

    const uintptr_t image_start = reinterpret_cast<uintptr_t>(info.lpBaseOfDll);
    const uintptr_t image_end = image_start + info.SizeOfImage;
    const size_t marker_len = strlen(marker);
    std::vector<uintptr_t> marker_vas;

    uintptr_t addr = image_start;
    while (addr < image_end) {
        MEMORY_BASIC_INFORMATION mbi = {0};
        if (!region_ok(reinterpret_cast<void*>(addr), mbi)) {
            addr += 0x1000;
            continue;
        }
        uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        uintptr_t region_end = region_start + mbi.RegionSize;
        uintptr_t scan_start = region_start < image_start ? image_start : region_start;
        uintptr_t scan_end = region_end > image_end ? image_end : region_end;
        if (scan_end > scan_start) {
            auto hits = find_all(
                reinterpret_cast<unsigned char*>(scan_start), scan_end - scan_start,
                reinterpret_cast<const unsigned char*>(marker), marker_len);
            for (size_t hit : hits) marker_vas.push_back(scan_start + hit);
        }
        addr = region_end;
    }
    if (marker_vas.empty()) return 0;

    addr = image_start;
    while (addr < image_end) {
        MEMORY_BASIC_INFORMATION mbi = {0};
        if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) break;
        uintptr_t region_start = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        uintptr_t region_end = region_start + mbi.RegionSize;
        uintptr_t scan_start = region_start < image_start ? image_start : region_start;
        uintptr_t scan_end = region_end > image_end ? image_end : region_end;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
            region_executable(mbi) && scan_end > scan_start) {
            auto* bytes = reinterpret_cast<unsigned char*>(scan_start);
            const size_t span = scan_end - scan_start;
            for (size_t i = 0; i + 7 <= span; ++i) {
                if ((bytes[i] != 0x48 && bytes[i] != 0x4C) || bytes[i + 1] != 0x8D ||
                    (bytes[i + 2] & 0xC7) != 0x05) {
                    continue;
                }
                int32_t displacement = 0;
                memcpy(&displacement, bytes + i + 3, sizeof(displacement));
                const uintptr_t instruction = scan_start + i;
                const uintptr_t target = instruction + 7 + displacement;
                bool matches = false;
                for (uintptr_t marker_va : marker_vas) {
                    if (target >= marker_va && target < marker_va + marker_len) {
                        matches = true;
                        break;
                    }
                }
                if (!matches) continue;

                DWORD64 function_image_base = 0;
                PRUNTIME_FUNCTION runtime = RtlLookupFunctionEntry(
                    static_cast<DWORD64>(instruction), &function_image_base, nullptr);
                if (runtime && function_image_base != 0) {
                    uintptr_t function = static_cast<uintptr_t>(function_image_base) +
                                         runtime->BeginAddress;
                    if (function >= image_start && function < image_end) return function;
                }
            }
        }
        addr = region_end;
    }
    return 0;
}

bool install_absolute_jump(uintptr_t function, uintptr_t target) {
    unsigned char stub[12] = {0x48, 0xB8};
    memcpy(stub + 2, &target, sizeof(target));
    stub[10] = 0xFF;
    stub[11] = 0xE0;

    auto* entry = reinterpret_cast<unsigned char*>(function);
    if (memcmp(entry, stub, sizeof(stub)) == 0) return true;
    return write_code(entry, stub, sizeof(stub));
}

}

int apply_fake_origin_patches() {
    static OriginMarkerPatch patches[] = {
        {"OriginCheckOnline entered", "OriginCheckOnline",
         reinterpret_cast<uintptr_t>(&OriginCheckOnline), false},
        {"OriginRequestAuthCodeSync entered", "OriginRequestAuthCodeSync",
         reinterpret_cast<uintptr_t>(&OriginRequestAuthCodeSync), false},
        {"OriginStartup entered", "OriginStartup",
         reinterpret_cast<uintptr_t>(&OriginStartup), false},
        {"OriginGetGameInfoSync entered", "OriginGetGameInfoSync",
         reinterpret_cast<uintptr_t>(&OriginGetGameInfoSync), false},
        {"OriginGetDefaultUser entered", "OriginGetDefaultUser",
         reinterpret_cast<uintptr_t>(&OriginGetDefaultUser), false},
        {"OriginDestroyHandle entered", "OriginDestroyHandle",
         reinterpret_cast<uintptr_t>(&OriginDestroyHandle), false},
        {"OriginGetProfile entered", "OriginGetProfile",
         reinterpret_cast<uintptr_t>(&OriginGetProfile), false},
        {"OriginGetProfileSync entered", "OriginGetProfileSync",
         reinterpret_cast<uintptr_t>(&OriginGetProfileSync), false},
        {"OriginUpdate entered", "OriginUpdate",
         reinterpret_cast<uintptr_t>(&OriginUpdate), false},
        {"OriginQueryFriends entered", "OriginQueryFriends",
         reinterpret_cast<uintptr_t>(&OriginQueryFriends), false},
        {"OriginQueryBlockedUsers entered", "OriginQueryBlockedUsers",
         reinterpret_cast<uintptr_t>(&OriginQueryBlockedUsers), false},
        {"OriginReadEnumerationSync entered", "OriginReadEnumerationSync",
         reinterpret_cast<uintptr_t>(&OriginReadEnumerationSync), false},
        {"OriginRegisterEventCallback entered", "OriginRegisterEventCallback",
         reinterpret_cast<uintptr_t>(&OriginRegisterEventCallback), false},
        {"OriginUnregisterEventCallback entered", "OriginUnregisterEventCallback",
         reinterpret_cast<uintptr_t>(&OriginUnregisterEventCallback), false},
    };

    int installed = 0;
    for (auto& patch : patches) {
        if (!patch.installed) {
            uintptr_t function = find_marker_function(patch.marker);
            if (function != 0 && install_absolute_jump(function, patch.target)) {
                patch.installed = true;
                log_line("[ORIGIN-PATCH] %s redirected at 0x%llx",
                         patch.name, (unsigned long long)function);
            }
        }
        if (patch.installed) installed++;
    }
    return installed;
}

}
