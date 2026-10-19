# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import argparse
import ipaddress
import signal
import sqlite3
import time
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as service_config
import access
import events
import health
import invite
import knock
import throttle
from accounts import (
    MAX_CONNECTIONS,
    MAX_REQUEST_BODY_BYTES,
    AccountsHandler,
    ConnectionBudget,
    DualProtocolHTTPServer,
)
from blaze import (
    AUTH70_EMPTY,
    AUTH70_MODES,
    REPLY_BOOTSTRAP,
    REPLY_MODES,
    PLAYER_ATTRIB_CHANGE_NOTIFICATION,
    BlazeCaptureServer,
    parse_sweep_ids,
)
from blaze_bootstrap import (
    COMPONENT_SETS,
    DEFAULT_COMPONENT_SET,
    DEFAULT_SERVER_VERSIONING,
    SERVER_VERSIONING_MODES,
    set_fut_base_url,
)
from blaze_frontend import (
    DEFAULT_ENTITLEMENT_TYPE_MODE,
    ENTITLEMENT_TYPE_MODES,
    set_content_base_url,
)
from certs import create_self_signed, der_sha256, legacy_server_context
from events import emit
from fut import (
    ACCOUNT_MODES,
    PRICELIMITS_MODE,
    PRICELIMITS_MODES,
    UNHANDLED_MODES,
    UNHANDLED_NOT_FOUND,
    ACCOUNT_RETURNING,
    FutCaptureHandler,
    FutCaptureServer,
)
from fut_state import MATCH_EXPIRY_SECONDS, FutStateStore
from identity import IdentityStore
from redirector import RedirectorServer

DEFAULT_HOSTNAME = "fifa17.local"
DEFAULT_ACCOUNTS_PORT = service_config.DEFAULT_ACCOUNTS_PORT
DEFAULT_REDIRECTOR_PORT = service_config.DEFAULT_REDIRECTOR_PORT
DEFAULT_BLAZE_PORT = service_config.DEFAULT_BLAZE_PORT
DEFAULT_FUT_PORT = service_config.DEFAULT_FUT_PORT
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "state" / "config.toml"

_is_loopback = service_config.is_loopback


DISCLAIMER = (
    "Project Revival 17 - unofficial, non-commercial fan project for game "
    "preservation.\n"
    "Not affiliated with, endorsed by or connected to any game publisher. "
    "All trademarks belong to their owners.\n"
    "Free of charge: no profit is made from it, and it must never be sold.\n"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Revival 17 server")
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG_PATH),
        help="Deployment configuration. Absent means the built-in 'local' "
        "profile, which is loopback-only and what a single machine has always "
        "used.")
    parser.add_argument(
        "--profile",
        help="Which profile in the configuration to run. Defaults to the "
        "file's default_profile, or 'local'.")
    parser.add_argument(
        "--host", default=None,
        help="Interface to listen on, overriding the profile's bind address.")
    parser.add_argument(
        "--advertise-host", default=None,
        help="Address handed to clients for every service, overriding the "
        "profile. This is what a client on another machine connects back to, "
        "so loopback here tells it to look at itself.")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Permit binding a non-loopback address and enforce TLS-only game "
        "transport. Configure an allowlist and firewall as separate controls.",
    )
    parser.add_argument("--accounts-port", type=int, default=None)
    parser.add_argument("--redirector-port", type=int, default=None)
    parser.add_argument("--blaze-port", type=int, default=None)
    parser.add_argument("--fut-port", type=int, default=None,
                        help="Ultimate Team listener port.")
    parser.add_argument(
        "--fut-account-mode",
        choices=ACCOUNT_MODES,
        default=ACCOUNT_RETURNING,
    )
    parser.add_argument(
        "--tournament-probe-row",
        action="store_true",
    )
    parser.add_argument(
        "--market-duration-seconds",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--fut-accountinfo-delay-ms",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--blaze-reply",
        choices=REPLY_MODES,
        default=REPLY_BOOTSTRAP,
    )
    parser.add_argument(
        "--preauth-components",
        choices=sorted(COMPONENT_SETS),
        default=DEFAULT_COMPONENT_SET,
    )
    parser.add_argument(
        "--auth-cmd70",
        choices=AUTH70_MODES,
        default=AUTH70_EMPTY,
    )
    parser.add_argument(
        "--server-versioning",
        choices=SERVER_VERSIONING_MODES,
        default=DEFAULT_SERVER_VERSIONING,
    )
    parser.add_argument(
        "--redirector-echo-versions",
        action="store_true",
    )
    parser.add_argument(
        "--entitlement-type",
        choices=sorted(ENTITLEMENT_TYPE_MODES),
        default=DEFAULT_ENTITLEMENT_TYPE_MODE,
    )
    parser.add_argument(
        "--fut-direct-boot",
        action="store_true",
    )
    parser.add_argument(
        "--fut-unhandled",
        choices=UNHANDLED_MODES,
        default=UNHANDLED_NOT_FOUND,
    )
    parser.add_argument(
        "--fut-club-size", type=int, default=1)
    parser.add_argument(
        "--fut-club", choices=("empty", "items"), default="empty")
    parser.add_argument(
        "--fut-pricelimits", choices=PRICELIMITS_MODES,
        default=PRICELIMITS_MODE)
    parser.add_argument(
        "--fut-recover-squad-name", action="store_true")
    parser.add_argument(
        "--matchmaking-duration", type=float, default=None,
        help="Online matchmaking search window in seconds. The game asks "
             "for 20; 120 gives two friends time to start searching together.")
    parser.add_argument(
        "--gamemanager-sweep", default="")
    parser.add_argument(
        "--gamemanager-sweep-persona", type=int, default=None)
    pairing = parser.add_mutually_exclusive_group()
    pairing.add_argument(
        "--enable-pairing", dest="enable_pairing", action="store_true",
        default=True)
    pairing.add_argument(
        "--disable-pairing", dest="enable_pairing", action="store_false")
    parser.add_argument(
        "--player-join-completed-notification", type=int, default=30)
    parser.add_argument(
        "--player-state-notification", type=int, default=116)
    parser.add_argument(
        "--advance-on-player-request", choices=("", "any", "all"), default="")
    parser.add_argument(
        "--player-attrib-notification", type=int,
        default=PLAYER_ATTRIB_CHANGE_NOTIFICATION)
    parser.add_argument(
        "--player-attrib-sweep", default="")
    parser.add_argument(
        "--player-state-sweep", default="")
    parser.add_argument(
        "--player-state-sweep-delay", type=float, default=1.5)
    parser.add_argument(
        "--pairing-result-notification", action="store_true")
    parser.add_argument(
        "--gamemanager-setup-reasons", default="")
    parser.add_argument(
        "--gamemanager-game-states", default="")
    parser.add_argument(
        "--gamemanager-finished-ids", default="")
    parser.add_argument(
        "--gamemanager-setup-control", action="store_true")
    parser.add_argument(
        "--gamemanager-setup-notification", type=int, default=0)
    parser.add_argument(
        "--gamemanager-setup-marker", default="")
    parser.add_argument(
        "--gamemanager-result-probe", type=int, default=None)
    parser.add_argument(
        "--gamemanager-setup-ids", default="")
    parser.add_argument(
        "--gamemanager-sweep-delay", type=float, default=8.0)
    parser.add_argument("--no-redirector", action="store_true", help="Do not listen on 42230")
    parser.add_argument("--no-blaze", action="store_true", help="Do not listen on 44321")
    parser.add_argument("--no-fut", action="store_true", help="Do not listen on the fut port")
    parser.add_argument(
        "--hostname",
        default=DEFAULT_HOSTNAME,
        help="Certificate CN, and the name the client resolves to this server. "
        "Must match the client shim's configured Host. Keep it to 16 characters "
        "or fewer if the shim rewrites hostnames in place.",
    )
    parser.add_argument("--database", default=str(PROJECT_ROOT / "state" / "identity.sqlite3"))
    parser.add_argument("--fut-database",
                        default=str(PROJECT_ROOT / "state" / "fut.sqlite3"),
                        help="durable FUT wallet, inventory and squad database")
    parser.add_argument(
        "--fut-match-expiry-seconds", type=int, default=MATCH_EXPIRY_SECONDS,
        help="Abandon an unfinished match this long after the last word from "
        "the client. Must exceed the longest real match, because there is no "
        "in-match heartbeat to measure instead. 0 disables expiry.",
    )
    parser.add_argument("--cert-dir", default=str(PROJECT_ROOT / "certs"))
    parser.add_argument(
        "--max-request-body", type=int, default=MAX_REQUEST_BODY_BYTES,
        help="Refuse an HTTP request body larger than this. 0 removes the "
        "limit.")
    parser.add_argument(
        "--max-connections", type=int, default=MAX_CONNECTIONS,
        help="Ceiling on concurrent HTTP connections. 0 removes the limit.")
    parser.add_argument("--log", default=str(PROJECT_ROOT / "logs" / "server.jsonl"))
    parser.add_argument(
        "--log-max-bytes", type=int, default=events.DEFAULT_MAX_BYTES,
        help="Rotate the event log once it reaches this size. 0 disables "
        "rotation.")
    parser.add_argument(
        "--log-keep", type=int, default=events.DEFAULT_KEEP,
        help="How many rotated event logs to keep.")
    parser.add_argument("--regenerate-cert", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not echo events to stderr")
    parser.add_argument(
        "--create-account",
        metavar="USERNAME:PASSWORD",
        help="Create an account and exit. The printed device token is what the "
        "client shim stores and replays on every boot.",
    )
    parser.add_argument(
        "--knock-port", type=int, default=0,
        help="Listen for self-enrollment knocks on this port. 0 disables it, "
        "which is the default: the endpoint is the one surface reachable by "
        "anybody, so it exists only when asked for.")
    parser.add_argument(
        "--create-enrollment-token", metavar="NAME",
        help="Issue an enrollment token and exit. Printed once and stored only "
        "as a hash, so this is the only moment it is readable.")
    invite_commands = parser.add_mutually_exclusive_group()
    invite_commands.add_argument(
        "--create-invite", metavar="NAME",
        help="Create an account and an enrollment token under NAME, then print "
        "one invite code carrying the host, every port, the token and the "
        "credential. Needs --knock-port, because a friend who cannot knock "
        "cannot reach anything. Send it over something private: it is as "
        "sensitive as both secrets in it.")
    invite_commands.add_argument(
        "--reissue-invite", metavar="NAME",
        help="Preserve an existing account's persona and FUT state, but rotate "
        "its password, device token, sessions and enrollment token atomically, "
        "then print a replacement invite. Needs --knock-port. Every older "
        "client for that account must paste the replacement.")
    parser.add_argument(
        "--revoke-enrollment-token", metavar="NAME",
        help="Revoke a token and drop every address it admitted, then exit.")
    parser.add_argument(
        "--list-enrollments", action="store_true",
        help="Show the issued tokens and the addresses currently admitted.")
    parser.add_argument("--print-pin", action="store_true", help="Print the certificate pin and exit")
    hidden = {
        "fut_account_mode", "tournament_probe_row", "market_duration_seconds",
        "fut_accountinfo_delay_ms", "blaze_reply", "preauth_components",
        "auth_cmd70", "server_versioning", "redirector_echo_versions",
        "entitlement_type", "fut_direct_boot", "fut_unhandled",
        "fut_club_size", "fut_club", "fut_pricelimits", "fut_recover_squad_name",
        "gamemanager_sweep", "gamemanager_sweep_persona", "enable_pairing",
        "player_join_completed_notification", "player_state_notification",
        "advance_on_player_request", "player_attrib_notification",
        "player_attrib_sweep", "player_state_sweep", "player_state_sweep_delay",
        "pairing_result_notification", "gamemanager_setup_reasons",
        "gamemanager_game_states", "gamemanager_finished_ids",
        "gamemanager_setup_control", "gamemanager_setup_notification",
        "gamemanager_setup_marker", "gamemanager_result_probe",
        "gamemanager_setup_ids", "gamemanager_sweep_delay",
    }
    for action in parser._actions:
        if action.dest in hidden:
            action.help = argparse.SUPPRESS
    return parser


def matches_blocking_stop(fut_state, signal_name: str,
                         already_warned: bool) -> list[dict]:
    if already_warned or signal_name not in ("SIGINT", ""):
        return []
    if fut_state is None:
        return []
    return fut_state.unfinished_matches()


def create_invite(args, config, store, pin: str) -> int:
    reissue_name = getattr(args, "reissue_invite", None)
    reissuing = bool(reissue_name)
    name = reissue_name if reissuing else args.create_invite

    knock_port = args.knock_port
    if knock_port is None or not 1 <= int(knock_port) <= 65535:
        print("--create-invite needs --knock-port: without the knock endpoint "
              "a friend cannot admit their address, and every game port stays "
              "closed to them.", file=sys.stderr)
        return 2

    advertised_hosts = (
        config.advertise_accounts,
        config.advertise_blaze,
        config.advertise_fut,
        config.advertise_content,
    )
    canonical_hosts = {host.rstrip(".").casefold() for host in advertised_hosts}
    if len(canonical_hosts) != 1:
        print("--create-invite cannot represent a split-host profile: the current "
              "invite format carries one host for Accounts, Redirector, Blaze, "
              "FUT and content. Configure one shared advertised host or create "
              "the client configuration manually.", file=sys.stderr)
        return 2

    host = config.advertise_accounts
    if not invite.valid_host(host):
        print(f"advertised host {host!r} is invalid or exceeds 16 ASCII bytes; the shim "
              "can only patch a valid host of 16 bytes or fewer, so this invite would produce a "
              "client that silently fails to redirect.", file=sys.stderr)
        return 2

    existing_account = store.account(name)
    if reissuing and existing_account is None:
        print(f"account {name!r} does not exist; use --create-invite for a new "
              "account.", file=sys.stderr)
        return 1
    if not reissuing and existing_account is not None:
        print(f"account {name!r} already exists. Its password cannot be "
              "recovered; use --reissue-invite to rotate it, or issue the "
              "invite under a different name.",
              file=sys.stderr)
        return 1

    password = invite.generate_password()
    try:
        if reissuing:
            record, token = store.reissue_invite_identity(name, password)
        else:
            record, token = store.create_invite_identity(name, password)
    except (ValueError, sqlite3.IntegrityError) as error:
        action = "reissue" if reissuing else "issue"
        print("could not %s the invite atomically: %s" % (action, error),
              file=sys.stderr)
        return 1

    code = invite.encode(
        name=config.profile,
        host=host,
        redirector_port=config.redirector_port,
        accounts_port=config.accounts_port,
        blaze_port=config.blaze_port,
        fut_port=config.fut_port,
        cdn_port=config.fut_port,
        knock_port=knock_port,
        token=token,
        username=name,
        password=password,
        pin=pin,
    )

    print(f"account      {record['username']}")
    print(f"persona id   {record['persona_id']}")
    print(f"profile      {config.profile}  ({host})")
    print(f"pin          {pin}")
    print()
    print(code)
    print()
    print("  Shown once. The token and the password are stored only as")
    print("  hashes, so neither can be recovered. If it is lost, run")
    print(f"  --reissue-invite {record['username']}: it keeps the account")
    print("  and club, and the old invite stops working.")
    print("  Send it over something private. It carries network access and")
    print("  an account, and is as sensitive as both.")
    if reissuing:
        print("  Every previous password, device token, session, enrollment")
        print("  token and dynamically admitted address for this account is revoked.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = service_config.load(
            args.config,
            profile=args.profile,
            overrides={
                "bind": args.host,
                "advertise": args.advertise_host,
                "accounts_port": args.accounts_port,
                "redirector_port": args.redirector_port,
                "blaze_port": args.blaze_port,
                "fut_port": args.fut_port,
            },
        )
    except (ValueError, OSError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    config.economy.apply()

    if (not service_config.valid_advertised_host(args.hostname)
            or len(args.hostname.encode("ascii")) > 64):
        print(f"configuration error: invalid certificate hostname {args.hostname!r}",
              file=sys.stderr)
        return 2

    if not config.binds_loopback_only and not args.allow_remote:
        print(
            f"refusing to bind non-loopback address {config.bind_host!r} "
            "without --allow-remote.\n"
            "Remote listeners require explicit operator acknowledgement.",
            file=sys.stderr,
        )
        return 2

    if args.fut_recover_squad_name and not config.binds_loopback_only:
        print(
            "refusing --fut-recover-squad-name on non-loopback address "
            f"{config.bind_host!r}.\n"
            "That recovery reads the shim log of the game running on this "
            "host, so a shared server would apply one player's captured text "
            "to another player's squad. It is a single-machine compatibility "
            "fallback only.",
            file=sys.stderr,
        )
        return 2

    set_fut_base_url(config.fut_base_url)
    set_content_base_url(config.content_base_url)

    cert_dir = Path(args.cert_dir)
    cert_path, key_path = create_self_signed(
        args.hostname, cert_dir, force=args.regenerate_cert,
        extra_addresses=config.advertised_certificate_names())
    pin = der_sha256(cert_path)

    if args.print_pin:
        print(pin)
        return 0

    store = IdentityStore(Path(args.database))

    if args.create_account:
        username, _, password = args.create_account.partition(":")
        if not username or not password:
            print("--create-account expects USERNAME:PASSWORD", file=sys.stderr)
            return 2
        if store.account(username) is not None:
            print(f"account {username!r} already exists", file=sys.stderr)
            return 1
        record = store.create_account(username, password)
        print(f"username     {record['username']}")
        print(f"persona id   {record['persona_id']}")
        print(f"device token {record['device_token']}")
        print("  the device token is shown once; only its hash is stored")
        return 0

    if args.create_enrollment_token:
        try:
            token = store.create_enrollment_token(args.create_enrollment_token)
        except (ValueError, sqlite3.IntegrityError) as error:
            print("could not issue that token: %s" % error, file=sys.stderr)
            return 1
        print("name   %s" % args.create_enrollment_token)
        print("token  %s" % token)
        print()
        print("  This is a network-only enrollment token, not a player")
        print("  invite: it admits an address but creates no account or")
        print("  club. For a player, use --create-invite instead.")
        print()
        print("  Shown once. Only its hash is stored, so it cannot be")
        print("  recovered. Token names cannot be reused, so if it is lost,")
        print("  revoke it with --revoke-enrollment-token and create a new")
        print("  token under a different name.")
        print("  Send it over something private. It is presented to the")
        print("  knock port to admit the sender's address.")
        return 0

    if args.create_invite or args.reissue_invite:
        return create_invite(args, config, store, pin)

    if args.revoke_enrollment_token:
        if store.revoke_enrollment_token(args.revoke_enrollment_token):
            print("revoked %s, and dropped every address it admitted"
                  % args.revoke_enrollment_token)
            return 0
        print("no live token named %r" % args.revoke_enrollment_token,
              file=sys.stderr)
        return 1

    if args.list_enrollments:
        tokens = store.enrollment_tokens()
        if not tokens:
            print("no enrollment tokens issued")
        for token in tokens:
            state = "revoked" if token["revoked_at"] else "live"
            used = (time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(token["last_used"]))
                    if token["last_used"] else "never used")
            print("  %-20s %-8s %s" % (token["name"], state, used))
        live = store.enrollments()
        print()
        if not live:
            print("no addresses currently admitted")
        for entry in live:
            print("  %-40s via %-16s %d min left"
                  % (entry["address"], entry["name"], entry["expiresIn"] // 60))
        return 0

    print(DISCLAIMER)
    events.configure(Path(args.log), echo=not args.quiet,
                     max_bytes=max(0, args.log_max_bytes),
                     keep=max(0, args.log_keep))
    advertise_host = config.advertise_blaze
    fut_state = FutStateStore(
        Path(args.fut_database),
        match_expiry_seconds=max(0, args.fut_match_expiry_seconds))

    expired = fut_state.expire_stale_matches()
    if expired:
        emit("fut-match-expired-at-startup", matches=int(expired),
             afterSeconds=int(fut_state.match_expiry_seconds))

    servers = []

    knock_port = max(0, args.knock_port)
    allow_list = access.AccessList(
        config.allow,
        enrolled=(store.enrolled_addresses if knock_port else None))
    operator_list = access.AccessList(config.operator_allow)
    auth_throttle = throttle.FailureThrottle()
    http_budget = ConnectionBudget(max(0, args.max_connections))

    def apply_limits(listener) -> None:
        listener.max_request_body = max(0, args.max_request_body)
        listener.max_connections = max(0, args.max_connections)
        listener.connection_budget = http_budget
        listener.access = allow_list
        listener.operator_access = operator_list
        listener.auth_throttle = auth_throttle

    accounts = DualProtocolHTTPServer(
        (config.bind_host, config.accounts_port),
        AccountsHandler,
        legacy_server_context(cert_path, key_path),
    )
    accounts.store = store
    accounts.fut_state = fut_state
    apply_limits(accounts)
    accounts.require_tls = config.require_transport_tls
    servers.append(("accounts", config.accounts_port, accounts))

    if not args.no_redirector:
        redirector = RedirectorServer(
            (config.bind_host, config.redirector_port),
            legacy_server_context(cert_path, key_path),
            advertise_host,
            config.blaze_port,
            echo_client_versions=args.redirector_echo_versions,
            blaze_secure=config.require_transport_tls,
        )
        apply_limits(redirector)
        redirector.require_tls = True
        servers.append(("redirector", config.redirector_port, redirector))

    if not args.no_blaze:
        blaze = BlazeCaptureServer(
            (config.bind_host, config.blaze_port),
            args.blaze_reply,
            store,
            preauth_components=args.preauth_components,
            auth70_reply=args.auth_cmd70,
            server_versioning=args.server_versioning,
            entitlement_type_mode=args.entitlement_type,
            fut_direct_boot=args.fut_direct_boot,
            matchmaking_duration_override=args.matchmaking_duration,
            gamemanager_sweep_ids=parse_sweep_ids(args.gamemanager_sweep),
            gamemanager_sweep_delay=args.gamemanager_sweep_delay,
            gamemanager_sweep_persona=args.gamemanager_sweep_persona,
            gamemanager_result_probe=args.gamemanager_result_probe,
            gamemanager_setup_ids=parse_sweep_ids(args.gamemanager_setup_ids),
            pairing_enabled=args.enable_pairing,
            pairing_result_notification=args.pairing_result_notification,
            player_join_completed_notification=args.player_join_completed_notification,
            player_state_notification=args.player_state_notification,
            player_state_sweep=parse_sweep_ids(args.player_state_sweep),
            player_attrib_notification=args.player_attrib_notification,
            player_attrib_sweep=parse_sweep_ids(args.player_attrib_sweep),
            advance_on_player_request=args.advance_on_player_request,
            player_state_sweep_delay=args.player_state_sweep_delay,
            gamemanager_setup_marker=args.gamemanager_setup_marker,
            gamemanager_setup_notification=args.gamemanager_setup_notification,
            gamemanager_setup_control=args.gamemanager_setup_control,
            gamemanager_game_states=tuple(
                int(g) for g in args.gamemanager_game_states.split(",")
                if g.strip()),
            gamemanager_finished_ids=parse_sweep_ids(
                args.gamemanager_finished_ids),
            gamemanager_setup_reasons=tuple(
                int(r) for r in args.gamemanager_setup_reasons.split(",")
                if r.strip()),
            ssl_context=(legacy_server_context(cert_path, key_path)
                         if config.require_transport_tls else None),
        )
        blaze.fut_state = fut_state
        blaze.access = allow_list
        servers.append(("blaze", config.blaze_port, blaze))

    if not args.no_fut:
        fut = FutCaptureServer(
            (config.bind_host, config.fut_port),
            FutCaptureHandler,
            legacy_server_context(cert_path, key_path),
        )
        fut.store = store
        fut.fut_state = fut_state
        fut.account_mode = args.fut_account_mode
        fut.accountinfo_delay_ms = max(0, args.fut_accountinfo_delay_ms)
        fut.tournament_probe_row = bool(args.tournament_probe_row)
        fut.club_items = args.fut_club == "items"
        fut.club_size = max(0, args.fut_club_size)
        fut.unhandled_mode = args.fut_unhandled
        fut.pricelimits_mode = args.fut_pricelimits
        fut.recover_squad_name = args.fut_recover_squad_name
        apply_limits(fut)
        fut.require_tls = config.require_transport_tls
        servers.append(("fut", config.fut_port, fut))

    if knock_port:
        knocker = knock.KnockServer(
            (config.bind_host, knock_port),
            legacy_server_context(cert_path, key_path),
            launcher_version=config.launcher_version,
            minimum_launcher_version=config.minimum_launcher_version,
            server_version=health.SERVER_VERSION,
            protocol_version=config.protocol_version,
            content_version=config.content_version,
        )
        knocker.store = store
        knocker.game_access = allow_list
        knocker.max_connections = max(0, args.max_connections)
        knocker.connection_budget = http_budget
        servers.append(("knock", knock_port, knocker))

    accounts.listeners = {name: port for name, port, _ in servers}
    accounts.observed_servers = {name: listener for name, _, listener in servers}
    accounts.protocol_version = config.protocol_version
    accounts.content_version = config.content_version

    if not config.binds_loopback_only and not allow_list.configured:
        print("WARNING: bound to %s with no [access] allow list."
              % config.bind_host)
        print("         Every listener is reachable by anyone who can route")
        print("         to this machine, and the Blaze, TDF and FUT parsers")
        print("         were written to recover a protocol, not to be")
        print("         attacked. Add allow = [...] to state/config.toml.")
        emit("access-unrestricted-bind", bind=config.bind_host)

    emit(
        "server-ready",
        host=config.bind_host,
        advertise_host=advertise_host,
        deployment=config.summary(),
        listeners={name: port for name, port, _ in servers},
        blaze_reply=args.blaze_reply,
        preauth_components=args.preauth_components if not args.no_blaze else None,
        auth_cmd70=args.auth_cmd70 if not args.no_blaze else None,
        server_versioning=args.server_versioning if not args.no_blaze else None,
        entitlement_type=args.entitlement_type if not args.no_blaze else None,
        fut_direct_boot=args.fut_direct_boot if not args.no_blaze else None,
        fut_account_mode=args.fut_account_mode if not args.no_fut else None,
        hostname=args.hostname,
        certificate=str(cert_path),
        certificate_pin=pin,
        database=args.database,
        log=args.log,
        matchmaking=({
            "pairingEnabled": args.enable_pairing,
            "pairingResultNotification": args.pairing_result_notification,
            "playerJoinCompletedNotification":
                args.player_join_completed_notification,
            "playerStateNotification": args.player_state_notification,
            "playerStateSweep": args.player_state_sweep,
            "playerAttribNotification": args.player_attrib_notification,
            "playerAttribSweep": args.player_attrib_sweep,
            "advanceOnPlayerRequest": args.advance_on_player_request,
            "matchmakingDurationOverride": args.matchmaking_duration,
        } if not args.no_blaze else None),
    )

    print(f"profile        {config.profile}"
          f"  (protocol {config.protocol_version}, "
          f"content {config.content_version})")
    transport = "https" if config.require_transport_tls else "http(s)"
    print(f"accounts API   {transport}://{config.bind_host}:{config.accounts_port}"
          f"  -> advertises {config.advertise_accounts}")
    if not args.no_redirector:
        print(f"redirector     tls://{config.bind_host}:{config.redirector_port}"
              f"  -> advertises {advertise_host}:{config.blaze_port}")
    if not args.no_blaze:
        print(
            f"blaze          {'tls' if config.require_transport_tls else 'tcp'}://{config.bind_host}:{config.blaze_port}  "
            f"(reply mode: {args.blaze_reply}; components: {args.preauth_components})"
        )
    if not args.no_fut:
        print(
            f"fut            {transport}://{config.bind_host}:{config.fut_port}  "
            f"(capture; account: {args.fut_account_mode})"
        )
    print(f"client fetches FUT from {config.fut_base_url}")
    if config.status_url:
        print(f"status         {config.status_url}")
    print(f"certificate    {cert_path}")
    print("pin (DER SHA-256, uppercase hex, no colons)")
    print(f"               {pin}")
    print(f"event log      {args.log}")
    print("READY - press Ctrl+C to stop")

    threads = []
    allow_list.start()
    operator_list.start()
    for _, _, server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        server._serve_thread = thread
        thread.start()
        threads.append(thread)

    stopping = threading.Event()
    stopped_by = {"signal": ""}

    def _request_stop(signum, _frame):
        try:
            stopped_by["signal"] = signal.Signals(signum).name
        except ValueError:
            stopped_by["signal"] = str(signum)
        stopping.set()

    for _name in ("SIGINT", "SIGBREAK", "SIGTERM"):
        _signum = getattr(signal, _name, None)
        if _signum is None:
            continue
        try:
            signal.signal(_signum, _request_stop)
        except (OSError, ValueError):
            pass

    drained = False

    def _begin_drain() -> None:
        if health.is_ready():
            health.begin_draining()
            emit("server-draining")

    def _may_stop() -> bool:
        nonlocal drained
        active = matches_blocking_stop(
            fut_state, stopped_by["signal"], drained)
        if not active:
            return True
        drained = True
        stopping.clear()
        print("\n%d match(es) still in progress:" % len(active))
        for match in active[:5]:
            print("  persona %d  %s  idle %dm%02ds" % (
                match["persona_id"], match["match_type"] or "match",
                match["idle_seconds"] // 60, match["idle_seconds"] % 60))
        print("stopping now loses whatever they report at full time.")
        print("Press Ctrl+C again to stop anyway.")
        return False

    try:
        while any(t.is_alive() for t in threads):
            if stopping.wait(0.5):
                _begin_drain()
                if _may_stop():
                    break
        print("\nstopping")
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        for _, _, server in servers:
            try:
                server.shutdown()
                server.server_close()
            except OSError:
                pass
        allow_list.close()
        operator_list.close()
        events.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
