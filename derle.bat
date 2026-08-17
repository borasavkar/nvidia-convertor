@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo  VidForge - EXE DERLEME
echo ============================================================
echo.

rem --- 1) Uygulama acikken derlenemez -------------------------------------
rem PyInstaller ciktiyi dist\VidForge icine yazar; program aciksa exe
rem kilitlidir ve derleme yarida "Permission denied" ile coker.
tasklist /FI "IMAGENAME eq VidForge.exe" 2>nul | find /I "VidForge.exe" >nul
if not errorlevel 1 (
    echo [DUR] VidForge su anda ACIK.
    echo       Once programi kapatin, sonra bu dosyayi tekrar calistirin.
    echo.
    pause
    exit /b 1
)

rem --- 2) Python secimi ---------------------------------------------------
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [!] .venv bulunamadi, sistem Python'u denenecek.
    set "PY=python"
)

rem --- 3) Derleme ---------------------------------------------------------
echo Derleniyor... (ilk derleme birkac dakika surebilir)
echo.
"%PY%" -m PyInstaller --noconfirm VidForge.spec
if errorlevel 1 (
    echo.
    echo [HATA] Derleme basarisiz. Yukaridaki mesaja bakin.
    echo        Sik sebep: "pip install pyinstaller" yapilmamis olmasi.
    echo.
    pause
    exit /b 1
)

rem --- 4) Sonuc -----------------------------------------------------------
echo.
if exist "dist\VidForge\VidForge.exe" (
    echo ============================================================
    echo  TAMAM. Yeni exe:
    echo    %CD%\dist\VidForge\VidForge.exe
    for %%F in ("dist\VidForge\VidForge.exe") do echo    Derleme zamani: %%~tF
    echo.
    echo  Programi acinca baslikta surum ve derleme zamani yazar;
    echo  dogru exe'yi calistirdiginizi oradan dogrulayabilirsiniz.
    echo ============================================================
) else (
    echo [HATA] Derleme bitti ama exe bulunamadi.
)
echo.
pause
