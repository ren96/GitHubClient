# GitHub Desktop Client

A Tkinter-based GitHub desktop client supporting repository management, Issue / PR browsing and operations, Gists, downloads, notification polling, auto-update, and more.

> **Note on feature parity**
> This English README mirrors the Chinese `README.md`. A few items in the feature list do **not** match the current codebase. They are flagged with ⚠️ below and summarized in the [Known Inconsistencies](#known-inconsistencies) section at the end.

## Features

- 📁 **My Repositories**: paginated browsing, sorting, filtering, favorites, mute, context menu (open local / VS Code / terminal / ZIP / clone / pull)
- 🔍 **Search**: repositories, code, trending; local history dropdown
- 📝 **Issues**: list, pagination, filter, create, edit, close / reopen, comment, permanent delete
- 🔀 **PR**: list, detail, file changes, Diff, Review (approve / request changes / comment), merge / close
- 🔔 **Notifications**: polling, ⚠️ unread badge, muted repositories
  - *Polling and mute filtering work. The "unread badge" is **not implemented**; new unread items trigger a desktop notification only.*
- ⭐ **Starred**: browse and unstar
- 📝 **Gists**: list, create, edit, delete, create from clipboard
- 📥 **Download queue**: concurrent Release asset downloads, pause / resume / retry / reveal
- 🚀 **Upload local project**: auto `init` / `commit` / `push`, optional auto-generated `.gitignore`
- 🎨 **Theme**: follow system / light / dark
- 🔐 **Login**: PAT or OAuth Device Flow; token stored in the system keyring (falls back to a `600`-permission file)
- 🔔 **Tray**: ⚠️ minimize to tray, desktop notifications
  - *Desktop notifications work (via native Windows Toast / macOS Notification Center / `notify-send` on Linux). The **system tray / minimize-to-tray behavior is not implemented**; `pystray` is listed in `requirements.txt` but never imported or used in the code. See [Known Inconsistencies](#known-inconsistencies).*
- ⬆️ **Auto-update**: distributed via GitHub Releases, supports `stable` / `beta` channels, download-and-install, skip specific version
- ⌨️ **Shortcuts**: `Ctrl+F` search / `Ctrl+K` command palette / `Ctrl+N` new Issue / `Ctrl+S` toggle theme / `Ctrl+P` settings / `Ctrl+U` check update / `Ctrl+Q` quit / `F5` refresh / `F1` shortcuts panel / `Delete` delete selected Issue

## Requirements

- **Python 3.9+** (3.10 or newer recommended)
- **Tkinter**
  - Windows / macOS: bundled with the official Python installer
  - Linux: install the system package, e.g. Debian/Ubuntu `sudo apt install python3-tk`, Fedora `sudo dnf install python3-tkinter`
- **Git** (for `git clone` / `git pull` / project upload), must be on `PATH`

## Install dependencies

```bash
pip install -r requirements.txt
```

> ⚠️ `pystray` is currently listed in `requirements.txt` but is **not used** by the code. You may safely drop it if you trim the dependency list.

## Run

```bash
python main.py
```

On first launch the login screen appears. Choose PAT or OAuth Device Flow as described below.

## Login

Two methods are supported:

1. **Personal Access Token (PAT)**
   - Go to <https://github.com/settings/tokens> and generate a token. Recommended scopes: `repo`, `read:user`, `notifications`, `gist`.
   - Paste it into the login box and check "Remember login" to save it to the system keyring.
   - If the `GITHUB_TOKEN` environment variable is set, it is pre-filled into the login box.
2. **OAuth Device Flow**
   - Create an OAuth App at <https://github.com/settings/developers> and put the **Client ID** into *Settings → OAuth App Client ID* (no `client_secret` is needed for Device Flow).
   - Click "🔐 OAuth login" and follow the prompt to visit the link and enter the code.

**Token storage**: prefers the system keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service). If unavailable, it falls back to the `tokens` field inside the config file, which is created with `600` permissions.

## Configuration

The config directory is platform-specific:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\github-client` |
| macOS | `~/Library/Application Support/github-client` |
| Linux | `$XDG_CONFIG_HOME/github-client` or `~/.config/github-client` |

Files inside:

| File | Purpose |
|------|---------|
| `config.json` | Settings: proxy, theme, font size, recent repos, favorites, muted repos, update source, etc. |
| `cache.db` | SQLite cache (ETag, repository / Issue / PR lists). Delete to reset. |
| `app.log` | Runtime log |

The "📂 Open config directory" button in the *About* dialog jumps straight to this folder.

### Proxy

Set *Settings → HTTP / HTTPS proxy* to something like `http://127.0.0.1:7890` (leave empty for direct connection). The proxy applies to:

- REST / GraphQL requests
- Release asset and zipball downloads
- `git clone` / `git pull` / `git push` (injected via `-c http.proxy=...` so the global Git config is not polluted)

### Theme and font size

Supports *Follow system / Light / Dark* and a font size from 8 to 16. Toggle quickly via the *⋮ More → Toggle theme* menu or `Ctrl+S`.

### Auto-update

- Set the update source repository (`owner/repo`) under *Settings → Auto-update*. Its **Releases** are the update source.
- Channels:
  - `stable`: uses the latest release only
  - `beta`: iterates all releases and takes the newest pre-release
- Installer assets are matched per platform: `.exe / .msi` on Windows, `.dmg / .pkg` on macOS, `.AppImage / .deb / .rpm` on Linux.
- "Skip this version" records `skipped_version` so the same release is not prompted again.

## Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+F` | Focus search |
| `Ctrl+K` | Command palette |
| `Ctrl+N` | New Issue |
| `Ctrl+S` | Toggle theme (follow system / light / dark) |
| `Ctrl+P` | Open settings |
| `Ctrl+U` | Check for updates |
| `Ctrl+Q` | Quit |
| `F5` | Refresh current page |
| `F1` | Show shortcuts panel |
| `Delete` | Delete selected Issue |
| Double-click repository | Open repository detail |

## Project structure

```text
.
├── main.py              # Entry point (sets AppUserModelID, logging, launches main window)
├── app.py               # Main window GitHubApp: login, tabs, theme, polling, shortcuts
├── api.py               # GitHub REST / GraphQL wrapper (ETag cache, rate limit handling)
├── config.py            # ConfigStore (JSON) and Cache (SQLite)
├── utils.py             # Utility helpers: time/byte formatting, logging, notifications, paths, theme detection
├── dialogs.py           # Dialogs: Issue, create repo, comment, settings, OAuth, upload, update, asset picker
├── about.py             # About dialog (runtime environment / dependencies / quick actions)
├── updater.py           # Auto-update: version parsing, Release lookup, asset selection, install
├── oauth.py             # OAuth Device Flow implementation
├── command_palette.py   # Ctrl+K command palette
├── download_queue.py    # Download queue window
├── repo_detail.py       # Repository detail window (README / files / branches / commits / Releases / Actions)
├── issue_detail.py      # Issue detail window
├── pr_detail.py         # PR detail window (overview / files / Diff / Review / merge)
├── gist_tab.py          # Gists tab
├── version.py           # Version / app name / app ID
├── make_ico.py          # Generate multi-size ico from tubiao/logo.png
├── requirements.txt
├── tubiao/
│   ├── logo.png         # Logo for About / login page
│   └── tubiao.ico       # Window / taskbar icon
└── README.md
```

## Generate icons

`tubiao/tubiao.ico` is generated from `tubiao/logo.png` and contains 16 / 24 / 32 / 48 / 64 / 128 / 256 sizes:

```bash
python make_ico.py
```

## Packaging as an executable

Use [PyInstaller](https://pyinstaller.org/):

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile ^
  --name "GitHub客户端" ^
  --icon "tubiao/tubiao.ico" ^
  --add-data "tubiao;tubiao" ^
  main.py
```

On macOS / Linux, replace the line-continuation `^` with `\` and the `--add-data` separator `;` with `:`.

Notes:

- The `tubiao` directory must be bundled as data. `utils.get_base_dir()` reads `sys._MEIPASS` in onefile mode and the executable's directory in onedir mode.
- Run `python make_ico.py` first to generate the multi-size ico.
- With `--noconsole`, external subprocesses (such as Git) are launched hidden through `utils.no_window_kwargs()`.
- On macOS, use `--windowed` instead (`--noconsole` has no effect).

## Data and privacy

- Tokens are stored in the system keyring whenever possible; otherwise a local file with `600` permissions is used.
- All network requests go to `api.github.com`; with a proxy configured, both HTTP and HTTPS traffic is proxied.
- Repository lists, Issues, PRs, etc. are cached in local SQLite (`cache.db`) for offline viewing and to reduce API calls. Delete this file to reset.
- Desktop notifications use native APIs (Windows Toast / macOS Notification Center / Linux `notify-send` or `zenity` / `kdialog`) with no third-party service.

## FAQ

**Q: Linux reports `No module named tkinter`?**
Install the system package: Debian/Ubuntu `sudo apt install python3-tk`; Fedora `sudo dnf install python3-tkinter`.

**Q: Upload project or `git clone` complains that Git is missing?**
Install Git and make sure `git` is on `PATH`; on Windows use Git for Windows.

**Q: API rate limit message?**
Unauthenticated requests have a lower quota. Make sure you are logged in; if the limit is still hit, switch networks via *Settings → Proxy* or wait — the error message includes the recommended wait time.

**Q: Icons / logo missing after packaging?**
Ensure the PyInstaller command includes `--add-data "tubiao;tubiao"` (use `:` on macOS/Linux) and that `tubiao/tubiao.ico` has been generated.

**Q: Some widget backgrounds do not follow the dark theme?**
The app broadcasts theme changes to registered windows and Treeviews. If any leftover appears, toggle the theme once via `Ctrl+S` or restart the app.

## Third-party dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP requests |
| `keyring` | Store tokens in the system keyring |
| `Pillow` | Image processing (logo / icon) |
| `markdown` | Render README Markdown |
| `tkhtmlview` | HTML view for README |
| ⚠️ `pystray` | Tray (optional) — **currently unused in code** |

> ⚠️ `pystray` is declared in `requirements.txt` but no module imports it, and no tray icon is ever created. See [Known Inconsistencies](#known-inconsistencies).

## Contributing

Issues and Pull Requests are welcome. Before submitting:

- `python main.py` runs successfully locally
- UI changes work under both light and dark themes
- No new dependency that conflicts with existing ones is introduced

## Known Inconsistencies

The following items in the feature list do **not** match the current codebase. They are kept in the list for roadmap visibility but marked ⚠️.

| Item | Status | Details |
|------|--------|---------|
| 🔔 System tray (minimize to tray) | ❌ Not implemented | `app.py` contains no `pystray` import and no tray window. `_update_tray_badge(self, unread)` is an empty `pass` stub. The `pystray` package is listed in `requirements.txt` but never used. |
| 🔔 Unread badge | ❌ Not implemented | There is no tray badge or window badge. `_poll_notifications()` calls `notify_desktop(...)` when the unread count increases, but no persistent visual indicator is updated. |
| 📦 `pystray` dependency | ⚠️ Declared but unused | Listed in `requirements.txt` as "Tray (optional)". Safe to remove if a lean dependency list is desired. |
| 🔔 Desktop notifications | ✅ Works | Implemented in `utils.notify_desktop()` and called from `_poll_notifications()`. |

Everything else in the feature list is backed by code in the current tree.

## License

This project is released under the [MIT License](LICENSE).