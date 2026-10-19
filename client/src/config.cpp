// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

#include <cstdarg>
#include <cstdio>
#include <mutex>
#include <share.h>

namespace revival {

namespace {

std::string trim(const std::string& value) {
    size_t begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) return "";
    size_t end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

std::string lower(std::string value) {
    for (char& ch : value) ch = static_cast<char>(::tolower(static_cast<unsigned char>(ch)));
    return value;
}

int to_int(const std::string& value, int fallback) {
    try {
        size_t consumed = 0;
        int parsed = std::stoi(value, &consumed);
        return consumed == value.size() ? parsed : fallback;
    } catch (...) {
        return fallback;
    }
}

bool to_bool(const std::string& value, bool fallback) {
    std::string v = lower(trim(value));
    if (v == "1" || v == "true" || v == "yes" || v == "on") return true;
    if (v == "0" || v == "false" || v == "no" || v == "off") return false;
    return fallback;
}

HMODULE self_module() {
    HMODULE module = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&self_module), &module);
    return module;
}

std::mutex g_log_mutex;
FILE* g_log = nullptr;

}

std::wstring module_directory() {
    wchar_t path[MAX_PATH] = {0};
    GetModuleFileNameW(self_module(), path, MAX_PATH);
    std::wstring wide(path);
    size_t slash = wide.find_last_of(L"\\/");
    return (slash == std::wstring::npos) ? L"." : wide.substr(0, slash);
}

Config parse_config(const std::string& ini_text) {
    Config config;
    std::string section;
    size_t pos = 0;
    while (pos < ini_text.size()) {
        size_t eol = ini_text.find('\n', pos);
        std::string raw = ini_text.substr(pos, eol == std::string::npos ? std::string::npos : eol - pos);
        pos = (eol == std::string::npos) ? ini_text.size() : eol + 1;

        std::string line = trim(raw);
        if (line.empty() || line[0] == ';' || line[0] == '#') continue;
        if (line.front() == '[' && line.back() == ']') {
            section = lower(trim(line.substr(1, line.size() - 2)));
            continue;
        }
        size_t equals = line.find('=');
        if (equals == std::string::npos) continue;
        std::string key = lower(trim(line.substr(0, equals)));
        std::string value = trim(line.substr(equals + 1));

        if (section == "login") {
            if (key == "host") config.host = value;
            else if (key == "port") config.redirector_port = to_int(value, config.redirector_port);
            else if (key == "debug") config.debug = to_bool(value, config.debug);
        } else if (section == "credentials") {
            if (key == "username") config.username = value;
            else if (key == "password") config.password = value;
        } else if (section == "patch") {
            if (key == "accept_certs") config.patch_accept_certs = to_bool(value, false);
            else if (key == "fut_probes") config.patch_fut_probes = to_bool(value, false);
            else if (key == "origin_gameinfo_table") {
                config.origin_gameinfo_table = to_bool(value, false);
            }
            else if (key == "fifa_points") config.patch_fifa_points = to_bool(value, true);
            else if (key == "recon") config.recon = to_bool(value, false);
            else if (key == "transfer_pile_capacity") {
                config.patch_transfer_pile_capacity = to_bool(value, true);
            }
            else if (key == "force_profile_advance") {
                config.force_profile_advance = to_bool(value, false);
            }
            else if (key == "apt_vm_probe") {
                config.apt_vm_probe = to_bool(value, false);
            }
            else if (key == "apt_byte_watch") {
                config.apt_byte_watch = to_bool(value, false);
            }
            else if (key == "script_publish_watch") {
                config.script_publish_watch = to_bool(value, false);
            }
            else if (key == "futdb_request_watch") {
                config.futdb_request_watch = to_bool(value, false);
            }
            else if (key == "squad_rename_guard") {
                config.squad_rename_guard = to_bool(value, true);
            }
            else if (key == "force_flux_components_ready") {
                config.force_flux_components_ready = to_bool(value, false);
            }
            else if (key == "apt_patch") config.apt_patch = value;
        } else if (section == "server") {
            if (key == "login_port") config.login_port = to_int(value, config.login_port);
            else if (key == "fut_port") config.fut_port = to_int(value, config.fut_port);
            else if (key == "cdn_port") config.cdn_port = to_int(value, config.cdn_port);
            else if (key == "blaze_port") config.blaze_port = to_int(value, config.blaze_port);
            else if (key == "certificate_pin") config.certificate_pin = value;
        }
    }
    return config;
}

std::wstring config_path_from_env_or_exe() {
    wchar_t env[MAX_PATH] = {0};
    DWORD n = GetEnvironmentVariableW(L"FIFA17_REVIVAL_CONFIG", env, MAX_PATH);
    if (n > 0 && n < MAX_PATH) {
        return env;
    }
    return module_directory() + L"\\fifa17-revival.ini";
}

Config load_config() {
    const std::wstring path = config_path_from_env_or_exe();
    // Keep filesystem paths wide. UTF-8 is only for the diagnostic string;
    // narrow CRT file APIs interpret it using the Windows system code page.
    const int source_size = WideCharToMultiByte(
        CP_UTF8, 0, path.data(), static_cast<int>(path.size()), nullptr, 0, nullptr, nullptr);
    std::string source_path(source_size, '\0');
    if (source_size > 0) {
        WideCharToMultiByte(CP_UTF8, 0, path.data(), static_cast<int>(path.size()),
                            source_path.data(), source_size, nullptr, nullptr);
    }
    Config config;
    config.source_path = source_path;

    FILE* file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"rb") == 0 && file) {
        std::string text;
        char buffer[4096];
        size_t read = 0;
        while ((read = fread(buffer, 1, sizeof(buffer), file)) > 0) text.append(buffer, read);
        fclose(file);
        config = parse_config(text);
        config.source_path = source_path;
        config.loaded_from_file = true;
    }
    return config;
}

void log_open(const Config& config) {
    if (!config.debug) return;
    std::lock_guard<std::mutex> guard(g_log_mutex);
    if (g_log) return;

    std::wstring logfile = module_directory() + L"\\fifa17-revival-log.txt";
    g_log = _wfsopen(logfile.c_str(), L"w", _SH_DENYNO);
}

void log_line(const char* fmt, ...) {
    std::lock_guard<std::mutex> guard(g_log_mutex);
    if (!g_log) return;
    SYSTEMTIME now;
    GetLocalTime(&now);
    fprintf(g_log, "[%02d:%02d:%02d.%03d] ", now.wHour, now.wMinute, now.wSecond, now.wMilliseconds);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log, fmt, args);
    va_end(args);
    fprintf(g_log, "\n");
    fflush(g_log);
}

void log_close() {
    std::lock_guard<std::mutex> guard(g_log_mutex);
    if (g_log) {
        fclose(g_log);
        g_log = nullptr;
    }
}

}
