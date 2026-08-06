# -*- mode: python ; coding: utf-8 -*-
#
# Derleme:  pyinstaller --noconfirm NvidiaConvertor.spec
#
# DIKKAT: "pyinstaller ... NvidiaConvertor.py" seklinde CLI bayraklariyla
# derlemek bu dosyanin UZERINE YAZAR ve buradaki ayarlar kaybolur.
# Ayar degistirmek icin bu dosyayi duzenleyip yukaridaki komutu kullanin.
#
# ONEDIR = True  -> klasor cikti (tasinabilir dagitim icin onerilen)
# ONEDIR = False -> tek dosya exe (her acilista icerigi temp'e acar)
import os
from PyInstaller.utils.hooks import collect_all

ONEDIR = True

# Proje klasorunde "ffmpeg" adinda bir klasor varsa icindeki ffmpeg.exe ve
# ffprobe.exe cikti ile birlikte paketlenir; boylece hedef makineye FFmpeg
# kurmak gerekmez. Yoksa uygulama PATH'e duser (bkz. find_tool).
FFMPEG_DIR = os.path.abspath('ffmpeg')

datas = [('icon.ico', '.')]
binaries = []
hiddenimports = []

for paket in ('customtkinter', 'tkinterdnd2'):
    # tkinterdnd2 kendi tkdnd Tcl kutuphanelerini paket verisi olarak tasir;
    # toplanmazsa surukle-birak derlenmis exe'de calismaz.
    tmp_ret = collect_all(paket)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

if os.path.isdir(FFMPEG_DIR):
    for arac in ('ffmpeg.exe', 'ffprobe.exe'):
        yol = os.path.join(FFMPEG_DIR, arac)
        if os.path.isfile(yol):
            binaries.append((yol, '.'))

a = Analysis(
    ['NvidiaConvertor.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

ortak = dict(
    name='NvidiaConvertor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX kapali: sikistirilmis exe'ler antivirus yanlis pozitifi uretmeye
    # egilimli ve acilisi yavaslatir.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **ortak)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   upx_exclude=[], name='NvidiaConvertor')
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              runtime_tmpdir=None, upx_exclude=[], **ortak)
