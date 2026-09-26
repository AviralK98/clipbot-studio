# ClipBot for Windows

ClipBot runs as one program with an icon in the taskbar tray. It opens the dashboard in your browser,
keeps working in the background, and posts on schedule as long as it's running (turn on
**Start with Windows** so it always is). No terminals, no `.env` file.

## Install

1. Run `ClipBot-Setup.exe`. It installs for your Windows account only (no administrator prompt) and
   offers a desktop shortcut and starting with Windows.
2. On first launch ClipBot asks where to keep your **clips**. They take a lot of space (about 2 to 3 GB
   per long video), so pick a drive with room. The database stays in `%LOCALAPPDATA%\ClipBot`.
3. The dashboard opens at <http://127.0.0.1:8742>. Create your studio password.
4. You land on **Connections**. Add your keys there (below), then click **Connect YouTube**.

Right-click the tray icon for: Open ClipBot, Pause posting, Start with Windows, Open clips folder,
Open logs, Reset studio password, Quit.

## Your keys

Keys are stored in **Windows Credential Manager**, encrypted to your Windows account. ClipBot never
shows a saved key again; paste a new one over it to change it.

| Service | What it's for | Where to get the key |
| --- | --- | --- |
| OpusClip | Finds clips; posts to TikTok (Pro plan) | Your OpusClip account's API settings |
| Vizard | A second clipping engine (optional) | Your Vizard account's API settings |
| Google Gemini | Watches your Shorts for AI insights (free tier works) | <https://aistudio.google.com/apikey> |
| YouTube | Posting Shorts and reading their stats | Your own Google Cloud project (next section) |

### YouTube: your own Google Cloud project (about 15 minutes, once)

Each ClipBot uses its owner's own Google project, so there's no review by Google and you get
YouTube's full daily allowance (about 6 uploads a day at the default quota).

1. Open <https://console.cloud.google.com>, sign in with the account that owns your channel, and
   create a project (any name).
2. **APIs & Services > Library**: enable **YouTube Data API v3** and **YouTube Analytics API**.
3. **Google Auth Platform**: fill in **Branding** (app name and your email). Under **Audience**, keep
   it in **Testing** and add your own Google account as a **test user**.
4. **Google Auth Platform > Clients > Create client**: application type **Desktop app**. Copy the
   **Client ID** and **Client secret** into ClipBot (Connections > YouTube).
5. **APIs & Services > Credentials > Create credentials > API key**. Restrict it to YouTube Data
   API v3 and paste it into ClipBot as the API key.
6. Click **Save YouTube settings**, then **Connect YouTube**. Sign in, tick every permission, and
   approve. If Google says the app isn't verified, click Continue: it's your own app. ClipBot adds
   your channel as a destination automatically.

While the project is in Testing, Google ends the login after **7 days**. When that happens ClipBot
waits (posts and stats are held, nothing is lost) and asks you to click **Reconnect YouTube**.

## Where things are

| What | Where |
| --- | --- |
| The app | `%LOCALAPPDATA%\Programs\ClipBot` |
| Keys | Windows Credential Manager, entries named `ClipBot` |
| Settings | `%APPDATA%\ClipBot\config.json` (clips folder, port) and `settings.json` |
| Database and logs | `%LOCALAPPDATA%\ClipBot` |
| Clips | The folder you chose on first run |

Uninstalling keeps your clips, database and keys, so reinstalling picks up where you left off.
If port 8742 is taken by another program, set `"port"` in `config.json`.

Coming from a `.env` setup? `ClipBot.exe --import-env C:\path\to\.env` moves its keys into
Credential Manager and its settings into `settings.json`.

## Building it

Needs Python 3.12, Node 22 and, for the installer, [Inno Setup 6](https://jrsoftware.org/isinfo.php).

    py -3.12 -m venv .venv
    .venv\Scripts\pip install -e .[desktop,build]
    cd apps\frontend && npm ci && cd ..\..
    powershell -File scripts\build_windows.ps1

That builds `dist\ClipBot\ClipBot.exe` and, with Inno Setup installed, `dist\ClipBot-Setup.exe`.
To run from source instead: build the dashboard with `CLIPBOT_STATIC=1 npm run build` in
`apps/frontend`, then `python -m clipbot.desktop`.

Servers and Docker keep using environment variables (see README); they always take priority over
anything saved in the app.
