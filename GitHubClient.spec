# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 修改这里：把用到的图标都打包进去
    datas=[
        ('tubiao/tubiao.ico', 'tubiao'),
        ('tubiao/logo.png', 'tubiao'),  # 如果你有做 login 界面的 logo 就加上，没有可以删掉这行
    ],
    hiddenimports=[
        # pystray 针对不同系统的后端
        'pystray._win32',
        'pystray._darwin',
        'pystray._xorg',
        # keyring 针对不同系统的后端
        'keyring.backends.Windows',
        'keyring.backends.macOS',
        'keyring.backends.SecretService',
        'keyring.backends.kwallet',
        # 补全 Windows 系统下的凭据依赖
        'win32ctypes.pywin32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['plyer', 'win10toast', 'tkinter.test', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=False,  # 保持 False 关闭黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='tubiao/tubiao.ico',  # 这里已经指定了 exe 文件本身在资源管理器里的图标
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