# Project Revival 17

> ## ⚠️ IMPORTANT — READ THIS FIRST
>
> **Project Revival 17 is an UNOFFICIAL, NON-COMMERCIAL fan project made ONLY for game preservation, because the game's official online servers were permanently shut down.**
>
> - **It is NOT affiliated with, NOT endorsed by, NOT sponsored by and NOT connected to any game publisher**, developer, league, club or player.
> - **All trademarks, names and logos belong to their respective owners.** They are used only to describe compatibility.
> - **The author makes NO PROFIT from this project.** It is free, has no donations, no ads and no paid access, and **must never be sold**.
> - **No game files are included.** Every player needs their own legitimate copy of the game.
>
> See [NOTICE](NOTICE) for the full disclaimer.

---

Project Revival 17 is a self-hosted replacement for the online services that
FIFA 17 (PC) needs to reach Ultimate Team. One person runs the server, and
friends connect to it with the launcher. Each player keeps their own club,
and players can trade with and play against each other on the same server.

## What is in this repository

| Part | Folder | What it does |
|---|---|---|
| Server | [`server/`](server/) | Accounts, sign-in, Blaze online services and the Ultimate Team service (Python). |
| Launcher | [`launcher/`](launcher/) | Windows app for players: accepts an invite, installs the client files, checks the connection. |
| Client shim | [`client/`](client/) | `version.dll` loaded by the game. Redirects the game to your server and applies in-memory compatibility patches. Nothing on disk is modified. |

## What works

**Sign-in and online menus**

- Sign-in, online session and the online main menu
- Ultimate Team unlocked, with club name, badge and squad

**Ultimate Team**

- Club, squads (create, rename, edit, save), chemistry styles
- Store and pack opening, unassigned items, quick sell
- Coins and FIFA Points, with a full transaction ledger
- Transfer market shared by all players on the server: search, bid, buy now, list, relist, compare price
- Club items: kits, badges, balls, stadiums
- Squad Building Challenges, including the retail challenge list and rewards
- Single Player Draft
- Single-player tournaments
- Offline Seasons

**Online play between players on the same server**

- Online Single Match: matchmaking, peer-to-peer match, results and rewards (tested with two clients)
- Online Seasons: separate matchmaking pool, ten-match campaigns, promotions and rewards (tested with two clients)
- Online Draft: separate matchmaking pool and draft runs (tested with two clients)

**Server**

- One account and one separate club per player
- Match records and settled rewards persist across server restarts, and
  duplicate result submissions do not pay twice. Restarting disconnects
  online services and can interrupt ongoing matches or prevent their
  results from being recorded.
- Invite-based access: invite codes, automatic enrollment, certificate pinning and TLS-only remote connections
- Automatic database migrations with a backup before each one

## Server economy

Each server has its own economy. Clubs, coins and FIFA Points exist only on
that server and are separate from the original game's accounts.

By default:

- Every new club starts with **1,000,000 coins** and **10,000 FIFA Points**.
- Coin rewards are multiplied:
  - **25x** for coins from Squad Building Challenges and single-player
    tournaments
  - **15x** for coins from offline competitions (Offline Seasons and Single
    Player Draft)
  - **25x** for coins from online competitions (Online Seasons and Online
    Draft)
- Only coin amounts are multiplied. Packs, players and other items awarded
  as rewards are not.

Server owners can change these values in `state\config.toml`; see
[Hosting a server, step 12](docs/HOSTING.md#12-change-the-starting-money-and-coin-rewards).

## Known limitations

- Squad Building Challenge artwork is not included, so challenge tiles show no image.
- Kit textures for club kit items may appear blank.
- Some optional online content (news, dynamic messages) is not available.
- Only the **final PC version of FIFA 17 (1.0.48.30259)** is supported.
- Windows only.

## Requirements

**Host (runs the server):**

- Windows 10 or 11 PC that stays on while people play
- Python 3.11 or newer
- A router where you can forward ports, and a public IPv4 address

**Every player, including the host if they play:**

- Windows 10 or 11, 64-bit
- A legitimate copy of FIFA 17 for PC, installed from EA app and fully updated
- The game installed in a **normal folder** such as `C:\Games\FIFA 17`. **Do not install it in a protected folder such as `C:\Program Files` or `C:\Program Files (x86)`.** The launcher must write two files next to `FIFA17.exe`, and Windows blocks that in protected folders.
- [.NET 8 Desktop Runtime (x64)](https://dotnet.microsoft.com/download/dotnet/8.0)

## Guides

1. **[Hosting a server](docs/HOSTING.md):** for the person running the server.
2. **[Playing on a server](docs/PLAYING.md):** for every player.

## Quick overview

1. The host installs the server, forwards the ports and starts it.
2. The host creates one invite per player and sends each player their invite and the launcher zip, **privately**.
3. Each player extracts the launcher, pastes the invite, installs the files and starts FIFA 17 from EA app.
4. Players do **not** need to forward any ports.

## Disclaimer

**This project is unofficial and non-commercial.** It is not affiliated with,
endorsed by, sponsored by or connected to any game publisher, developer,
league, club or player. All trademarks, names and logos belong to their
respective owners. The author makes no profit from this project: it is free,
it must never be sold, and access to a server running it must never be sold.
It exists only to preserve a game whose official online servers were shut
down. No game files are included or distributed. The software is provided
"as is", without warranty of any kind. Full text: [NOTICE](NOTICE).

## License

The source code is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE). You may use, copy, change
and share it for any noncommercial purpose. Selling it, or charging for
access to a server running it, is not permitted. When you share it, include
the [LICENSE](LICENSE) file with its `Required Notice` line. This does not
grant any right in third-party trademarks or names; see [NOTICE](NOTICE).

## Credits

- **aleksanderG**: creator of Project Revival 17.
- Thanks to **[KyroGeorge2](https://github.com/KyroGeorge2)** for sharing his work.
