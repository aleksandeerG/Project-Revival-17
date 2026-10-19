// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <intrin.h>
#include <mutex>

namespace revival {
namespace {

std::array<char, 256> g_auth_code = {};
size_t g_auth_code_length = 0;
std::mutex g_origin_mutex;

using OriginEnumerationCallback = void(__cdecl *)(
    void* context, void* handle, uint32_t total, uint32_t available,
    int32_t error);

struct PendingEnumeration {
    OriginEnumerationCallback callback = nullptr;
    void* context = nullptr;
};

PendingEnumeration g_friends_enumeration;
PendingEnumeration g_blocked_enumeration;

using OriginProfileCallback = void(__cdecl *)(
    void* context, const void* profile, uint32_t count, int32_t error);

struct PendingProfile {
    OriginProfileCallback callback = nullptr;
    void* context = nullptr;
};

PendingProfile g_profile_request;
alignas(8) std::array<unsigned char, 0x540> g_profile = {};
std::array<char, 32> g_profile_name = {"LocalFUT"};

void prepare_local_profile() {
    g_profile.fill(0);
    constexpr uint64_t kPersonaId = 1'000'001;
    memcpy(g_profile.data(), &kPersonaId, sizeof(kPersonaId));

    const char* name = g_profile_name.data();
    memcpy(g_profile.data() + 0x10, &name, sizeof(name));
    memcpy(g_profile.data() + 0x38, &name, sizeof(name));
    memcpy(g_profile.data() + 0x40, name, strlen(name) + 1);
    memcpy(g_profile.data() + 0x140, name, strlen(name) + 1);
}

void trace_stub_once(const char* name, std::atomic<bool>& seen) {
    if (!seen.exchange(true)) {
        log_line("[ORIGIN] %s called; compatibility body not recovered yet", name);
    }
}

bool is_writable(const void* pointer, size_t bytes) {
    uintptr_t address = reinterpret_cast<uintptr_t>(pointer);
    if (address == 0 || bytes == 0) return false;
    if (address == 0xFFFFFFFFull || address == UINTPTR_MAX) return false;
    if (address >= 0x0000800000000000ull) return false;
    if (address + bytes < address) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(pointer, &mbi, sizeof(mbi)) == 0) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)) return false;
    const DWORD writable = PAGE_READWRITE | PAGE_WRITECOPY |
                           PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    if ((mbi.Protect & writable) == 0) return false;
    uintptr_t region_end = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    return address + bytes <= region_end;
}

}

std::atomic<bool> g_gameinfo_table{false};

void origin_set_gameinfo_table(bool enabled) {
    g_gameinfo_table.store(enabled);
    log_line("[ORIGIN] game-info mode: %s",
             enabled ? "f2457a5 table (capacity-respecting)"
                     : "747db65 legacy ('true' for every type, unconditional)");
}

void origin_publish_auth_code(const std::string& auth_code) {
    std::lock_guard<std::mutex> guard(g_origin_mutex);
    g_auth_code.fill('\0');
    g_auth_code_length = auth_code.size() < g_auth_code.size() - 1
        ? auth_code.size()
        : g_auth_code.size() - 1;
    memcpy(g_auth_code.data(), auth_code.data(), g_auth_code_length);
    log_line("[ORIGIN] published auth code for SDK bridge (length=%zu)", g_auth_code_length);
}

const char* origin_auth_code(size_t* length) {
    std::lock_guard<std::mutex> guard(g_origin_mutex);
    if (length) *length = g_auth_code_length;
    return g_auth_code.data();
}

}

extern "C" __declspec(dllexport) int32_t OriginCheckOnline(unsigned char* online) {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginCheckOnline", seen);
    if (online) *online = 1;
    return 0;
}

extern "C" __declspec(dllexport) uint64_t OriginGetDefaultUser() {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginGetDefaultUser", seen);
    return 1'000'001;
}

extern "C" __declspec(dllexport) int32_t OriginGetErrorDescription(
    int32_t , char* buffer, size_t* length) {
    if (buffer && length && *length > 0) buffer[0] = '\0';
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginRequestAuthCodeSync(
    uint64_t , const char* , const char** auth_code, size_t* length) {
    size_t available = 0;
    const char* code = revival::origin_auth_code(&available);
    if (auth_code) *auth_code = code;
    if (length) *length = available;
    revival::log_line("[ORIGIN] OriginRequestAuthCodeSync returned %zu-byte code", available);
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginStartup() {
    revival::log_line("[ORIGIN] OriginStartup");
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginShutdown() {
    revival::log_line("[ORIGIN] OriginShutdown");
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginUpdate() {
    revival::PendingEnumeration friends;
    revival::PendingEnumeration blocked;
    revival::PendingProfile profile;
    {
        std::lock_guard<std::mutex> guard(revival::g_origin_mutex);
        friends = revival::g_friends_enumeration;
        blocked = revival::g_blocked_enumeration;
        profile = revival::g_profile_request;
        revival::g_friends_enumeration = {};
        revival::g_blocked_enumeration = {};
        revival::g_profile_request = {};
    }
    if (friends.callback) {
        revival::log_line("[ORIGIN] dispatching empty friends enumeration");
        friends.callback(friends.context, nullptr, 0, 0, 0);
        revival::log_line("[ORIGIN] completed empty friends enumeration");
    }
    if (blocked.callback) {
        revival::log_line("[ORIGIN] dispatching empty blocked-users enumeration");
        blocked.callback(blocked.context, nullptr, 0, 0, 0);
        revival::log_line("[ORIGIN] completed empty blocked-users enumeration");
    }
    if (profile.callback) {
        revival::prepare_local_profile();
        constexpr uint64_t kPersonaId = 1'000'001;
        const char* name = revival::g_profile_name.data();
        revival::log_line(
            "[ORIGIN] dispatching local profile callback=%p context=%p profile=%p "
            "personaId=%llu personaNamePtr=%p personaName=%s count=1 error=0",
            reinterpret_cast<void*>(profile.callback), profile.context,
            revival::g_profile.data(), static_cast<unsigned long long>(kPersonaId),
            static_cast<const void*>(name), name);
        profile.callback(profile.context, revival::g_profile.data(), 1, 0);
        revival::log_line("[ORIGIN] local profile callback returned normally");
        revival::log_fut_gate_state("after-profile-callback");
        revival::retry_deferred_fut_registration();
    }
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginGetProfileSync(
    uint64_t user, uint32_t timeout_ms, void* profile, void** handle) {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginGetProfileSync", seen);
    revival::prepare_local_profile();
    revival::log_line(
        "[ORIGIN] OriginGetProfileSync user=%llu timeout=%u profile=%p handle=%p",
        static_cast<unsigned long long>(user), timeout_ms, profile, handle);
    constexpr size_t kFifa17SyncProfileSize = 0x18;
    if (!revival::is_writable(profile, kFifa17SyncProfileSize)) {
        revival::log_line("[ORIGIN] OriginGetProfileSync profile output is not writable");
        return -1;
    }
    memcpy(profile, revival::g_profile.data(), kFifa17SyncProfileSize);
    if (revival::is_writable(handle, sizeof(*handle))) *handle = nullptr;
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginGetProfile(
    uint64_t user, uint32_t timeout_ms,
    revival::OriginProfileCallback callback, void* context) {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginGetProfile", seen);
    void* caller = _ReturnAddress();
    revival::log_line(
        "[ORIGIN] OriginGetProfile user=%llu timeout=%u callback=%p context=%p caller=%p",
        static_cast<unsigned long long>(user), timeout_ms,
        reinterpret_cast<void*>(callback), context, caller);
    revival::capture_fut_runtime_callsite("profile", caller);
    std::lock_guard<std::mutex> guard(revival::g_origin_mutex);
    revival::g_profile_request = {callback, context};
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginQueryFriends(
    uint64_t , revival::OriginEnumerationCallback callback, void* context) {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginQueryFriends", seen);
    std::lock_guard<std::mutex> guard(revival::g_origin_mutex);
    revival::g_friends_enumeration = {callback, context};
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginQueryBlockedUsers(
    uint64_t , revival::OriginEnumerationCallback callback, void* context) {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginQueryBlockedUsers", seen);
    std::lock_guard<std::mutex> guard(revival::g_origin_mutex);
    revival::g_blocked_enumeration = {callback, context};
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginReadEnumerationSync(
    void* handle, void* buffer, size_t buffer_bytes,
    size_t start_index, size_t max_count, size_t* items_read) {
    static std::atomic<bool> seen = false;
    revival::trace_stub_once("OriginReadEnumerationSync", seen);
    revival::log_line(
        "[ORIGIN] OriginReadEnumerationSync handle=%p buffer=%p bytes=%zu start=%zu "
        "max=0x%zx out=%p",
        handle, buffer, buffer_bytes, start_index, max_count, static_cast<void*>(items_read));
    if (revival::is_writable(items_read, sizeof(*items_read))) {
        *items_read = 0;
    } else if (items_read) {
        revival::log_line(
            "[ORIGIN] items_read=%p not a canonical writable pointer; write skipped",
            static_cast<void*>(items_read));
    }
    return 0;
}

extern "C" __declspec(dllexport) int32_t OriginGetGameInfoSync(
    int32_t type, char* value, size_t* length) {
    if (!revival::g_gameinfo_table.load()) {
        constexpr char kLegacy[] = "true";
        constexpr size_t kLegacyLength = sizeof(kLegacy) - 1;
        bool wrote = false;
        if (revival::is_writable(value, sizeof(kLegacy))) {
            memcpy(value, kLegacy, sizeof(kLegacy));
            wrote = true;
        }
        if (revival::is_writable(length, sizeof(*length))) *length = kLegacyLength;
        revival::log_line(
            "[ORIGIN] OriginGetGameInfoSync type=%d legacy value='%s' wrote=%d",
            type, kLegacy, wrote ? 1 : 0);
        return 0;
    }

    static constexpr const char* kValues[] = {
        "", "en_US", "FIFA 17", "false", "true",
    };
    const char* selected = type >= 1 && type <= 4 ? kValues[type] : "";
    const size_t available = strlen(selected);
    size_t capacity = 0;
    if (revival::is_writable(length, sizeof(*length))) {
        capacity = *length;
    }

    size_t copied = 0;
    if (value != nullptr && capacity != 0) {
        copied = (std::min)(available, capacity - 1);
        if (revival::is_writable(value, copied + 1)) {
            memcpy(value, selected, copied);
            value[copied] = '\0';
            *length = copied;
        } else {
            copied = 0;
        }
    }
    revival::log_line(
        "[ORIGIN] OriginGetGameInfoSync type=%d capacity=%zu value='%s' copied=%zu",
        type, capacity, selected, copied);
    return 0;
}

#define ORIGIN_SCAFFOLD(name)                                      \
    extern "C" __declspec(dllexport) int32_t name() {              \
        static std::atomic<bool> seen = false;                      \
        revival::trace_stub_once(#name, seen);                      \
        return 0;                                                   \
    }

ORIGIN_SCAFFOLD(OriginDestroyHandle)
ORIGIN_SCAFFOLD(OriginEnableDebug)
ORIGIN_SCAFFOLD(OriginGetErrorInfo)
ORIGIN_SCAFFOLD(OriginGetPresence)
ORIGIN_SCAFFOLD(OriginGetSettingSync)
ORIGIN_SCAFFOLD(OriginHookDebug)
ORIGIN_SCAFFOLD(OriginRegisterErrorCallback)
ORIGIN_SCAFFOLD(OriginRegisterEventCallback)
ORIGIN_SCAFFOLD(OriginRequestAuthCode)
ORIGIN_SCAFFOLD(OriginRequestFriendUISync)
ORIGIN_SCAFFOLD(OriginSendInvite)
ORIGIN_SCAFFOLD(OriginSetPresence)
ORIGIN_SCAFFOLD(OriginShowFriendsProfileUISync)
ORIGIN_SCAFFOLD(OriginShowIGO)
ORIGIN_SCAFFOLD(OriginUnregisterEventCallback)

#undef ORIGIN_SCAFFOLD
