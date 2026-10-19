// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

namespace revival {

namespace {

constexpr int kMaxHostnamePasses = 60;
constexpr DWORD kPassIntervalMs = 500;

DWORD WINAPI verdict_recon_worker(LPVOID) {
    constexpr int kMaxPasses = 1200;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        if (recon_online_verdict()) return 0;
        Sleep(1000);
    }
    log_line("[VERDICT] some anchors were never referenced by decrypted code; a "
             "message may be produced from a table rather than a direct string "
             "reference, or its screen was never reached this run");
    return 0;
}

DWORD WINAPI fifa_points_worker(LPVOID) {
    bool applied = false;
    for (;;) {
        const bool now = apply_fifa_points_patch();
        if (now != applied) {
            applied = now;
            if (!now) {
                log_line("[FIFA POINTS] patch site no longer ours "
                         "(CardsDLL unloaded or reloaded); will re-apply");
            }
        }
        Sleep(20);
    }
}

DWORD WINAPI transfer_pile_capacity_worker(LPVOID) {
    for (;;) {
        if (apply_transfer_pile_capacity_patch()) return 0;
        Sleep(20);
    }
}

DWORD WINAPI club_caller_scan_worker(LPVOID) {
    constexpr int kMaxPasses = 360;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        recon_users_club_callers();
        Sleep(5000);
    }
    log_line("[FUT-CALLERS] nothing referenced the users/club builder within the "
             "scan window; it may be reached through a computed pointer");
    return 0;
}

DWORD WINAPI fut_event_source_scan_worker(LPVOID) {
    constexpr int kMaxPasses = 360;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        recon_fut_event_publishers();
        Sleep(5000);
    }
    return 0;
}

DWORD WINAPI ui_registry_worker(LPVOID) {
    constexpr int kMaxPasses = 240;
    int quiet = 0;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        if (build_ui_registry() > 0) {
            write_ui_registry_file();
            quiet = 0;
        } else if (++quiet == 12) {
            log_line("[UI-REGISTRY] no new registration blocks in the last minute; "
                     "still scanning as pages decrypt");
        }
        Sleep(5000);
    }
    write_ui_registry_file();
    return 0;
}

DWORD WINAPI fut_residency_worker(LPVOID) {
    init_screen_tracking();
    log_line("[FUT-RESIDENT] baseline pass (before FUT entry; reference only)");
    probe_fut_frontend_residency(false);

    constexpr int kMaxWaits = 2400;
    int scans_after_fut = 0;
    for (int i = 0; i < kMaxWaits && scans_after_fut < 6; ++i) {
        if (consume_fut_residency_request()) {
            if (scans_after_fut > 0) Sleep(8000);
            log_line("[FUT-RESIDENT] post-FUT pass %d (triggered by the FUT state store)",
                     scans_after_fut + 1);
            probe_fut_frontend_residency(true);
            scans_after_fut++;
            if (scans_after_fut < 6) request_fut_residency_scan();
            continue;
        }
        Sleep(500);
    }
    return 0;
}

DWORD WINAPI module_watch_worker(LPVOID) {
    constexpr int kMaxPasses = 3600;
    int quiet = 0;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        if (poll_loaded_modules()) return 0;
        if (++quiet % 240 == 0) {
            log_line("[FUT-MODULE] still no CardsDLL_Win64_retail.dll after %d s",
                     quiet / 2);
        }
        Sleep(500);
    }
    return 0;
}

DWORD WINAPI apt_force_worker(LPVOID parameter) {
    const Config* config = reinterpret_cast<const Config*>(parameter);
    constexpr int kMaxPasses = 600;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        if (apply_apt_force_patch(*config)) return 0;
        Sleep(500);
    }
    log_line("[APT-FORCE] the configured APT bytes never appeared; the stream may "
             "not be loaded, or the signature does not match this build");
    return 0;
}

DWORD WINAPI flux_components_ready_worker(LPVOID) {
    constexpr int kMaxWaits = 2400;
    for (int wait = 0; wait < kMaxWaits; ++wait) {
        if (!consume_flux_components_ready_request()) {
            Sleep(500);
            continue;
        }
        for (int attempt = 0; attempt < 20; ++attempt) {
            if (apply_flux_components_ready_patch()) return 0;
            Sleep(250);
        }
        log_line("[FUT-FLUX-WAIT] validated FluxHub wait site did not become "
                 "uniquely locatable within five seconds of FLUX_COMPONENTS_DP");
    }
    log_line("[FUT-FLUX-WAIT] no FLUX_COMPONENTS_DP trigger within twenty minutes");
    return 0;
}

DWORD WINAPI fut_phase_probe_worker(LPVOID) {
    constexpr int kMaxPasses = 1200;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        if (apply_fut_phase_probe()) return 0;
        Sleep(500);
    }
    log_line("[FUT-PHASE] phase handler never decrypted within the window");
    return 0;
}

DWORD WINAPI cert_patch_worker(LPVOID parameter) {
    const bool accept_certs = parameter != nullptr;

    recon_protossl_modules();
    recon_protossl_strings();

    constexpr int kMaxXrefPasses = 90;
    constexpr DWORD kXrefIntervalMs = 1000;
    bool dumped = false, module_dumped = false;
    for (int pass = 0; pass < kMaxXrefPasses; ++pass) {
        int n = recon_protossl_xrefs();
        if (n > 0) dumped = true;
        if (!module_dumped) module_dumped = recon_protossl_dump_module();
        if ((dumped || n < 0) && module_dumped) break;
        Sleep(kXrefIntervalMs);
    }
    if (!dumped) {
        log_line("[SSL] xref recon found nothing; the cert code may not have "
                 "decrypted within the window, or references the anchors indirectly");
    }

    if (accept_certs) {
        if (module_dumped) {
            apply_protossl_accept_patch();
        } else {
            log_line("[PATCH] skipped: cert code never decrypted this run");
        }
    } else {
        log_line("[PATCH] accept_certs disabled in config; observing only");
    }
    set_certificate_patch_done();
    return 0;
}

void log_object_ascii(const char* label, const uintptr_t* words, int bytes) {
    const auto* raw = reinterpret_cast<const unsigned char*>(words);
    char ascii[200];
    size_t at = 0;
    for (int i = 0; i < bytes && at + 1 < sizeof(ascii); ++i) {
        const unsigned char c = raw[i];
        ascii[at++] = (c >= 32 && c < 127) ? (char)c : '.';
    }
    ascii[at] = '\0';
    log_line("[SQUAD-GUARD] %s ascii: %s", label, ascii);
}

DWORD WINAPI squad_guard_worker(LPVOID) {
    bool installed = false;
    for (int pass = 0; pass < 12000; ++pass) {
        if (install_squad_null_guard_patch(GetModuleHandleW(nullptr))) {
            installed = true;
            break;
        }
        Sleep(250);
    }
    if (!installed) {
        log_line("[SQUAD-GUARD] never saw the expected bytes; guard not installed");
        return 0;
    }
    uint32_t reported = 0;
    bool key_down[256] = {};
    char entered[33] = {};
    size_t entered_length = 0;
    ULONGLONG last_character_at = 0;
    for (;;) {
        DWORD foreground_pid = 0;
        GetWindowThreadProcessId(GetForegroundWindow(), &foreground_pid);
        if (foreground_pid == GetCurrentProcessId() &&
            squad_input_capture_active()) {
            const bool modified = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0 ||
                                  (GetAsyncKeyState(VK_MENU) & 0x8000) != 0;
            for (int key = VK_BACK; key <= 'Z'; ++key) {
                const bool relevant = key == VK_BACK || key == VK_SPACE ||
                                      (key >= '0' && key <= '9') ||
                                      (key >= 'A' && key <= 'Z');
                if (!relevant) continue;
                const bool down = (GetAsyncKeyState(key) & 0x8000) != 0;
                if (down && !key_down[key]) {
                    const ULONGLONG now = GetTickCount64();
                    if (key == VK_BACK) {
                        if (entered_length != 0) entered[--entered_length] = '\0';
                    } else if (!modified) {
                        if (last_character_at != 0 && now - last_character_at > 2000) {
                            entered_length = 0;
                            entered[0] = '\0';
                        }
                        if (entered_length < 32) {
                            char character = key == VK_SPACE
                                                 ? ' '
                                                 : static_cast<char>(key);
                            entered[entered_length++] = character;
                            entered[entered_length] = '\0';
                            last_character_at = now;
                        }
                    }
                }
                key_down[key] = down;
            }
        }
        const uint32_t hits = squad_guard_hits();
        if (hits != reported) {
            log_line("[SQUAD-GUARD] tid=%lu null branch taken %u time(s)",
                     GetCurrentThreadId(), hits);
            reported = hits;
            const ULONGLONG now = GetTickCount64();
            const ULONGLONG age = last_character_at == 0
                                      ? ~0ULL : now - last_character_at;
            if (entered_length != 0 && age <= 2000) {
                log_line("[SQUAD-INPUT] candidate='%s' ageMs=%llu", entered,
                         (unsigned long long)age);
            } else {
                log_line("[SQUAD-INPUT] no recent candidate");
            }
            entered_length = 0;
            entered[0] = '\0';
            last_character_at = 0;
            finish_squad_input_capture();
            capture_squad_guard_runtime_callsites();
            auto* object = reinterpret_cast<const uintptr_t*>(
                squad_guard_object());
            MEMORY_BASIC_INFORMATION info{};
            const bool readable =
                object != nullptr &&
                VirtualQuery(object, &info, sizeof(info)) != 0 &&
                info.State == MEM_COMMIT &&
                (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)) == 0;
            if (!readable) {
                log_line("[SQUAD-GUARD] object 0x%llx not readable",
                         (unsigned long long)reinterpret_cast<uintptr_t>(object));
                Sleep(20);
                continue;
            }
            char text[900];
            text[0] = '\0';
            for (int i = 0; i < 16; ++i) {
                char cell[64];
                _snprintf_s(cell, sizeof(cell), _TRUNCATE, "+0x%02x=0x%llx%s ",
                            i * 8, (unsigned long long)object[i],
                            object[i] == 0 ? "(NULL)" : "");
                strncat_s(text, sizeof(text), cell, _TRUNCATE);
            }
            log_line("[SQUAD-GUARD] object 0x%llx -> %s",
                     (unsigned long long)reinterpret_cast<uintptr_t>(object),
                     text);
            log_object_ascii("object", object, 128);

            for (int i = 0; i < 16; ++i) {
                const uintptr_t value = object[i];
                if (value < 0x10000 || value > 0x7FFFFFFFFFFFull) continue;
                const auto* target = reinterpret_cast<const uintptr_t*>(value);
                MEMORY_BASIC_INFORMATION at{};
                if (VirtualQuery(target, &at, sizeof(at)) == 0 ||
                    at.State != MEM_COMMIT ||
                    (at.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) {
                    continue;
                }
                char label[48];
                _snprintf_s(label, sizeof(label), _TRUNCATE,
                            "+0x%02x -> 0x%llx", i * 8,
                            (unsigned long long)value);
                log_object_ascii(label, target, 64);
            }
        }
        Sleep(10);
    }
    return 0;
}

DWORD WINAPI fut_probe_worker(LPVOID) {
    log_line("[FUT-PROBE] waiting for the accountinfo parser to decrypt");
    constexpr int kMaxPasses = 6000;
    for (int pass = 0; pass < kMaxPasses; ++pass) {
        if (apply_fut_accountinfo_probe()) {
            bool navigation_ready = false;
            bool login_flow_ready = false;
            bool script_publish_ready = false;
            for (int flow_pass = 0; flow_pass < 1200; ++flow_pass) {
                if (!navigation_ready) {
                    navigation_ready = apply_fut_navigation_probe();
                }
                if (!login_flow_ready) {
                    login_flow_ready = apply_fut_login_flow_probe();
                }
                if (!script_publish_ready) {
                    script_publish_ready = apply_fut_script_publish_probe();
                }
                if (navigation_ready && login_flow_ready &&
                    script_publish_ready) return 0;
                Sleep(50);
            }
            log_line(
                "[FUT-PROBE] late probes incomplete after one minute: "
                "navigation=%d loginFlow=%d scriptPublish=%d",
                navigation_ready ? 1 : 0, login_flow_ready ? 1 : 0,
                script_publish_ready ? 1 : 0);
            return 0;
        }
        Sleep(certificate_patch_done() ? 50 : 500);
    }
    log_line("[FUT-PROBE] parser did not decrypt within five minutes");
    return 0;
}

}

DWORD WINAPI worker_main(LPVOID) {
    Config config = load_config();
    log_open(config);
    set_recon_enabled(config.recon);

    log_line("=== FIFA 17 FUT Revival shim loaded (build %s %s) ===", __DATE__, __TIME__);
    if (config.loaded_from_file) {
        log_line("[CFG] config: %s", config.source_path.c_str());
    } else {
        log_line("[CFG] no config file at %s; using defaults", config.source_path.c_str());
    }
    log_line("[CFG] host=%s redirector_port=%d login_port=%d blaze_port=%d",
             config.host.c_str(), config.redirector_port, config.login_port, config.blaze_port);
    if (config.host.size() > shortest_hostname_target()) {
        log_line("[CFG] WARNING: host is longer than the shortest EA hostname (%zu); "
                 "some hostnames cannot be patched. Use an address <= %zu characters.",
                 shortest_hostname_target(), shortest_hostname_target());
    }

    install_crash_reporter();

    if (config.squad_rename_guard) {
        HANDLE squad_guard_thread =
            CreateThread(nullptr, 0, squad_guard_worker, nullptr, 0, nullptr);
        if (squad_guard_thread != nullptr) {
            CloseHandle(squad_guard_thread);
        } else {
            log_line("[SQUAD-GUARD] failed to start worker: error=%lu",
                     GetLastError());
        }
    } else {
        log_line("[SQUAD-GUARD] disabled ([Patch] squad_rename_guard=0)");
    }

    origin_set_gameinfo_table(config.origin_gameinfo_table);
    configure_fut_profile_advance(config.force_profile_advance);
    configure_fut_apt_vm_probe(config.apt_vm_probe);
    configure_fut_script_publish_probe(config.script_publish_watch);
    configure_flux_components_ready(config.force_flux_components_ready);

    if (config.force_flux_components_ready) {
        HANDLE flux_wait_thread =
            CreateThread(nullptr, 0, flux_components_ready_worker, nullptr, 0, nullptr);
        if (flux_wait_thread != nullptr) CloseHandle(flux_wait_thread);
    }

    HANDLE cert_thread = CreateThread(
        nullptr, 0, cert_patch_worker,
        config.patch_accept_certs ? reinterpret_cast<LPVOID>(1) : nullptr, 0, nullptr);

    if (config.patch_fut_probes) {
        int file_hooks = apply_game_file_io_trace();
        log_line("[FUT-FILE] installed %d/3 game file/read hooks", file_hooks);

        set_futdb_watch_enabled(config.futdb_request_watch);
        log_line("[FUT-DB] %s ([Patch] futdb_request_watch=%d)",
                 config.futdb_request_watch
                     ? "armed; will watch the loadFUTDatabase request site when "
                       "checkFUTRostersFlow is entered"
                     : "disabled",
                 config.futdb_request_watch ? 1 : 0);

        const int module_hooks = apply_module_load_trace();
        log_line("[FUT-MODULE] installed %d/2 LoadLibrary hooks (0 is normal for "
                 "the packed image; the poller is the definitive check)",
                 module_hooks);
        HANDLE module_thread =
            CreateThread(nullptr, 0, module_watch_worker, nullptr, 0, nullptr);
        if (module_thread != nullptr) CloseHandle(module_thread);

        const uintptr_t watch_flags = config.apt_byte_watch ? 1u : 0u;
        HANDLE submit_watch_thread =
            CreateThread(nullptr, 0, fut_submit_watch_worker,
                         reinterpret_cast<LPVOID>(watch_flags),
                         0, nullptr);
        if (submit_watch_thread != nullptr) CloseHandle(submit_watch_thread);

        HANDLE registry_thread =
            CreateThread(nullptr, 0, ui_registry_worker, nullptr, 0, nullptr);
        if (registry_thread != nullptr) CloseHandle(registry_thread);

    } else {
        log_line("[FUT-PROBE] disabled ([Patch] fut_probes=0); no reconnaissance "
                 "detours are installed into the game this run");
    }

    if (config.patch_fut_probes || config.force_flux_components_ready) {
        HANDLE fut_probe_thread =
            CreateThread(nullptr, 0, fut_probe_worker, nullptr, 0, nullptr);
        if (fut_probe_thread != nullptr) CloseHandle(fut_probe_thread);
        if (!config.patch_fut_probes) {
            log_line("[FUT-FLUX-WAIT] fut_probes=0; installing only the detour "
                     "chain the FluxHub bypass needs");
        }
    }

    if (config.patch_fifa_points) {
        HANDLE points_thread = CreateThread(nullptr, 0, fifa_points_worker, nullptr, 0, nullptr);
        if (points_thread != nullptr) CloseHandle(points_thread);
    } else {
        log_line("[FIFA POINTS] disabled ([Patch] fifa_points=0); the balance will "
                 "use the game's own DIME path");
    }

    if (config.patch_transfer_pile_capacity) {
        HANDLE pile_thread = CreateThread(
            nullptr, 0, transfer_pile_capacity_worker, nullptr, 0, nullptr);
        if (pile_thread != nullptr) CloseHandle(pile_thread);
    } else {
        log_line(
            "[FUT-PILE-SIZE] disabled ([Patch] "
            "transfer_pile_capacity=0); an uninitialised FCC cache may show "
            "the transfer pile as count/0");
    }

    int total_patched = 0;
    for (int pass = 0; pass < kMaxHostnamePasses; ++pass) {
        HostPatchResult result = patch_hostnames_in_main_module(config.host);
        total_patched += result.patched;
        if (result.patched > 0 && result.not_found == 0) {
            log_line("[REDIR] all hostnames patched on pass %d", pass + 1);
            break;
        }
        if (pass + 1 < kMaxHostnamePasses) Sleep(kPassIntervalMs);
    }
    if (total_patched == 0) {
        log_line("[REDIR] WARNING: no hostnames were patched; the game will use EA's "
                 "real endpoints. The image may not have decrypted, or the strings moved.");
    }

    AuthResult auth = accounts_login_and_authorize(config);
    if (!auth.ok) {
        log_line("[LOGIN] not completed: %s", auth.error.c_str());
    } else {
        origin_publish_auth_code(auth.auth_code);
    }

    constexpr int kOriginPatchCount = 14;
    int origin_patches = 0;
    for (int pass = 0; pass < 60 && origin_patches < kOriginPatchCount; ++pass) {
        origin_patches = apply_fake_origin_patches();
        if (origin_patches < kOriginPatchCount) Sleep(250);
    }
    if (origin_patches < kOriginPatchCount) {
        log_line("[ORIGIN-PATCH] installed %d/%d marker redirects before timeout",
                 origin_patches, kOriginPatchCount);
    }

    if (cert_thread != nullptr) {
        WaitForSingleObject(cert_thread, INFINITE);
        CloseHandle(cert_thread);
    }

    if (config.recon) {
        HANDLE verdict_thread = CreateThread(nullptr, 0, verdict_recon_worker, nullptr, 0, nullptr);
        if (verdict_thread != nullptr) CloseHandle(verdict_thread);
    }

    static Config g_apt_config;
    if (!config.apt_patch.empty()) {
        g_apt_config = config;
        HANDLE apt_thread = CreateThread(nullptr, 0, apt_force_worker, &g_apt_config, 0, nullptr);
        if (apt_thread != nullptr) CloseHandle(apt_thread);
        log_line("[APT-FORCE] armed with apt_patch=%s", config.apt_patch.c_str());
    }

    if (config.patch_fut_probes) {
        HANDLE club_scan_thread =
            CreateThread(nullptr, 0, club_caller_scan_worker, nullptr, 0, nullptr);
        if (club_scan_thread != nullptr) CloseHandle(club_scan_thread);

        HANDLE phase_thread =
            CreateThread(nullptr, 0, fut_phase_probe_worker, nullptr, 0, nullptr);
        if (phase_thread != nullptr) CloseHandle(phase_thread);

        HANDLE eventsrc_thread =
            CreateThread(nullptr, 0, fut_event_source_scan_worker, nullptr, 0, nullptr);
        if (eventsrc_thread != nullptr) CloseHandle(eventsrc_thread);

    }

    if (!config.recon) {
        log_line("=== shim initialisation complete ===");
        return 0;
    }

    constexpr int kMaxComponentPasses = 30;
    constexpr DWORD kComponentIntervalMs = 3000;
    bool fire2_dumped = false, authentication_dumped = false, util_dumped = false;
    bool census_dumped = false;
    for (int pass = 0; pass < kMaxComponentPasses; ++pass) {
        if (!fire2_dumped && recon_fire2_dump()) fire2_dumped = true;
        if (!authentication_dumped && recon_authentication_dump()) authentication_dumped = true;
        if (!util_dumped && recon_util_dump()) util_dumped = true;
        if (!census_dumped && recon_census_dump()) census_dumped = true;
        if (fire2_dumped && authentication_dumped && util_dumped && census_dumped) break;
        Sleep(kComponentIntervalMs);
    }
    if (!fire2_dumped) {
        log_line("[FIRE2] connection code never decrypted within the window; the game "
                 "may not have reached the Blaze handshake this run");
    }
    if (!authentication_dumped) {
        log_line("[AUTH-RECON] component registration code never decrypted within the window; "
                 "command 70 remains intentionally unmapped");
    }
    if (!util_dumped) {
        log_line("[UTIL-RECON] component registration/type code never decrypted within the "
                 "window; postAuth schema remains unconfirmed");
    }
    if (!census_dumped) {
        log_line("[CENSUS-RECON] component registration/type code never decrypted within the "
                 "window; subscribe-update schema remains unconfirmed");
    }

    bool fut_dumped = false;
    constexpr int kMaxFutPasses = 180;
    constexpr DWORD kFutIntervalMs = 1000;
    for (int pass = 0; pass < kMaxFutPasses && !fut_dumped; ++pass) {
        fut_dumped = recon_fut_dump();
        if (!fut_dumped) Sleep(kFutIntervalMs);
    }
    if (!fut_dumped) {
        log_line("[FUT-RECON] accountinfo code never decrypted within the three-minute "
                 "window; enter Ultimate Team sooner on the next launch");
    }

    log_line("=== shim initialisation complete ===");
    return 0;
}

}
