# GitHub 桌面客户端

一个基于 Tkinter 的 GitHub 桌面客户端，支持仓库管理、Issue / PR 浏览与操作、Gist、下载、通知轮询、自动更新等。

## 功能

- 📁 我的仓库：分页浏览、排序、筛选、收藏、静音、右键菜单（打开本地 / VS Code / 终端 / ZIP / clone / pull）
- 🔍 搜索：仓库、代码、趋势；支持本地历史记录下拉
- 📝 Issues：列表、分页、筛选、新建、编辑、关闭/重开、评论、永久删除
- 🔀 PR：列表、详情、文件变更、Diff、Review（批准 / 请求修改 / 评论）、合并 / 关闭
- 🔔 通知：轮询、未读徽标、静音仓库
- ⭐ Starred：浏览与取消 Star
- 📝 Gists：列表、创建、编辑、删除、从剪贴板创建
- 📥 下载队列：Release 资产并发下载、暂停 / 继续 / 重试 / 定位
- 🚀 上传本地项目：自动 init / commit / push，可自动生成 `.gitignore`
- 🎨 主题：跟随系统 / 浅色 / 深色
- 🔐 登录：PAT 或 OAuth Device Flow；Token 保存在系统密钥环（不可用时回退到 `600` 权限文件）
- 🔔 托盘：最小化到托盘，桌面通知
- ⬆️ 自动更新：通过 GitHub Release 分发，支持 stable / beta 通道、下载并安装、忽略指定版本
- ⌨️ 快捷键：`Ctrl+F` 搜索 / `Ctrl+K` 命令面板 / `Ctrl+N` 新建 Issue / `Ctrl+S` 切换主题 / `Ctrl+P` 设置 / `Ctrl+U` 检查更新 / `Ctrl+Q` 退出 / `F5` 刷新 / `F1` 快捷键面板 / `Delete` 删除选中 Issue

## 环境要求

- **Python 3.9+**（推荐 3.10 或更高）
- **Tkinter**
  - Windows / macOS：官方 Python 自带
  - Linux：需安装系统包，例如 Debian/Ubuntu `sudo apt install python3-tk`，Fedora `sudo dnf install python3-tkinter`
- **Git**（用于 `git clone` / `git pull` / 上传项目），需在 `PATH` 中

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

首次启动会显示登录界面，可按下方「登录」一节选择 PAT 或 OAuth Device Flow 登录。

## 登录

支持两种方式：

1. **Personal Access Token (PAT)**
   - 前往 <https://github.com/settings/tokens> 生成 Token，建议勾选 `repo`、`read:user`、`notifications`、`gist` 等 scope。
   - 粘贴到登录框，勾选「记住登录」以保存到系统密钥环。
   - 若环境变量 `GITHUB_TOKEN` 存在，会自动填入登录框。
2. **OAuth Device Flow**
   - 先在 <https://github.com/settings/developers> 创建一个 OAuth App，把 **Client ID** 填入「设置 → OAuth App Client ID」（Device Flow 不需要 client_secret）。
   - 点击「🔐 OAuth 登录」，按提示访问链接并输入授权码即可。

**Token 存储**：优先写入系统密钥环（Windows Credential Manager / macOS Keychain / Linux Secret Service）。系统不支持时，回退到配置文件中的 `tokens` 字段，文件权限为 `600`。

## 配置

配置目录按平台区分：

| 平台 | 路径 |
|------|------|
| Windows | `%APPDATA%\github-client` |
| macOS | `~/Library/Application Support/github-client` |
| Linux | `$XDG_CONFIG_HOME/github-client` 或 `~/.config/github-client` |

目录内主要文件：

| 文件 | 说明 |
|------|------|
| `config.json` | 配置：代理、主题、字号、最近仓库、收藏、静音、更新源等 |
| `cache.db` | SQLite 缓存（ETag、仓库 / Issue / PR 列表等），可删除以重置 |
| `app.log` | 运行日志 |

「关于」对话框中的「📂 打开配置目录」可直接定位到该目录。

### 代理

「设置 → HTTP / HTTPS 代理」填写形如 `http://127.0.0.1:7890` 的地址（留空直连）。该代理会同时应用于：

- REST / GraphQL 请求
- Release 资产与 zipball 下载
- `git clone` / `git pull` / `git push`（通过 `-c http.proxy=...` 传入，避免污染全局 Git 配置）

### 主题与字号

支持「跟随系统 / 浅色 / 深色」，字号 8–16 可调。可通过顶部「⋮ 更多 → 切换主题」或 `Ctrl+S` 快速切换。

### 自动更新

- 在「设置 → 自动更新」填写更新源仓库（`owner/repo`）。该仓库的 **Release** 将作为更新来源。
- 通道：
  - `stable`：只取 latest release
  - `beta`：遍历所有 release，取最新预发布版本
- 安装包按平台自动匹配：Windows `.exe/.msi`，macOS `.dmg/.pkg`，Linux `.AppImage/.deb/.rpm`。
- 可「忽略此版本」，下次不再提示（写入 `skipped_version`）。

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+F` | 聚焦搜索 |
| `Ctrl+K` | 命令面板 |
| `Ctrl+N` | 新建 Issue |
| `Ctrl+S` | 切换主题（跟随系统 / 浅色 / 深色） |
| `Ctrl+P` | 打开设置 |
| `Ctrl+U` | 检查更新 |
| `Ctrl+Q` | 退出程序 |
| `F5` | 刷新当前页 |
| `F1` | 显示快捷键面板 |
| `Delete` | 删除选中的 Issue |
| 双击仓库 | 查看仓库详情 |

## 项目结构

```text
.
├── main.py              # 入口（设置 AppUserModelID、日志、启动主窗口）
├── app.py               # 主窗口 GitHubApp：登录、标签页、主题、轮询、快捷键
├── api.py               # GitHub REST / GraphQL 封装（含 ETag 缓存、限流处理）
├── config.py            # ConfigStore（JSON 配置）与 Cache（SQLite 缓存）
├── utils.py             # 通用工具：时间/字节格式化、日志、通知、路径、主题探测等
├── dialogs.py           # 各类对话框：Issue、新建仓库、评论、设置、OAuth、上传、更新、资产选择
├── about.py             # 关于对话框（运行环境 / 依赖 / 快捷操作）
├── updater.py           # 自动更新：版本解析、Release 查询、安装包选择、安装
├── oauth.py             # OAuth Device Flow 实现
├── command_palette.py   # Ctrl+K 命令面板
├── download_queue.py    # 下载队列窗口
├── repo_detail.py       # 仓库详情窗口（README / 文件 / 分支 / 提交 / Release / Actions）
├── issue_detail.py      # Issue 详情窗口
├── pr_detail.py         # PR 详情窗口（概览 / 文件 / Diff / Review / 合并）
├── gist_tab.py          # Gists 标签页
├── version.py           # 版本号 / 应用名 / App ID
├── make_ico.py          # 由 tubiao/logo.png 生成多尺寸 ico
├── requirements.txt
├── tubiao/
│   ├── logo.png         # 关于 / 登录页 Logo
│   └── tubiao.ico       # 窗口 / 任务栏图标
└── README.md
```

## 生成图标

`tubiao/tubiao.ico` 由 `tubiao/logo.png` 生成，包含 16 / 24 / 32 / 48 / 64 / 128 / 256 多种尺寸：

```bash
python make_ico.py
```

## 打包为可执行文件

使用 [PyInstaller](https://pyinstaller.org/)：

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile ^
  --name "GitHub客户端" ^
  --icon "tubiao/tubiao.ico" ^
  --add-data "tubiao;tubiao" ^
  main.py
```

macOS / Linux 需将续行符 `^` 换成 `\`，并把 `--add-data` 的分隔符 `;` 换成 `:`。

注意事项：

- 必须把 `tubiao` 目录作为 data 一并打包。`utils.get_base_dir()` 在 PyInstaller onefile 模式下会读取 `sys._MEIPASS`，onedir 模式下读取可执行文件所在目录。
- 建议先运行 `python make_ico.py` 生成多尺寸 ico。
- 使用 `--noconsole` 后，Git 等外部子进程已通过 `utils.no_window_kwargs()` 隐藏控制台窗口。
- macOS 上对应参数为 `--windowed`（`--noconsole` 无效）。

## 数据与隐私

- Token 优先保存在系统密钥环；系统不支持时回退到本地文件（权限 `600`）。
- 所有网络请求发往 `api.github.com`；开启代理后 HTTP / HTTPS 均走代理。
- 仓库列表、Issue、PR 等会写入本地 SQLite 缓存（`cache.db`），便于离线查看与减少 API 调用。删除该文件即可重置缓存。
- 桌面通知使用系统原生接口（Windows Toast / macOS 通知中心 / Linux `notify-send` 或 `zenity` / `kdialog`），不依赖第三方服务。

## 常见问题

**Q: Linux 启动报 `No module named tkinter`？**
安装系统包：Debian/Ubuntu `sudo apt install python3-tk`；Fedora `sudo dnf install python3-tkinter`。

**Q: 上传项目或 `git clone` 提示找不到 git？**
安装 Git 并确保 `git` 在 `PATH` 中；Windows 用户可使用 Git for Windows。

**Q: 提示「API 限流」？**
GitHub 未认证请求限额较低。请确认已登录；如已登录仍限流，可在「设置 → 代理」切换网络，或稍后再试（错误信息会显示建议等待的秒数）。

**Q: 打包后图标 / Logo 丢失？**
确认 PyInstaller 命令包含 `--add-data "tubiao;tubiao"`（macOS/Linux 用 `:`），并已生成 `tubiao/tubiao.ico`。

**Q: 深色主题下部分控件背景没有跟随？**
应用会在切换主题时广播给已注册的窗口与 Treeview。若出现遗留，可在 `Ctrl+S` 切换一次主题，或重启应用。

## 第三方依赖

| 包 | 用途 |
|----|------|
| `requests` | HTTP 请求 |
| `keyring` | 系统密钥环存储 Token |
| `Pillow` | 图像处理（Logo / 图标） |
| `markdown` | README Markdown 渲染 |
| `tkhtmlview` | README HTML 视图 |
| `pystray` | 托盘（可选） |

## 贡献

欢迎提交 Issue 与 Pull Request。提交前请确保：

- 本地能正常运行 `python main.py`
- 改动涉及 UI 时，浅色 / 深色主题均能正常显示
- 不引入与现有依赖冲突的新依赖

## 许可证

本项目基于 [MIT License](LICENSE) 发布。