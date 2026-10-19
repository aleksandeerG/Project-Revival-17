// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#pragma once

#include <windows.h>
#include <string>
#include <vector>

namespace revival {

struct HostnameTarget {
    const char* name;
    size_t length;
};

inline const std::vector<HostnameTarget>& hostname_targets() {
    static const std::vector<HostnameTarget> targets = {
        {"winter15.gosredirector.stest.ea.com", 35},
        {"winter15.gosredirector.scert.ea.com", 35},
        {"winter15.gosredirector.sdev.ea.com", 34},
        {"winter15.gosredirector.ea.com", 29},
        {"demangler.ea.com", 16},
    };
    return targets;
}

inline size_t shortest_hostname_target() {
    size_t shortest = SIZE_MAX;
    for (const auto& target : hostname_targets()) {
        if (target.length < shortest) shortest = target.length;
    }
    return shortest;
}

struct Config {
    std::string host = "127.0.0.1";
    int redirector_port = 42230;
    bool debug = true;

    std::string username;
    std::string password;
    std::string certificate_pin;

    bool patch_accept_certs = false;

    bool patch_fut_probes = false;

    bool origin_gameinfo_table = false;

    bool patch_fifa_points = true;

    bool patch_transfer_pile_capacity = true;

    bool force_profile_advance = false;

    bool apt_vm_probe = false;

    bool apt_byte_watch = false;

    bool script_publish_watch = false;

    bool futdb_request_watch = false;

    bool force_flux_components_ready = false;
    bool squad_rename_guard = true;
    bool recon = false;

    std::string apt_patch;

    int login_port = 5139;
    int fut_port = 8080;
    int cdn_port = 8080;
    int blaze_port = 44321;

    bool loaded_from_file = false;
    std::string source_path;
};

Config load_config();
Config parse_config(const std::string& ini_text);
std::wstring config_path_from_env_or_exe();
std::wstring module_directory();

void log_open(const Config& config);
void log_line(const char* fmt, ...);

void install_crash_reporter();
void log_close();

struct HostPatchResult {
    int patched = 0;
    int skipped_too_long = 0;
    int not_found = 0;
};
HostPatchResult patch_hostnames_in_buffer(unsigned char* buffer, size_t size,
                                          const std::string& new_host);
HostPatchResult patch_hostnames_in_main_module(const std::string& new_host);

int apply_game_file_io_trace();

int apply_module_load_trace();

bool poll_loaded_modules();

void recon_protossl_modules();
void recon_protossl_strings();
int recon_protossl_xrefs();
bool recon_protossl_dump_module();

bool recon_fire2_dump();

bool apply_fut_phase_probe();
bool apply_fut_login_flow_probe();

bool certificate_patch_done();
void set_certificate_patch_done();

void set_recon_enabled(bool enabled);
bool recon_enabled();

int recon_fut_event_publishers();

int build_ui_registry();

void write_ui_registry_file();

const char* ui_registry_describe(uint32_t id, char* out, size_t capacity);

int probe_fut_frontend_residency(bool after_fut);

int probe_fut_frontend_residency_ex(bool after_fut, bool priority_only);

void init_screen_tracking();

void request_fut_residency_scan();
bool consume_fut_residency_request();

int recon_users_club_callers();

bool apply_apt_force_patch(const Config& config);

bool apply_flux_components_ready_patch(uintptr_t hint = 0,
                                       bool near_only = false,
                                       bool synchronize_watch = false);

bool prepare_flux_opcode_watch(uintptr_t load_movie_opcode,
                               uintptr_t initialize_screen_opcode,
                               DWORD timeout_ms);

void configure_fut_profile_advance(bool enabled);
void configure_fut_apt_vm_probe(bool enabled);
void configure_fut_script_publish_probe(bool enabled);
void configure_flux_components_ready(bool enabled);

bool install_squad_null_guard_patch(HMODULE module);

uint32_t squad_guard_hits();

void* squad_guard_object();
bool squad_input_capture_active();
void finish_squad_input_capture();
void capture_squad_guard_runtime_callsites();
bool consume_flux_components_ready_request();

inline constexpr uint32_t kCardsDllTimeDateStamp = 0x593B2C2C;
inline constexpr uint32_t kCardsDllSizeOfImage = 0x0031D000;
inline constexpr uint32_t kFifaPointsPatchRva = 0x000E2EFB;
inline constexpr size_t kFifaPointsPatchLength = 15;
extern const unsigned char kFifaPointsOriginal[kFifaPointsPatchLength];
extern const unsigned char kFifaPointsReplacement[kFifaPointsPatchLength];

enum class PointsSite {
    Original,
    AlreadyPatched,
    Unrecognised,
};
PointsSite classify_fifa_points_site(const unsigned char* bytes, size_t length);

bool apply_fifa_points_patch();

bool apply_transfer_pile_capacity_patch();

void origin_set_gameinfo_table(bool enabled);

bool recon_online_verdict();

bool recon_authentication_dump();

bool recon_util_dump();

bool recon_census_dump();

bool recon_fut_dump();

bool apply_fut_accountinfo_probe();

bool apply_fut_navigation_probe();

bool apply_fut_script_publish_probe();

DWORD WINAPI fut_submit_watch_worker(LPVOID);

bool prepare_apt_byte_watch_for_profile(DWORD timeout_ms);

bool prepare_futdb_request_watch(uintptr_t request_site, DWORD timeout_ms);

void request_futdb_watch_from_gate();

void set_futdb_watch_enabled(bool enabled);

void log_fut_gate_state(const char* phase);

void retry_deferred_fut_registration();

void capture_fut_runtime_callsite(const char* label, void* caller);

bool apply_protossl_accept_patch();

int apply_fake_origin_patches();

struct AuthResult {
    bool ok = false;
    long status = 0;
    std::string sid;
    std::string persona_id;
    std::string display_name;
    std::string auth_code;
    std::string error;
};
AuthResult accounts_login_and_authorize(const Config& config);

void origin_publish_auth_code(const std::string& auth_code);

DWORD WINAPI worker_main(LPVOID);

}
