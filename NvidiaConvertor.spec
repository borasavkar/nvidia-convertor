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
import sys
from PyInstaller.utils.hooks import collect_all

ONEDIR = True

# Buradaki klasorde ffmpeg.exe/ffprobe.exe varsa cikti ile birlikte paketlenir;
# boylece hedef makineye FFmpeg kurmak gerekmez.
#
# Bos birakilirsa (ya da klasor yoksa) FFmpeg PAKETLENMEZ; uygulama calisirken
# kendi yanina, PATH'e ve yaygin kurulum konumlarina bakar, bulamazsa kullanici
# arayuzden klasoru gosterebilir (bkz. find_tool / select_ffmpeg_dir).
#
# NOT: scoop'un "current" klasoru bir junction'dir; FFmpeg'i guncelledigimde
# pakete giren surum de degisir. Surumu sabitlemek istersen ikilileri sabit bir
# klasore kopyalayip yolu oraya cevir.
FFMPEG_DIR = os.path.join(os.environ.get('USERPROFILE', ''),
                          'scoop', 'apps', 'ffmpeg', 'current', 'bin')

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

# --- Tcl/Tk 9 (Python 3.14) ---
# Python 3.14'te Tcl betik kutuphanesi DLL icine gomulu bir zipfs'te duruyor;
# PyInstaller 6.21 onu okuyamiyor ve "TclTkInfo: ... does not exist!" uyarisi
# verip TOPLAMIYOR. Toplanmazsa uretilen exe acilista FileNotFoundError ile
# cokuyor. Asagidaki yardimci Tcl'in kendi komutlariyla zipfs'ten diske cikarir.
sys.path.insert(0, os.path.abspath('tools'))
try:
    from collect_tcl9 import cikar as _tcl9_cikar
    _tcl_dizin, _tk_dizin = _tcl9_cikar(os.path.abspath('build_tcl'))
    if _tcl_dizin:
        datas += [(_tcl_dizin, '_tcl_data'), (_tk_dizin, '_tk_data')]
        print('spec: Tcl 9 betik kutuphaneleri zipfs disina cikarildi ve eklendi')
except Exception as _hata:                                    # pragma: no cover
    print('spec: Tcl 9 cikarma atlandi (%s)' % _hata)

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
