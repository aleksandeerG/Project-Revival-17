# Hosting a Project Revival 17 server

> **Unofficial, non-commercial fan project made only for game preservation, because the official servers were shut down. Not affiliated with, endorsed by or connected to any game publisher. All trademarks belong to their respective owners. The author makes no profit from it. Never sell it, and never charge anyone for access to your server.** Full text: [NOTICE](../NOTICE).

This guide is for the person who runs the server. Every command below is for
**Windows PowerShell**, run from the project folder.

The example values used throughout this guide:

| Setting | Example | Yours |
|---|---|---|
| Project folder | `C:\ProjectRevival17` | |
| Your public IPv4 address | `203.0.113.10` | |
| This PC's LAN address | `192.168.1.50` | |
| Accounts port | `34991` | |
| Redirector port | `24937` | |
| Blaze port | `34472` | |
| Ultimate Team port | `22111` | |
| Knock port | `32130` | |

---

## 1. Before you start

You need:

- **A Windows 10 or 11 PC** that stays on while people play.
- **Python 3.11 or newer** from [python.org](https://www.python.org/downloads/). During setup, tick **"Add python.exe to PATH"**.
- **Access to your router's settings** to forward ports.
- **A public IPv4 address.** Many internet providers put customers behind
  carrier-grade NAT (CGNAT), and then port forwarding cannot work. To check:
  open your router's status page and compare its WAN/Internet IPv4 address
  with the address shown by a "what is my IP" website. If they differ, or the
  router shows an address starting with `100.64.` to `100.127.`, you are
  behind CGNAT. Ask your provider for a public IPv4 address.

**Only for building the launcher yourself** (optional, see step 9):

- Visual Studio 2022 (Community is fine) with the **"Desktop development with C++"** workload
- [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)

## 2. Get the project

Download the repository (**Code → Download ZIP** on GitHub) and extract it, or
clone it:

```powershell
git clone https://github.com/aleksandeerG/Project-Revival-17.git C:\ProjectRevival17
cd C:\ProjectRevival17
```

## 3. Install the server

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If PowerShell says `python` is not recognized, reinstall Python with "Add
python.exe to PATH" ticked, then open a new PowerShell window.

## 4. Give this PC a fixed LAN address

In your router, create a **DHCP reservation** (sometimes called "static
lease" or "address reservation") for this PC, so its LAN address (for
example `192.168.1.50`) never changes. To see the current address, run
`ipconfig` and look for **IPv4 Address**.

## 5. Configure the server

```powershell
New-Item -ItemType Directory state -Force
Copy-Item config.example.toml state\config.toml
notepad state\config.toml
```

In the `[profiles.friends]` section:

1. Set `advertise` to **your public IPv4 address**, for example
   `advertise = "203.0.113.10"`.
   - It may be **at most 16 characters**. Most dynamic-DNS names are longer,
     so use the IP address, or a very short hostname.
   - It is written into every invite. **If it ever changes, you must send
     every player a new invite** (see step 11).
2. Set `allow` to this PC and your home network, for example
   `allow = ["127.0.0.1", "::1", "192.168.1.0/24"]`.
   Friends do **not** go in this list. Their launcher admits them
   automatically with their invite.
3. Keep or change the four ports. Use numbers between 20000 and 45000 that
   nothing else on this PC uses.

Save the file.

## 6. Forward the ports on your router

In your router's **port forwarding** (or "virtual server" / "NAT") page,
forward these **TCP** ports to this PC's LAN address (`192.168.1.50`):

| Port | Purpose |
|---|---|
| `34991` | Accounts |
| `24937` | Redirector |
| `34472` | Blaze (online services) |
| `22111` | Ultimate Team |
| `32130` | Knock (invite enrollment) |

Forward nothing else. **Players do not forward anything**: only the host does.

## 7. Allow the ports through Windows Firewall

Open **PowerShell as Administrator** and run (with your port numbers):

```powershell
New-NetFirewallRule -DisplayName "Project Revival 17" -Direction Inbound -Protocol TCP -LocalPort 34991,24937,34472,22111,32130 -Action Allow
```

To remove it later:

```powershell
Remove-NetFirewallRule -DisplayName "Project Revival 17"
```

## 8. Start the server

```powershell
.venv\Scripts\python.exe server\main.py --profile friends --allow-remote --knock-port 32130 --matchmaking-duration 120
```

- On first start, the server creates its certificate in `certs\` and its
  databases in `state\`.
- **Keep this window open** while people play. Press **Ctrl+C** once to stop
  the server cleanly.
- `--matchmaking-duration 120` gives two friends two minutes to start
  searching for an online match at the same time.
- Logs are written to `logs\server.jsonl`.

Always start the server **before** anyone starts the game.

## 9. Get the launcher zip for your players

Players need the launcher zip, and **it must be the same version as your
server**. A mismatch is shown in the launcher as "not compatible with this
server".

**Option A: use the official release.** Download the launcher zip that
matches your server version from the project's
[releases page](https://github.com/aleksandeerG/Project-Revival-17/releases).

**Option B: build it yourself.** You need the tools from step 1. In a normal
PowerShell window in the project folder:

```powershell
client\build.cmd
powershell -ExecutionPolicy Bypass -File launcher\pack.ps1 -Serial 1
```

The zip is created in `dist\`, for example
`dist\ProjectRevival17-0.1.0-r1.zip`. Increase `-Serial` every time you build
a new version for your players.

**Send the zip to your players privately**, together with their invite.

## 10. Create an invite for each player

Every player, including you if you play, needs **their own** invite. Open a
**second** PowerShell window in the project folder (the server can keep
running) and run, with a different name for each player:

```powershell
.venv\Scripts\python.exe server\main.py --profile friends --allow-remote --knock-port 32130 --create-invite alex
```

This prints a long code starting with `FUT1-`.

- **It is shown only once.** Copy it straight away.
- **Send it privately**, for example in a direct message, never in a public
  channel. Anyone holding it can join your server as that player.
- The name (`alex`) becomes the player's account name.

## 11. Managing players

| Task | Command (add `--profile friends --allow-remote --knock-port 32130`) |
|---|---|
| New invite for an existing player (lost code, new PC, address changed) | `.venv\Scripts\python.exe server\main.py ... --reissue-invite alex` |
| Remove a player's network access | `.venv\Scripts\python.exe server\main.py ... --revoke-enrollment-token alex` |
| List invites and admitted addresses | `.venv\Scripts\python.exe server\main.py ... --list-enrollments` |

`--reissue-invite` keeps the player's club and replaces their password and
access token. The old invite stops working, and the player pastes the new one
in the launcher (**Account and maintenance → Replace invite**).

## 12. Change the starting money and coin rewards

The starting balances and coin reward multipliers are set in the `[economy]`
section of `state\config.toml`, which you created in step 5:

```powershell
notepad state\config.toml
```

```toml
[economy]
starting_coins = 1_000_000
starting_points = 10_000

coin_reward_multiplier = 25                 # Squad Building Challenges, single-player tournaments
offline_competition_reward_multiplier = 15  # Offline Seasons, Single Player Draft
online_competition_reward_multiplier = 25   # Online Seasons, Online Draft
```

Change the numbers you want, save the file, then stop the server with Ctrl+C
and start it again (step 8).

- **Every line is optional.** Leave one out, or the whole `[economy]`
  section, to keep the value shown above.
- **Keep the `[economy]` heading line.** The settings must sit under it, not
  under a `[profiles...]` heading: they apply to the whole server. If your
  `state\config.toml` was made before this version and has no `[economy]`
  section, paste the block above at the end of the file.
- **Whole numbers only**, such as `500000` or `10`, not `1.5`. The
  underscores in `1_000_000` are optional.
- **Starting coins and points:** `0` to `2147483647`. They apply only to
  clubs created after the change. Existing clubs keep their balances.
- **Multipliers:** `1` to `1000`. `1` uses the project's unmultiplied base
  rewards; it does not restore the original game's economy.
  They multiply coins only, never packs, players or other items. They apply
  to every reward paid after the restart, including Seasons campaigns and
  Drafts already in progress.
- If a value is wrong, the server refuses to start and names the setting.
- `state\` is kept when you update the server (step 13), so your values
  stay.

## 13. Back up and update

**Back up** regularly, with the server stopped:

- `state\` holds all accounts, clubs, coins and the configuration.
- `certs\` holds the server certificate. **Never delete it.** A new
  certificate means every player needs a new invite.

**Update** the server:

1. Stop the server with Ctrl+C and back up `state\` and `certs\`.
2. Replace the project files with the new version. Keep `state\`, `certs\` and `.venv\`.
3. Run `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
4. Start the server again. Database upgrades run automatically, with a backup first.
5. If the new version needs a new launcher, send the new zip to your players.

## 14. Troubleshooting

| Problem | What to check |
|---|---|
| Nobody outside your home can connect | Port forwarding (step 6), Windows Firewall (step 7), CGNAT (step 1), and that `advertise` is your current public IP. |
| Your public IP changed | Update `advertise` in `state\config.toml`, restart the server, and send every player a new invite with `--reissue-invite`. |
| You can't connect from the server PC (or your home network), but friends can | Your router must support **NAT loopback** (also called hairpin NAT) for home devices to reach your own public address. Enable it in the router settings if available. |
| "You are not eligible to use online … age restriction" in game | The game could not reach the server when it started. Make sure the server is running, then restart the game. |
| Two players never find each other online | Both must choose the same mode and start searching within the matchmaking window (two minutes with `--matchmaking-duration 120`). |
| "Refusing to bind non-loopback address" | Add `--allow-remote`. |
| "--create-invite needs --knock-port" | Add the same `--knock-port` you start the server with. |
| "advertised host … exceeds 16 ASCII bytes" | Use your public IP address in `advertise`, not a long hostname. |
| A player sends a diagnostic report | In the launcher, **Connection details → Copy diagnostic report**. Passwords, invites and paths are removed from it. |

## 15. Security

- **Invite-only.** Run the server only for people you know and trust.
- Send invites privately. Revoke anyone who should no longer have access.
- Forward only the five ports above, and remove the port forwards when you stop hosting.
- Keep Windows and Python up to date.

---

**Disclaimer.** Project Revival 17 is unofficial and non-commercial. It is not
affiliated with, endorsed by or connected to any game publisher, and all
trademarks belong to their respective owners. No profit is made from it. Never
sell it or charge for access to your server. See [NOTICE](../NOTICE).
