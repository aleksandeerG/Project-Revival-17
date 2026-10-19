# Playing on a Project Revival 17 server

> **Unofficial, non-commercial fan project made only for game preservation, because the official servers were shut down. Not affiliated with, endorsed by or connected to any game publisher. All trademarks belong to their respective owners. The author makes no profit from it. It is free and must never be sold.** Full text: [NOTICE](../NOTICE).

This guide is for players. Your host runs the server. You only need the
launcher and your invite. **You do not need to forward any ports.**

---

## 1. What you need

- **Windows 10 or 11, 64-bit.**
- **Your own legitimate copy of FIFA 17 for PC**, installed through **EA app**
  and **fully updated** (final version 1.0.48.30259). Start it once normally
  so EA app finishes any updates.
- **The game installed in a normal folder**, for example `C:\Games\FIFA 17`.

  > ⚠️ **Do not install the game in a protected folder** such as
  > `C:\Program Files` or `C:\Program Files (x86)`. The launcher must place
  > two files next to `FIFA17.exe`, and Windows blocks this in protected
  > folders. If your game is there now, uninstall it in EA app and install it
  > again, choosing a folder such as `C:\Games` as the install location.

- **[.NET 8 Desktop Runtime (x64)](https://dotnet.microsoft.com/download/dotnet/8.0)**.
  On that page, under **.NET Desktop Runtime 8**, download and install the
  **Windows x64** installer.
- From your host, sent to you privately:
  - **the launcher zip**, for example `ProjectRevival17-0.1.0-r1.zip`
  - **your invite code**, a long text starting with `FUT1-`

  Keep your invite private: anyone who has it can play as you.

## 2. Install the launcher

1. Create a new folder, for example `C:\ProjectRevival17`. **Do not use the
   game folder.**
2. Extract the **whole** zip into that folder.
3. Open the extracted folder (for example `ProjectRevival17-r1`) and run
   **`RevivalLauncher.exe`**.
   - If Windows SmartScreen says "Windows protected your PC", click
     **More info → Run anyway**. The launcher is not code-signed.

## 3. First-time setup

The large button at the bottom right always shows the next step.

1. **Find FIFA 17.** The launcher usually finds the game by itself. If it
   doesn't, click **Find FIFA 17** (or open **FIFA installation → Browse for
   FIFA17.exe…**) and select `FIFA17.exe` in your game folder.
2. **Paste your invite** into **YOUR INVITE** and click **Use this invite**.
3. Click **Install / apply Revival files**. The launcher places `version.dll`
   and `fifa17-revival.ini` next to `FIFA17.exe` and keeps a backup of
   anything it replaces.

> ⚠️ The generated `fifa17-revival.ini` contains your account password in
> plaintext. Never share this file.

## 4. Every time you play

1. Make sure your host's server is running.
2. Open **RevivalLauncher.exe** and click **Prepare connection**.
3. When the launcher says it is waiting for FIFA, start **FIFA 17 from EA app**
   as usual.
4. **Keep the launcher open while you play.** It keeps your connection to the
   server active. You can use **Minimize to tray**.

In the game, open **Ultimate Team** as normal.

## 5. Playing online with friends on the same server

- Online Single Match, Online Seasons and Online Draft find opponents among
  the players on your server.
- Both players must choose **the same mode** and start searching **at about
  the same time** (within the matchmaking window your host set, usually two
  minutes).
- Matches are played directly between players. No port forwarding is needed
  by players.

## 6. New invite, update or uninstall

- **New invite from your host:** **Account and maintenance → Replace
  invite…**, paste it, then click **Install / apply invite** if asked.
- **New launcher version:** extract the new zip into a **new, empty** folder
  and run the new `RevivalLauncher.exe`. It updates the game files when you
  click **Install / apply Revival files**.
- **Something seems broken:** **Account and maintenance → Repair files**.
- **Uninstall:** **Account and maintenance → Uninstall Revival**. This removes
  the files from the game folder and restores anything that was there before.
  Then delete the launcher folder.

## 7. Troubleshooting

| Problem | What to do |
|---|---|
| "The game folder could not be written to" | The game is in a protected folder such as Program Files. Reinstall it into a normal folder such as `C:\Games\FIFA 17` (see section 1). |
| "Your invite was refused" | Ask your host for a new invite and use **Replace invite…**. |
| "The server certificate changed" | Your host's server changed. Ask your host for a new invite. |
| "The launcher release is not compatible with this server" | Ask your host for the launcher zip that matches their server. |
| "This release is incomplete or modified" | Extract the **whole** zip again into a **new, empty** folder. |
| "Another mod's version.dll is already installed" | Another mod uses the same file. Remove it from the game folder yourself, then click **Install / apply Revival files**. |
| "This build of FIFA 17 has not been tested" | Update the game to the final version in EA app. |
| "You are not eligible to use online … age restriction" in game | The game could not reach the server when it started. Check that the host's server is running and the launcher shows a working connection, then restart the game. |
| Antivirus removes or blocks `version.dll` | `version.dll` loads into the game to redirect it, which some antivirus programs flag. Restore it or add an exception, then click **Repair files**. |
| You can't find an opponent | Both players must search in the same mode at the same time. |

If you need help, open **Connection details → Copy diagnostic report** and
send the text to your host. Passwords, invites and paths are removed from it
automatically.

---

**Disclaimer.** Project Revival 17 is unofficial and non-commercial. It is not
affiliated with, endorsed by or connected to any game publisher, and all
trademarks belong to their respective owners. No profit is made from it, and
it must never be sold. You need your own legitimate copy of the game. See
[NOTICE](../NOTICE).
