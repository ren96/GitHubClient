# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import copy_metadata

# ---------- 数据文件 ----------
_datas = []
if os.path.exists('tubiao/tubiao.ico'):
    _datas.append(('tubiao/tubiao.ico', 'tubiao'))
if os.path.exists('tubiao/logo.png'):
    _datas.append(('tubiao/logo.png', 'tubiao'))

# 复制几个包的元数据（运行时可能通过 importlib.metadata 反查）
for _pkg in ('keyring', 'markdown', 'pystray'):
    try:
        _datas += copy_metadata(_pkg)
    except Exception:
        pass

# ---------- 隐式导入 ----------
_hidden = [
    # pystray 各平台后端
    'pystray._win32',
    'pystray._darwin',
    'pystray._xorg',

    # keyring 各平台后端
    'keyring.backends.Windows',
    'keyring.backends.macOS',
    'keyring.backends.SecretService',
    'keyring.backends.kwallet',

    # Windows 凭据依赖
    'win32ctypes.pywin32',

    # markdown 扩展（repo_detail.py 动态传入字符串，静态分析扫不到）
    'markdown.extensions.fenced_code',
    'markdown.extensions.tables',
    'markdown.extensions.extra',
    'markdown.extensions.nl2br',

    # README 渲染库
    'tkhtmlview',

    # Pillow 的 Tkinter 集成 + 图片插件
    'PIL._tkinter_finder',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL._imagingtk',
    'PIL.IcoImagePlugin',
    'PIL.PngImagePlugin',

    # sqlite3（config.py 的 Cache 使用）
    '_sqlite3',
    'sqlite3',
]

# ---------- Analysis ----------
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 增加排除项，避免环境中自带的巨型数据科学库被误打包进去，显著减小体积
    excludes=[
        'plyer', 'win10toast', 'tkinter.test', 'unittest',
        'pydoc', 'doctest', 'pip', 'setuptools', 'wheel', 'pytest',
        'numpy', 'pandas', 'scipy', 'matplotlib', 'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# ---------- EXE ----------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GitHubClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='tubiao/tubiao.ico' if os.path.exists('tubiao/tubiao.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GitHubClient',
)