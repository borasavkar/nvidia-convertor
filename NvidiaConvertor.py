import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import os
import sys
import winsound
import time
import shutil
import json
import tempfile
from collections import deque

# Ayarlar kullanicinin profilinde tutulur; program klasoru salt-okunur olabilir
# (Program Files) ve tasinabilir kurulumda da bu yol calisir.
SETTINGS_PATH = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"),
    "NvidiaConvertor", "settings.json"
)


def find_tool(name, tercih_dizin=None):
    """
    ffmpeg/ffprobe konumunu bulur.

    Arama sirasi:
      1. Kullanicinin arayuzden elle gosterdigi klasor (ayarlarda saklanir)
      2. Uygulamanin yani / paketin ici  -> tasinabilir dagitim
      3. PATH                            -> klasik kurulum (Windows ve Linux)
      4. Yaygin kurulum konumlari        -> PATH'e eklenmemis kurulumlar

    Boylece cogu makinede hicbir sey yapmadan bulunur; bulunamazsa kullanici
    arayuzden klasoru gosterebilir.
    """
    exe = name + (".exe" if os.name == "nt" else "")
    altlar = ("", "bin", "ffmpeg", os.path.join("ffmpeg", "bin"))

    def ara(kok):
        for alt in altlar:
            aday = os.path.join(kok, alt, exe)
            if os.path.isfile(aday):
                return aday
        return None

    # 1) kullanicinin gosterdigi klasor
    if tercih_dizin:
        bulunan = ara(tercih_dizin)
        if bulunan:
            return bulunan

    # 2) uygulamanin yani / paket ici
    if getattr(sys, "frozen", False):
        kokler = [os.path.dirname(sys.executable)]
        if getattr(sys, "_MEIPASS", None):
            kokler.append(sys._MEIPASS)
    else:
        kokler = [os.path.dirname(os.path.abspath(__file__))]
    for kok in kokler:
        bulunan = ara(kok)
        if bulunan:
            return bulunan

    # 3) PATH
    yol = shutil.which(name)
    if yol:
        return yol

    # 4) yaygin kurulum konumlari
    for kok in common_tool_dirs():
        bulunan = ara(kok)
        if bulunan:
            return bulunan

    return name


def common_tool_dirs():
    """PATH'e eklenmemis olabilecek yaygin FFmpeg kurulum konumlari."""
    yollar = []
    if os.name == "nt":
        for degisken in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData",
                         "LOCALAPPDATA", "USERPROFILE"):
            kok = os.environ.get(degisken)
            if not kok:
                continue
            yollar += [
                os.path.join(kok, "ffmpeg"),
                os.path.join(kok, "scoop", "apps", "ffmpeg", "current"),
                os.path.join(kok, "chocolatey", "bin"),
                os.path.join(kok, "Microsoft", "WinGet", "Links"),
            ]
        yollar += [r"C:\ffmpeg", r"C:\Program Files\ffmpeg"]
    else:
        yollar += ["/usr/bin", "/usr/local/bin", "/opt/ffmpeg",
                   "/snap/bin", "/var/lib/flatpak/exports/bin",
                   os.path.expanduser("~/.local/bin"),
                   os.path.expanduser("~/bin")]
    return yollar


def tools_usable(ffmpeg_bin, ffprobe_bin):
    """Bulunan ikililerin GERCEKTEN calistigini dogrular ('-version' denemesi)."""
    for arac in (ffmpeg_bin, ffprobe_bin):
        try:
            sonuc = subprocess.run(
                [arac, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if sonuc.returncode != 0:
                return False
        except Exception:
            return False
    return True


def encoder_calisiyor_mu(encoder, ffmpeg_bin=None):
    """
    Bir donanim kodlayicisinin BU makinede gercekten calistigini olcer.

    Kodlayici listesinde gorunmek yetmez: ffmpeg AMD'li bir makinede de
    hevc_nvenc'i listeler, ama calistirinca "Cannot load nvcuda.dll" der.
    Tek guvenilir yontem kucuk bir gercek kodlama denemesi (~0.1-0.3 sn).

    DIKKAT: kare boyutu DENEME_BOYUTU'ndan kucuk olmamali; olculdu, 256x256'da
    hevc_amf/av1_amf "encoder->Init() failed with error 5" verip calisan bir
    karti "yok" gosteriyor.
    """
    try:
        sonuc = subprocess.run(
            [ffmpeg_bin or FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"testsrc2=s={DENEME_BOYUTU}:r=30:d=0.2",
             "-c:v", encoder, "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return sonuc.returncode == 0
    except Exception:
        return False


def donanim_bul(ffmpeg_bin=None):
    """
    Hangi markalarin donanim kodlayicisi kullanilabilir? SAF OLCUM.
    {marka: True/False} dondurur.
    """
    return {marka: encoder_calisiyor_mu(bilgi["deneme"], ffmpeg_bin)
            for marka, bilgi in DONANIM.items()}


def resolve_tools(tercih_dizin=None):
    """FFMPEG_BIN / FFPROBE_BIN global degerlerini yeniden cozer."""
    global FFMPEG_BIN, FFPROBE_BIN
    FFMPEG_BIN = find_tool("ffmpeg", tercih_dizin)
    FFPROBE_BIN = find_tool("ffprobe", tercih_dizin)
    return FFMPEG_BIN, FFPROBE_BIN


FFMPEG_BIN = find_tool("ffmpeg")
FFPROBE_BIN = find_tool("ffprobe")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
    # drop_target_register / dnd_bind bu mixin'den gelir. tkinterdnd2'nin kendi
    # TkinterDnD.Tk sinifini kullanamayiz (CTk'den turemek zorundayiz), bu yuzden
    # mixin'i dogrudan sinifa ekliyoruz.
    _DndBase = TkinterDnD.DnDWrapper
except ImportError:
    HAS_DND = False
    DND_FILES = None

    class _DndBase:
        """tkinterdnd2 kurulu degilken sinif hiyerarsisini bozmayan bos taban."""
        pass

# --- MODERN ARAYÜZ AYARLARI ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# =======================================================
# CQ ARALIK TABLOLARİ (tek yerde tanımlı)
# =======================================================
# NOT: 1440p / 360p / 240p satirlari, mevcut tablonun egrisi uzerinden
# ARA DEGER olarak turetilmistir (olculmus degerler degildir); amac yeni
# cozunurluklerde de tutarli bir "onerilen aralik" gostermektir.
CQ_RANGES = {
    "av1_nvenc": {
        "4K": (45, 50), "1440p": (41, 47), "1080p": (38, 45), "720p": (33, 38),
        "480p": (28, 32), "360p": (25, 29), "240p": (23, 27),
        "default": (38, 45)
    },
    "hevc_nvenc": {
        "4K": (33, 38), "1440p": (30, 36), "1080p": (28, 34), "720p": (24, 28),
        "480p": (20, 24), "360p": (18, 22), "240p": (16, 20),
        "default": (28, 34)
    },
    "h264_nvenc": {
        "4K": (27, 31), "1440p": (25, 29), "1080p": (23, 28), "720p": (19, 23),
        "480p": (16, 19), "360p": (14, 17), "240p": (12, 15),
        "default": (23, 28)
    },
    "libvpx-vp9": {
        "4K": (12, 18), "1440p": (21, 27), "1080p": (28, 34), "720p": (29, 35),
        "480p": (30, 36), "360p": (33, 39), "240p": (34, 40),
        "default": (28, 34)
    },
    # --- AMD (AMF) ---
    # OLCULDU 2026-08-14: ham 1080p50 kaynak (test.y4m), her cozunurluk icin
    # lanczos ile indirilip KAYIPSIZ referansa cevrildi, VMAF ile karsilastirildi.
    # Alt sinir = VMAF 96'ya, ust sinir = VMAF 90'a denk gelen QP.
    # NVENC tablolari KOPYALANMADI: ayni QP iki markada ayni kaliteyi vermiyor
    # (ornek: HEVC 1080p'de NVENC 28-34, AMF 31-35).
    # 240p/360p/1440p/4K satirlari olculen ucun egiminden TURETILDI (kaynak
    # 1080p oldugu icin buyuterek olcmek sahte kolaylik yaratirdi).
    "hevc_amf": {
        "4K": (33, 37), "1440p": (32, 36), "1080p": (31, 35), "720p": (31, 34),
        "480p": (30, 33), "360p": (29, 32), "240p": (28, 31),
        "default": (31, 35)
    },
    "h264_amf": {
        "4K": (33, 37), "1440p": (32, 36), "1080p": (31, 35), "720p": (30, 34),
        "480p": (29, 32), "360p": (28, 31), "240p": (27, 30),
        "default": (31, 35)
    },
    # AV1 AMF'nin QP olcegi 0-255 (digerleri 0-51) - bkz. AMF_QP_TAVANI.
    #
    # 4K/1440p satirlari ONCE turetilmisti (156-172 / 150-166) ve GERCEK 4K
    # icerikle CELISTI: QP144 bile VMAF 82.8 verdi. Turetme, ayni kaynagin
    # KUCULTULMUS hallerinin eğiminden cikarilmisti; kucultunce detay
    # yogunlastigi icin dusuk cozunurluk daha dusuk QP istiyordu ve o egim
    # yukari dogru gecerli degil.
    #
    # 4K yerine gercek 4K olcumu kondu (h264.mp4, 2160x3840):
    #   QP  20 -> VMAF 96.2 (57.2 MB)    QP  70 -> 92.9 (9.6 MB)
    #   QP  50 -> 94.3      (16.0 MB)    QP 104 -> 90.0
    # Ust sinir olculen VMAF 90 noktasi (104). Alt sinir AZALAN GETIRI dizi:
    # QP 70'ten 20'ye inmek 6 kat bit harciyor ama yalnizca 3.3 VMAF puani
    # getiriyor.
    #
    # DIKKAT - IKI OLCUM AYNI TEMELDE DEGIL: 480p/720p/1080p satirlari HAM
    # kaynakla (test.y4m) olculdu, 4K satiri H.264 ile sikistirilmis bir
    # kaynakla. Sikistirilmis referansa karsi VMAF egrisi yatiklasir ve 96'ya
    # zor ulasir. Duzeltmek icin HAM (y4m/kayipsiz) bir 4K kaynak gerekir.
    # 1440p icin hicbir olcum YOK; 4K satiri kullaniliyor - kaliteden yana
    # hata yapmak icin (turetilmis yuksek QP degerleri kanitla celisti).
    "av1_amf": {
        "4K": (70, 104), "1440p": (70, 104), "1080p": (144, 160),
        "720p": (135, 153), "480p": (125, 146), "360p": (120, 141),
        "240p": (115, 136),
        "default": (144, 160)
    },
}

# Varsayilan artik AYRI BIR TABLODA TUTULMUYOR: onerilen araligin UST SINIRI
# dogrudan CQ_RANGES'ten okunur (bkz. get_cq_default).
#
# Neden ust sinir: bu bandin ust ucu OLCULEN VMAF ~90 noktasidir, yani
# "gorunur kayip baslamadan onceki en kucuk dosya". Once alt uc (VMAF ~96)
# kullaniliyordu; arsiv icin dogruydu ama dosyalar gereksiz buyuyordu.
# Bandin disina cikilmiyor: alt uc de ust uc de olculmus degerler.
#
# Neden ayri tablo yok: iki tablonun ayrisması bu projede zaten bir kez kusur
# uretti (av1_nvenc'te "1080p" anahtari eksikti, "default" devreye girip
# araligin tepesine dusuyordu). Tek kaynaktan turetince o sinif hata imkansiz.

SCALE_MAP = {
    "240p": 426, "360p": 640, "480p": 854, "720p": 1280,
    "1080p": 1920, "1440p": 2560, "4K": 3840
}

# =======================================================
# KODLAYICI LEVEL (BITRATE TAVANI) AYARI
# =======================================================
# NVENC'in "auto" level secimi, dusuk CQ'da SERT bir bitrate tavani yaratiyor.
# Olculdu (park_joy.y4m, 10 sn 1080p50, p7, ffmpeg 9.0) - bitrate kbps:
#
#   kodek | auto (eski)              | asagidaki deger
#   hevc  | 16149 / 16149 / 16149    | 119565 / 63370 / 39165   (CQ 12 / 18 / 22)
#   h264  | 41237 / 41233 / 35333    | 120447 /  57279 / 34945
#
# "auto" ile CQ12, CQ16 ve CQ18 BAYT BAYT ayni dosyayi uretiyordu: kalite
# kaydiricisi arsiv ucunda hicbir sey yapmiyordu. VMAF 87.3 -> 96.4 (5.1) ->
# daha yukari (6.2).
#
# DIKKAT - LEVEL CQ'DAN BAGIMSIZ OLARAK BITSTREAM'E YAZILIR. Yani CQ31'lik
# siradan bir cikti da artik Level 6.2 damgali. Katı donanim cozuculer (bazi
# TV/set-ustu kutular) yuksek level'i, dosya kucuk olsa bile reddedebilir.
# Uyumluluk sorunu yasarsan dusurulecek yer burasi - tek satir.
#
# AV1 BILEREK DISARIDA: olculdu, AV1'de "auto" ile tavan YOK (CQ31->CQ12 arasi
# 19933 -> 117709 kbps temiz olcekleniyor). AV1'e level EKLEMEK zarar verir;
# level 5.1 denendiginde 40194 kbps'te tavan olusuyordu.
HEVC_LEVEL = "6.2"    # 4.1 (auto) -> tavan pratikte kalkar
H264_LEVEL = "5.1"    # 4.2 (auto) -> tavan kalkar; 6.2 ile ayni sonucu verdi

# AMD'de (AMF) level tavani YOK: olculdu, "-level 153" ve "-level 186" ile
# ciktilar BAYT BAYT ayni (qp=12'de 12304841 bayt). AMF level'i yalnizca
# bitstream'e yaziyor, bitrate'i kisitlamiyor. Bu yuzden AMF dallarina
# -level EKLENMEZ; AV1/NVENC'te oldugu gibi dokunmamak dogrusu.

# =======================================================
# DONANIM (VENDOR) TANIMLARI
# =======================================================
# Uygulama tek bir marka icin degil, MAKINEDE NE VARSA onun icin calisir.
# Kartlar degisir: bu proje bir gun icinde RTX 5060 Ti'dan RX 9070 XT'ye
# gecti ve NVENC sekmelerinin hepsi "Cannot load nvcuda.dll" ile coktu.
# O yuzden marka acilista OLCULUR (bkz. encoder_calisiyor_mu), varsayilmaz.

NVIDIA, AMD = "nvidia", "amd"

# AMD (AMF) sekmelerinin TEK kaynagi. Sekmeler bundan uretilir, markaya gore
# gizleme listesi de, hata mesajlarinin "su sekmeyi kullanin" onerisi de.
# Ayri ayri yazilsalardi bir yeniden adlandirma otekini sessizce eskitirdi.
AMF_SEKME_ADI = {
    "av1_amf": "AV1 (AMD)",
    "hevc_amf": "H.265 (AMD)",
    "h264_amf": "H.264 (AMD)",
}

# TAM GPU (kopyasiz AMF hatti) kendi sekmesinde durur; kodlayici o sekmenin
# icinden secilir. Neden ayri sekme oldugu icin bkz. COZUCU_SECENEKLERI notu.
TAMGPU_SEKME = "⚡ TAM GPU (AMD)"

DONANIM = {
    NVIDIA: {
        "ad": "NVIDIA",
        # Markanin varligini olcmek icin denenecek kodlayici. Biri calisiyorsa
        # o markanin surucusu yuklu demektir.
        "deneme": "hevc_nvenc",
        "sekmeler": ("AV1 (Standart)", "H.265 (Standart)", "H.264 (Standart)",
                     "⚡ SAF CUDA"),
    },
    AMD: {
        "ad": "AMD",
        "deneme": "hevc_amf",
        "sekmeler": tuple(AMF_SEKME_ADI.values()) + (TAMGPU_SEKME,),
    },
}

# --- SES ---
# Varsayilan SES AYARI "kopyala". Olculdu (kullanicinin 83 dakikalik 1.mp4
# dosyasi): kaynagin sesi 32 kbps AAC (19 MB) iken uygulama onu 128 kbps
# Opus'a yeniden kodluyordu (72 MB) ve TEK BASINA bu, ciktinin kaynaktan
# buyuk cikmasina yol aciyordu - video tarafi 77.5 -> 70.2 MB ile kuculmustu.
# Kopyalama hem kayipsiz hem kucuk; mumkun olmadigi durumu uygulama zaten
# OLCUYOR (bkz. can_copy_audio) ve kendiliginden yeniden kodlamaya duser.
SES_KOPYALA = "Kopyala (yeniden kodlama yok)"

# Arayuzde sunulan bitrate adimlari (kbps). Sinirlama bu merdiveni kullanir.
SES_BITRATE_ADIMLARI = (64, 96, 128, 192, 256, 320)

# Acilista secili gelmesi istenen sekme. Yoksa (donanimi olmadigi icin
# silindiyse) kalan ilk sekmeye dusulur - bkz. donanimi_uygula.
VARSAYILAN_SEKME = "⚡ SAF CUDA"

# Markadan bagimsiz sekmeler: donanim olmasa da calisirlar, HIC gizlenmezler.
# (VP9 tamamen CPU'da kodlar; sadece-altyazi hic kodlama yapmaz.)
DONANIMSIZ_SEKMELER = ("VP9 (Google VOD)", "💬 SADECE ALTYAZI")

# Algilama denemesinin kare boyutu. 256x256 KULLANILAMAZ: olculdu, hevc_amf ve
# av1_amf o boyutta "encoder->Init() failed with error 5" veriyor ve calisan
# bir kart "yok" gorunuyordu. 640x360 uc markada da sorunsuz.
DENEME_BOYUTU = "640x360"

# AMF kalite onayarlari (-quality). NVENC'in p1..p7'sinin karsiligi.
AMF_QUALITY_VALUES = ["quality", "balanced", "speed", "high_quality"]
AMF_CODECS = tuple(AMF_SEKME_ADI)

# AMF'de B-kare QP'sini AYRI alan kodlayicilar. hevc_amf'te boyle bir secenek
# YOK; olmayanina vermek "not used for any stream" uyarisi uretir.
AMF_QP_B_KODEKLERI = ("av1_amf", "h264_amf")

# QP olcegi kodege gore DEGISIR ve bu sessizce yanlis calisan bir arayuz uretir:
# av1_amf 0-255, digerleri 0-51. Kaydiriciyi hepsinde 0-51 tutunca AV1'de en
# yuksek deger bile kayipsiza yakin kaliyordu; olculdu, qp16 ile qp51 arasinda
# VMAF 99.99 -> 99.98 (373 Mbps -> 157 Mbps), yani kadran hicbir sey yapmiyordu.
AMF_QP_TAVANI = {"av1_amf": 255}
AMF_QP_TAVANI_VARSAYILAN = 51

# VCN'in kabul ettigi en kucuk kare. Altina inilirse ffmpeg yalnizca
# "encoder->Init() failed with error 5" der; sebebini anlamak imkansiz.
#
# SINIR KODEGE GORE COK FARKLI. OLCULDU (RX 9070 XT, ffmpeg 9.0.1): her kodek
# 2 piksellik adimlarla tarandi, sinir KESKIN cikti (hizalama kurali degil,
# duz bir alt sinir) ve iki boyut birbirinden bagimsiz:
#     h264_amf :  96 x  32   (94 ve 30'da coker)
#     av1_amf  : 320 x 128   (318 ve 126'da coker)
#     hevc_amf : 384 x 128   (382 ve 126'da coker)
#
# ONCEDEN UCUNE DE EN KOTU DURUM (384x128) UYGULANIYORDU ve bu, h264/av1'in
# sorunsuz kodladigi dosyalari da engelliyordu: 320x240 bir kaynakta uc AMD
# sekmesi de "cok kucuk" diyordu, oysa yalnizca H.265 gercekten cokuyor
# (uygulamanin kendi komutuyla ucu de kosularak dogrulandi).
#
# Uygulamanin en kucuk olcekleme secenegi 240p uzun kenari 426 yapar, yani
# YATAY videoda olcekleme secenekleri guvenli. Sinir iki durumda isirir:
# kucuk kaynak + "Orijinal", ve DIKEY video (uzun kenar yukseklige gidince
# genislik 240p'de 240, 360p'de 360 kalir; hevc 384 ister).
AMF_MIN_KARE = {
    "h264_amf": (96, 32),
    "av1_amf": (320, 128),
    "hevc_amf": (384, 128),
}


def amf_kabul_eden_sekmeler(w, h):
    """
    Verilen kareyi kodlayabilen AMD sekmelerinin adlari. SAF FONKSIYON.

    "Cok kucuk" uyarisi bunu kullanir: kullaniciyi VP9'a (CPU, kat kat yavas)
    ya da cozunurluk degistirmeye yollamadan once, kareyi OLDUGU GIBI kabul
    eden bir donanim sekmesi var mi diye bakariz. Sira AMF_SEKME_ADI'ndan
    gelir; once kalite/verim acisindan tercih edilen kodek onerilir.
    """
    return [ad for kod, ad in AMF_SEKME_ADI.items()
            if w >= AMF_MIN_KARE[kod][0] and h >= AMF_MIN_KARE[kod][1]]


# Bazi kaynak kodeklerinde DONANIM cozucusu zarar veriyor; bu sezgiye ters
# oldugu icin olculerek bulundu (RX 9070 XT, 1080p, 3'er kosu, cikti bayt
# bayt ayni):
#     AV1  kaynak: d3d11va 2090 ms | yazilim 1431 ms   -> yazilim %46 hizli
#     H264 kaynak: d3d11va  950 ms | yazilim 1042 ms   -> donanim %10 hizli
# Sebep mimari: AMD'de GPU filtre zinciri kurulamadigi icin kareler zaten
# sistem bellegine donmek zorunda. Donanim cozucu fazladan bir VRAM->RAM
# kopyasi ekliyor; kolay cozulen akislarda (dav1d cok hizli) bu kopya baskin
# geliyor, zor akislarda donanim kazaniyor.
#
# DIKKAT: yalnizca AV1 olculdu ve tek dosyayla. Cok yuksek bitrate'li bir
# AV1'de donanim one gecebilir - listeyi genisletmeden once OLC.
D3D11VA_ISTEMEYEN_KODEKLER = frozenset({"av1"})

# Kullanicinin donanim cozucu tercihi. "Otomatik" yukaridaki olcume uyar;
# digerleri kullanicinin bilinçli secimidir (dusuk CPU mu, kisa sure mi).
#
# TAM GPU BURADA YOK, ARTIK KENDI SEKMESI VAR (bkz. TAMGPU_SEKME). Sebep:
# o hatta altyazi gomme, renk filtresi ve taraklanma giderme CALISAMIYOR ve
# secenek burada dururken bu ozellikler SESSIZCE atlaniyordu - kullanici
# altyazi ekleyip 83 dakika bekledikten sonra altyazisiz dosya buluyordu.
# Ayri sekmede yalnizca o hatta gercekten calisan secenekler gosteriliyor.
COZUCU_SECENEKLERI = {
    "Otomatik (ölçüme göre)": "oto",
    "Donanım - GPU (d3d11va)": "donanim",
    "Yazılım - CPU (dav1d vb.)": "yazilim",
}

# TAM GPU HATTI (AMF -> AMF, kopyasiz)
# ------------------------------------
# "-hwaccel amf -hwaccel_output_format amf": kare cozuldukten sonra AMF
# yuzeyi olarak kalir ve dogrudan AMF kodlayicisina gider; GPU<->sistem
# bellegi kopyasi olmaz.
#
# ONEMLI - ONCEDEN "KURULAMIYOR" DEDIM, YANLISTI. Denedigim kombinasyon
# "-hwaccel d3d11va -hwaccel_output_format amf" idi ve d3d11va cozucusu amf
# yuzeyi uretemedigi icin cokuyordu. Dogrusu cozucunun de amf olmasi.
#
# OLCULDU (RX 9070 XT): HIZ KAZANCI YOK.
#   4K olceklemesiz : mevcut 10.4 sn | tam GPU 10.6 sn
#   1080p'ye olcek  : mevcut  4.0 sn | tam GPU  4.1 sn
#   AV1 kaynak      : mevcut  2.7 sn | tam GPU  3.2 sn (mevcut daha hizli)
# Yine de secenek olarak duruyor: kullanicinin amaci hiz degil, isin tamamen
# GPU'da kalmasi (CPU'yu bosta birakmak).
#
# vpp_amf'in VARSAYILANI bilinear ve kalite kaybettiriyor; olculdu, 4K->1080p
# kucultmede VMAF bilinear 85.4 iken bicubic 88.6 (lanczos 87.7). Bu yuzden
# bicubic SABITLENIYOR.
AMF_TAMGPU_SCALE = "bicubic"

# AV1 kaynaklarda AMF hattı ek donanim karesi istiyor (ffmpeg AMF wiki).
AMF_EXTRA_HW_FRAMES = "10"

# Tam GPU hattinda kare AMF yuzeyinde kalir; bu filtrelerin AMF karsiligi yok
# ve zinciri kirar. Istenirse kullaniciya soylenip ATLANIR.
AMF_TAMGPU_DESTEKLENMEYEN = ("renk filtresi", "taraklanma giderme", "altyazı gömme")

# sr_amf = AMD'nin donanimsal HQ buyutmesi (ffmpeg -h filter=sr_amf).
#
# "SR 1.1" (algorithm=4) BILEREK YOK: bu surucude SIMSIYAH kare uretiyor.
# OLCULDU (RX 9070 XT, ffmpeg 9.0.1) - komut basariyla bitiyor, cikti dogru
# cozunurlukte ve dogru kare sayisinda, ama goruntu bos:
#     kaynak                YAVG 125.6
#     sr_amf algorithm=4    YAVG   0.0   <-- siyah (PSNR 9.6 dB)
#     sr_amf algorithm=2    YAVG 125.6   dogru
#     sr_amf algorithm=1/0  YAVG 125.6   dogru
# Bu yuzden "kostu mu" kontrolu YETMIYOR; goruntunun kendisi olculmeli.
AMF_SR_ALGORITMALARI = {
    "SR 1.0 (AMD, önerilen)": "2",
    "Bicubic": "1",
    "Bilinear": "0",
}
AMF_SR_VARSAYILAN_ALGO = "2"

# HANGI AMF FILTRELERI BIR ARADA CALISIR - OLCULDU (RX 9070 XT, ffmpeg 9.0.1;
# her birlesim hevc_amf ve av1_amf ile 3'er kez kosuldu):
#     vpp_amf olcekleme                      -> 6/6 basarili
#     vpp_amf olcekleme + format=p010        -> 6/6   (10-bit AYNI filtrede)
#     vpp_amf(olcek+10bit) + frc_amf         -> 6/6   (zincirde IKI AMF filtresi)
#     sr_amf tek basina                      -> 6/6
#     sr_amf + frc_amf                       -> 5/6   COKTU
#     sr_amf + vpp_amf(format=p010)          -> 5/6   COKTU
#     sr_amf + vpp_amf + frc_amf             -> KILITLENDI (1 sn'lik klip, 180 sn)
# Sonuc: sr_amf BASKA BIR AMF FILTRESIYLE BIRLESTIRILMEZ. HQ buyutme secilince
# 10-bit ve kare katlama uygulanmaz; arayuz de o iki salteri kapatir.
# ("-pix_fmt p010le" ile 10-bit istemek de bu hatta cokuyor: "Error
# reinitializing filters!" - 10-bit YALNIZCA vpp_amf=format ile alinir.)
AMF_SR_YALNIZ_CALISIR = True


def amf_qp_tavani(codec):
    """Bu kodlayicinin QP kaydiricisinin ust siniri."""
    return AMF_QP_TAVANI.get(codec, AMF_QP_TAVANI_VARSAYILAN)

# Dosya secimi ve surukle-birak ayni listeyi kullanir (birbirinden sapmasin diye)
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.ts', '.vob', '.y4m',
              '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg')
SUB_EXTS = ('.srt', '.ass', '.vtt')

# Terminal kutusunda gorunecek satir sayisi. Kucuk tutuluyor cunku ayar
# kartlari zaten cok yer kapliyor; log otomatik kaydigi icin en son satirlar
# her zaman gorunur kalir.
LOG_SATIR_SAYISI = 3

# Altyazi dugmesinin bos haldeki metni (secilince dosya adiyla degisir)
SUB_BTN_BOS = "💬 Altyazı Ekle"

# =======================================================
# SADECE ALTYAZI (REMUX) MODU SABITLERI
# =======================================================
# Bu moddaki tablolar ffmpeg 9.0 ile OLCULEREK dolduruldu, ezberden degil:
#   * Matroska metin altyazilarin UTF-8 olmasini SART kosar. CP1254 bir .srt
#     "-c:s copy" ile kopyalanirsa baytlar oldugu gibi gecer ve oynaticida
#     bozuk karakter cikar; "-c:s srt" ile charenc VERILMEDEN cevrilmeye
#     kalkilirsa ffmpeg "Invalid UTF-8 in decoded subtitles text" diyip isi
#     69 cikis koduyla birakir. Yani kodlama olcumu opsiyonel bir susleme
#     degil, isin calismasiyla cokmesi arasindaki fark.
#   * mov_text (MP4 kaynaklardan gelir) matroska'ya KOPYALANAMAZ:
#     "Could not write header (incorrect codec parameters ?)". srt'ye cevrilir.
#   * MP4 metin altyazi olarak YALNIZCA mov_text kabul eder; srt'yi "copy" ile
#     denemek "codec not currently supported in container" ile 127 verir.
#   * Resim tabanli altyazilar (PGS/VobSub) metne cevrilemez: MP4 ciktida
#     tasinamazlar, atlanmalari gerekir. MKV bunlari sorunsuz kopyalar.

# ffprobe'un dondurdugu resim tabanli altyazi codec adlari.
BITMAP_SUB_CODECS = frozenset({
    "hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub",
    "dvb_subtitle", "dvbsub", "dvb_teletext", "xsub",
})

# Stil tasiyan altyazi uzantilari: cevirmek gerekirse srt yerine ass'e yazilir
# ki renk/konum/italik bilgisi kaybolmasin.
STYLED_SUB_EXTS = ('.ass', '.ssa')

# Harici altyazinin karakter kodlamasi. "" = olc ve kendin karar ver
# (bkz. detect_sub_charenc). Digerleri kullanicinin elle zorlamasi icindir:
# olcum yalnizca "UTF-8 mi, degil mi" sorusunu kesin cevaplayabilir; UTF-8
# degilse hangi 8-bitlik kod sayfasi oldugunu bayta bakarak ayirt etmek
# mumkun degil (her kod sayfasi her bayt dizisini "basariyla" cozer).
SUB_CHARENC_SECENEKLERI = {
    "Otomatik (ölçerek karar ver)": "",
    "UTF-8": "UTF-8",
    "Windows-1254 (Türkçe)": "CP1254",
    "ISO-8859-9 (Türkçe)": "ISO-8859-9",
    "Windows-1252 (Batı Avrupa)": "CP1252",
    "Windows-1250 (Orta Avrupa)": "CP1250",
    "Windows-1251 (Kiril)": "CP1251",
}

# UTF-8 olmayan bir altyazida otomatik modun varsayacagi kod sayfasi.
# Turkce altyazilarda fiilen standart olan budur; yanlissa arayuzden zorlanir.
SUB_CHARENC_VARSAYILAN = "CP1254"

# Altyazi izine yazilacak dil etiketi (ISO 639-2). Oynaticilar izi bu etiketle
# adlandirir; bos birakilirsa "Undetermined" olarak gorunur.
SUB_DIL_SECENEKLERI = {
    "Belirtilmedi": "",
    "Türkçe (tur)": "tur",
    "İngilizce (eng)": "eng",
    "Almanca (ger)": "ger",
    "Fransızca (fre)": "fre",
    "İspanyolca (spa)": "spa",
    "İtalyanca (ita)": "ita",
    "Rusça (rus)": "rus",
    "Arapça (ara)": "ara",
    "Japonca (jpn)": "jpn",
    "Korece (kor)": "kor",
}


def ses_bitrate_sinirla(secilen, kaynak_kbps):
    """
    Yeniden kodlamada kullanilacak ses bitrate'ini dondurur: (deger, not).
    SAF FONKSIYON.

    Kayipli sesin kaybettigi kaliteyi geri getirmek MUMKUN DEGIL: 32 kbps'lik
    bir kaynagi 128 kbps'e kodlamak yalnizca dosyayi buyutur. Kural: hedef,
    kaynagin USTUNDEKI ilk adimi asamaz. Boylece kayipli -> kayipli gecis
    icin bir kademe pay kalir (32 -> 64k), israf ise engellenir.

    Kaynagin bitrate'i okunamadiysa (None; bazi MKV'lerde akis basina deger
    yazmaz) DOKUNULMAZ - tahmin edip kaliteyi dusurmektense secimi birakiriz.
    """
    if not kaynak_kbps or not secilen:
        return secilen, None
    try:
        secilen_kbps = int(str(secilen).rstrip("kK"))
    except ValueError:
        return secilen, None
    tavan = next((adim for adim in SES_BITRATE_ADIMLARI if adim >= kaynak_kbps),
                 SES_BITRATE_ADIMLARI[-1])
    if secilen_kbps <= tavan:
        return secilen, None
    return (f"{tavan}k",
            f"🎵 Kaynağın sesi {kaynak_kbps} kbps; {secilen} yerine {tavan}k "
            "kullanılıyor. Daha yükseği kaybolmuş kaliteyi geri getirmez, "
            "sadece dosyayı büyütür.")


def cozunurluk_bandi(w, h):
    """
    Bir kareye EN YAKIN CQ tablosu satirini secer ("4K", "1080p", ...).
    Boyut bilinmiyorsa None. SAF FONKSIYON.

    Neden gerekli: kullanici "Orijinal" secince tabloda o adda satir YOK ve
    eskiden dogrudan "default" satira dusuluyordu. "default" 1080p turevidir,
    yani cozunurluk ne olursa olsun 1080p tavsiyesi veriliyordu. 4K bir
    kaynakta bu sessizce yanlis: av1_amf'te OLCULEN 4K bandi 70-104 iken sekme
    144'te aciliyordu ve 144, gercek 4K icerikte VMAF 90'in ALTINA denk
    geliyor (bkz. CQ_RANGES av1_amf notu).

    Satir uzun kenara gore ve EN YAKIN olan secilir (buyuk-esit degil): 3500
    piksellik bir kaynak 1440p'den cok 4K'ya benzer. 3840'in ustu (8K vb.)
    icin olcum YOK; en yakin satir olarak 4K kullanilir.
    """
    uzun = max(w or 0, h or 0)
    if uzun <= 0:
        return None
    return min(SCALE_MAP, key=lambda ad: abs(SCALE_MAP[ad] - uzun))


def get_cq_range(codec, scale, kaynak_boyut=None):
    """
    Onerilen CQ/QP araligi. "Orijinal" secildiyse ve kaynagin boyutu
    biliniyorsa band KAYNAGIN cozunurlugunden turer (bkz. cozunurluk_bandi).
    kaynak_boyut verilmezse eski davranis: "default" satiri.
    """
    codec_ranges = CQ_RANGES.get(codec, CQ_RANGES["hevc_nvenc"])
    if scale == "Orijinal" and kaynak_boyut:
        scale = cozunurluk_bandi(*kaynak_boyut) or scale
    return codec_ranges.get(scale, codec_ranges["default"])


def komut_metni(cmd):
    """
    Komutu KOPYALANIP CALISTIRILABILIR bicimde metne cevirir.

    Uygulama komutu kabuktan gecirmez (subprocess'e liste verilir), o yuzden
    calisma acisindan tirnaga gerek yok. Ama loga duz " ".join() ile yazinca
    bosluklu yollar bozuluyor ve kullanici komutu terminale yapistirinca
    calismiyordu - hata ararken en cok isine yarayacak sey tam da bu.
    """
    parcalar = []
    for p in cmd:
        parcalar.append(f'"{p}"' if (" " in p or "\t" in p) else p)
    return " ".join(parcalar)


def get_cq_default(codec, scale, kaynak_boyut=None):
    """
    Sekme acildiginda kullanilacak CQ/QP: onerilen araligin UST SINIRI, yani
    "camurlasma riski" esiginin hemen altindaki en tutumlu deger.

    KULLANICI TERCIHI (2026-08-16): eskiden bandin ALT ucu (en yuksek kalite)
    kullaniliyordu. Amac arsiv kalitesiydi ama pratikte dosyalar gereksiz
    buyuyordu - olculdu, 32 kbps'lik gercek bir kaynakta bile cikti kaynaktan
    buyuk cikabiliyor. Ust sinir hala OLCULEN bandin icinde: VMAF ~90, yani
    "gorunur kayip baslamadan onceki en kucuk dosya".

    Bandin kendisi kaynagin cozunurlugune gore secilir (bkz. get_cq_range),
    yani bu deger de kaynaga gore degisir.
    """
    return get_cq_range(codec, scale, kaynak_boyut)[1]


def parse_time(metin):
    """
    'ss', 'dd:ss' veya 'ss:dd:ss(.ms)' girdisini saniyeye cevirir.
    Bos/gecersiz girdi None dondurur (kirpma uygulanmaz).
    """
    metin = (metin or "").strip()
    if not metin:
        return None
    try:
        parcalar = [float(p) for p in metin.split(":")]
    except ValueError:
        return None
    if not 1 <= len(parcalar) <= 3 or any(p < 0 for p in parcalar):
        return None
    saniye = 0.0
    for p in parcalar:
        saniye = saniye * 60 + p
    return saniye


def trim_args(cfg):
    """
    Kirpma bayraklarini uretir. -ss GIRDIDEN ONCE gelir (hizli arama) ve
    -to bu durumda girdinin basina gore degil, -ss sonrasina goredir; bu
    yuzden sure farki -t olarak verilir.
    """
    bas = parse_time(cfg.get("trim_start"))
    son = parse_time(cfg.get("trim_end"))
    args = []
    if bas:
        args += ["-ss", f"{bas:.3f}"]
    if son and (not bas or son > bas):
        args += ["-t", f"{son - (bas or 0):.3f}"]
    return args


def color_filter_of(cfg):
    """Secili renk profiline karsilik gelen eq filtresi (yoksa bos dize)."""
    if cfg["color_preset"] == "Karanlık Video Kurtarma":
        return "eq=brightness=0.05:contrast=1.15:saturation=1.1:gamma=1.5"
    if cfg["color_preset"] == "Özel Ayarlar":
        b, c, s, g = cfg["brightness"], cfg["contrast"], cfg["saturation"], cfg["gamma"]
        if b != 0.0 or c != 1.0 or s != 1.0 or g != 1.0:
            return f"eq=brightness={b:.2f}:contrast={c:.2f}:saturation={s:.2f}:gamma={g:.2f}"
    return ""


def cuda_color_roundtrip_ok(pix_fmt):
    """
    CUDA karesini renk filtresi icin RAM'e indirip geri yuklemek mumkun mu?

    8 ve 10 bitte evet (nv12 / p010le). 12 bit ve ustunde ffmpeg 9.0 ile
    HICBIR indirme formati kabul edilmiyor ("Invalid output format ... for
    hwframe download"); bu durumda filtreleri CPU'da calistirmak gerekir.
    """
    return cuda_download_format(pix_fmt) != "p016le"


def tamgpu_hedef_boyut(cfg):
    """
    TAM GPU hattinda olceklemenin hedef karesi (w, h); olcekleme yoksa None.
    SAF FONKSIYON.

    AMF filtreleri (vpp_amf/sr_amf) ifade KABUL ETMIYOR - "-2" ya da
    "if(gt(a,1),..)" yazilamaz - bu yuzden iki boyut da burada acikca
    hesaplanir. Kaynak orani bilinmiyorsa 16:9 varsayilir.
    """
    if cfg.get("scale") == "Orijinal":
        return None
    uzun = SCALE_MAP.get(cfg.get("scale"))
    if uzun is None:
        return None
    kw, kh = cfg.get("cikti_boyutu") or (0, 0)
    if kw and kh:
        return (uzun, max(2, round(uzun * kh / kw))) if kw >= kh else \
               (max(2, round(uzun * kw / kh)), uzun)
    return (uzun, round(uzun * 9 / 16))


def build_filters(cfg, probes):
    """
    Video filtre zincirini kurar. SAF FONKSIYON.
    Hem gercek kodlama hem de onizleme karesi ayni zinciri kullanir; boylece
    onizlemede gordugun goruntu ciktida elde edecegin goruntudur.
    """
    # Sadece-altyazi modunda kare HIC dokunulmadan kopyalanir: tek bir filtre
    # bile calismaz. Bu erken cikis olmadan onizleme, ciktida OLMAYAN bir renk
    # duzeltmesini gosterip "onizleme = cikti" sozunu bozuyordu.
    if cfg.get("is_remux"):
        return [], []

    notes = []
    cuda_frames = probes.get("cuda_frames", False)
    vf_filters = []

    # ---------- TAM GPU (AMF) HATTI ----------
    # Kare AMF yuzeyinde kalir. Yalnizca vpp_amf calisabilir; renk/taraklanma/
    # altyazi filtrelerinin AMF karsiligi yok ve zinciri kirarlar.
    if cfg.get("tam_gpu"):
        hedef = tamgpu_hedef_boyut(cfg)
        if cfg["scale"] != "Orijinal" and hedef is None:
            notes.append(f"⚠️ Bilinmeyen çözünürlük: {cfg['scale']}, Orijinal kullanılıyor.")

        # HQ buyutme (sr_amf) YALNIZ calisir: baska bir AMF filtresiyle
        # birlesince coküyor, ucu bir arada ise kilitleniyor (bkz.
        # AMF_SR_YALNIZ_CALISIR olcumu). Arayuz de bu iki salteri kapatir;
        # buradaki kontrol kuyruga eski ayarlarla giren isler icin.
        hq = bool(cfg.get("amf_sr")) and hedef is not None
        if hq:
            sr = f"sr_amf=w={hedef[0]}:h={hedef[1]}:algorithm={cfg.get('amf_sr_algo', AMF_SR_VARSAYILAN_ALGO)}"
            keskinlik = cfg.get("amf_sr_sharpness")
            if keskinlik not in (None, "", -1):
                sr += f":sharpness={keskinlik}"
            vf_filters.append(sr)
            engellenen = [ad for ad, acik in (("10-bit", cfg.get("ten_bit")),
                                              ("kare hızı katlama", cfg.get("amf_frc")))
                          if acik]
            if engellenen:
                notes.append("⚠️ HQ büyütme açıkken " + " ve ".join(engellenen) +
                             " ATLANDI: ölçüldü, AMD'nin HQ büyütmesi başka bir "
                             "AMF filtresiyle birlikte çöküyor ya da kilitleniyor.")
        else:
            # 10-bit AYNI vpp_amf filtresinde istenir; ayri filtre eklemek
            # zinciri uzatir ve kararsizlastirir (olculdu).
            vpp = []
            if hedef:
                vpp.append(f"w={hedef[0]}:h={hedef[1]}:scale_type={AMF_TAMGPU_SCALE}")
            if cfg.get("ten_bit"):
                vpp.append("format=p010")
            if vpp:
                vf_filters.append("vpp_amf=" + ":".join(vpp))
            if cfg.get("amf_frc"):
                vf_filters.append("frc_amf")
                notes.append("🎞️ Kare hızı hareket interpolasyonuyla İKİ KATINA "
                             "çıkarılıyor (frc_amf). Dosya büyür ve görüntü "
                             "'video' karakterine kayar.")

        # Renk etiketi bu hatta da yazilabiliyor (setparams metadata filtresi;
        # kareye dokunmadigi icin AMF yuzeyini bozmuyor - olculdu). 10-bit
        # cikti + etiketsiz kaynak birlesimi olmadan sahte HDR uretiyordu.
        if probes.get("renk_etiketsiz"):
            vf_filters.append("setparams=color_primaries=bt709:color_trc=bt709"
                              ":colorspace=bt709:range=tv")
            notes.append("🎨 Kaynakta renk etiketi yok; çıktı BT.709 olarak "
                         "işaretlendi.")

        atlanan = []
        if color_filter_of(cfg):
            atlanan.append("renk filtresi")
        if cfg["use_bwdif"]:
            atlanan.append("taraklanma giderme")
        if cfg["sub_file"]:
            atlanan.append("altyazı gömme")
        if atlanan:
            notes.append("⚠️ TAM GPU hattında " + ", ".join(atlanan) +
                         " ATLANDI: bunların AMF karşılığı yok ve kopyasız "
                         "zinciri kırarlar. Gerekiyorsa kod çözücüyü "
                         "'Otomatik' yapın.")
        return vf_filters, notes

    if cfg["use_bwdif"]:
        vf_filters.append("yadif_cuda" if cuda_frames else "bwdif")

    if cfg["scale"] != "Orijinal":
        w = SCALE_MAP.get(cfg["scale"])
        if w is None:
            notes.append(f"⚠️ Bilinmeyen çözünürlük: {cfg['scale']}, Orijinal kullanılıyor.")
        elif cuda_frames:
            sc = f"scale_cuda=w='if(gt(a,1),{w},-2)':h='if(gt(a,1),-2,{w})'"
            if cfg["interp_algo"] != "Otomatik":
                sc += f":interp_algo={cfg['interp_algo']}"
            vf_filters.append(sc)
        else:
            vf_filters.append(f"scale='if(gt(a,1),{w},-2)':'if(gt(a,1),-2,{w})':flags=lanczos")

    # 8-bit istendiginde CUDA karelerini GPU'da nv12'ye dusurmek gerekir:
    # -profile:v main tek basina yok sayilir, cikti yine Main 10 olur.
    if cuda_frames and not cfg["ten_bit"] and not cfg["is_vp9"]:
        vf_filters.append("scale_cuda=format=nv12")

    color_filter = color_filter_of(cfg)

    if color_filter:
        if cuda_frames:
            # Indirme formati kaynagin bit derinligine gore secilmeli:
            # sabit "nv12" 10/12-bit kaynaklarda ffmpeg'i durduruyordu.
            dl_fmt = cuda_download_format(probes.get("pix_fmt", ""))
            notes.append("⚠️ UYARI: Saf CUDA sekmesinde CPU tabanlı renk filtresi aktif. "
                         f"Veri VRAM->RAM->VRAM kopyalanacak (format: {dl_fmt}). Bu işlem hızı düşürebilir.")
            vf_filters.extend(["hwdownload", f"format={dl_fmt}", color_filter, "hwupload_cuda"])
        else:
            vf_filters.append(color_filter)

    if not cfg["is_pure_cuda"] and cfg["sub_file"]:
        vf_filters.append(f"subtitles={escape_filter_path(cfg['sub_file'])}")

    # ---------- RENK ETIKETI ----------
    # Kaynakta renk metadata'si yoksa cikti YANLIS etiketleniyor ve goruntu
    # bozuk gorunuyor. OLCULDU: etiketsiz 8-bit bir kaynak 10-bit'e cevrilince
    # cikti "color_primaries=bt2020, color_transfer=smpte2084" yani HDR/PQ
    # damgasi aliyor. Oynatici SDR icerige BT.2020 donusumu uygulayinca
    # goruntu asiri doygun ve KIRMIZIYA calan hale geliyor.
    # (8-bit ciktida bu olmuyor; sorun 10-bit + etiketsiz kaynak birlesimi.)
    #
    # Cozum: etiket yoksa BT.709 damgala. SD/HD SDR icerigin tamami BT.709'dur;
    # gercekten HDR olan kaynaklar ZATEN etiketlidir ve onlara dokunulmaz.
    # "-color_* cikis secenekleri" denendi, tam oturmadi (transfer/primaries
    # "unknown" kaliyordu); setparams filtresi ucunu de dogru yaziyor.
    if probes.get("renk_etiketsiz"):
        vf_filters.append("setparams=color_primaries=bt709:color_trc=bt709"
                          ":colorspace=bt709:range=tv")
        notes.append("🎨 Kaynakta renk etiketi yok; çıktı BT.709 olarak "
                     "işaretlendi (etiketsiz bırakılırsa oynatıcılar HDR "
                     "sanıp renkleri bozuyor).")

    return vf_filters, notes


def build_preview_command(cfg, probes, cikti_png, zaman=None):
    """
    Tek karelik onizleme komutu. Kodlama komutuyla AYNI filtre zincirini
    kullanir (build_filters), boylece onizleme ciktiyi temsil eder.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if cfg.get("hwaccel"):
        cmd.extend(["-hwaccel", cfg["hwaccel"]])
    if probes.get("cuda_frames"):
        cmd.extend(["-hwaccel_output_format", "cuda"])
    bas = parse_time(cfg.get("trim_start")) or 0.0
    cmd.extend(["-ss", f"{(zaman if zaman is not None else bas):.3f}", "-i", cfg["input_file"]])

    vf, _ = build_filters(cfg, probes)
    if probes.get("cuda_frames"):
        # PNG kodlayicisi sistem bellegi ister.
        if vf and vf[-1] == "hwupload_cuda":
            # Renk filtresi zinciri kareyi zaten RAM'e indirmisti; sirf VRAM'e
            # geri yukleyip tekrar indirmek gereksiz ve hatali (yukleme sonrasi
            # kare formati degistigi icin ikinci hwdownload cakiliyor).
            vf = vf[:-1]
        else:
            vf = vf + ["hwdownload", f"format={cuda_download_format(probes.get('pix_fmt', ''))}"]
    if vf:
        cmd.extend(["-vf", ",".join(vf)])
    cmd.extend(["-frames:v", "1", "-y", cikti_png])
    return cmd


def build_command(cfg, probes):
    """
    FFmpeg komutunu kurar. SAF FONKSIYON: Tk yok, disk yok, alt surec yok.

    Olcum gerektiren her sey `probes` sozlugunden gelir; boylece komut kurma
    mantigi GPU/ffmpeg olmadan birim testine girebilir:
        cuda_frames    -> NVDEC gercekten CUDA karesi uretiyor mu
        pix_fmt        -> kaynagin piksel formati (indirme formati secimi icin)
        sub_codecs     -> kaynaktaki altyazi codec'leri
        audio_copy_ok  -> ses hedef konteynere kopyalanabiliyor mu

    (komut_listesi, kullaniciya_gosterilecek_notlar) dondurur.
    """
    # Sadece-altyazi modu hicbir kodlayici/filtre/hwaccel kullanmadigi icin
    # tamamen ayri bir govdeye sahiptir (bkz. build_remux_command).
    if cfg.get("is_remux"):
        return build_remux_command(cfg, probes)

    notes = []
    cuda_frames = probes.get("cuda_frames", False)
    is_pure_cuda = cfg["is_pure_cuda"]
    is_vp9 = cfg["is_vp9"]
    codec_v = cfg["codec_v"]
    container = cfg["container"]
    sub_file = cfg["sub_file"]
    cq_val = cfg["cq_val"]
    preset = cfg["preset"]
    ten_bit = cfg["ten_bit"]

    if cfg.get("upscale_blocked"):
        notes.append(
            f"ℹ️ Kaynak zaten {cfg.get('source_resolution', '?')}; "
            "seçilen hedef daha büyük olduğu için ölçekleme atlandı (büyütme kapalı)."
        )
    if is_pure_cuda and not cuda_frames:
        notes.append("⚠️ Bu kaynağı donanımsal kod çözücü (NVDEC) desteklemiyor. "
                     "Filtreler CPU üzerinde çalışacak, kodlama yine GPU'da (NVENC) yapılacak.")
    if is_pure_cuda and sub_file:
        notes.append("⚠️ UYARI: Saf CUDA modunda donanımsal altyazı desteği yoktur. Altyazı ATLANDI!")

    # ---------- DONANIMSAL COZUCU ----------
    # -hwaccel MARKAYA BAGLIDIR ve yanlisi isi hic baslatmaz: olculdu, AMD
    # makinede "-hwaccel cuda" verilince ffmpeg "Cannot load nvcuda.dll /
    # Device creation failed" deyip cikti dosyasini HIC olusturmuyor. Eskiden
    # bu bayrak komutun basina sabit yazilmisti; kart degisince VP9 dahil her
    # sekme kiriliyordu.
    cmd = ["ffmpeg"]
    hwaccel = cfg.get("hwaccel", "")
    if hwaccel:
        cmd.extend(["-hwaccel", hwaccel])
    if cfg.get("tam_gpu"):
        # Cozulen kare AMF yuzeyi olarak kalir -> kopyasiz zincir.
        cmd.extend(["-hwaccel_output_format", "amf"])
        # AV1 kaynak ek donanim karesi istiyor (ffmpeg AMF wiki); digerlerinde
        # zararsiz oldugu icin kosulsuz veriliyor.
        cmd.extend(["-extra_hw_frames", AMF_EXTRA_HW_FRAMES])
    elif cuda_frames:
        cmd.extend(["-hwaccel_output_format", "cuda"])
    cmd.extend(trim_args(cfg))
    cmd.extend(["-i", cfg["input_file"]])

    vf_filters, filtre_notlari = build_filters(cfg, probes)
    notes.extend(filtre_notlari)
    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    # ---------- AKIS ESLEME ----------
    # FFmpeg'in varsayilan secimi yalnizca 1 video + 1 ses alir; cok dilli
    # kaynaklarda diger ses izleri SESSIZCE kaybolur. Acikca esliyoruz.
    # 0:V:0 -> kapak resmi gibi "attached_pic" akislarini atlayan ilk video.
    cmd.extend(["-map", "0:V:0", "-map", "0:a?"])

    # Altyazi izleri yalnizca MKV'ye guvenle tasinabilir (MP4/WebM'in altyazi
    # destegi kisitli). Hardsub secildiyse iz olarak ayrica eklemeye gerek yok.
    if container == "mkv" and not sub_file:
        sub_codecs = probes.get("sub_codecs") or []
        if sub_codecs:
            # mov_text (MP4 kaynaklardan gelir) matroska'ya kopyalanamaz -> srt'ye cevir
            s_codec = "srt" if "mov_text" in sub_codecs else "copy"
            cmd.extend(["-map", "0:s?", "-c:s", s_codec, "-map", "0:t?"])
            notes.append(f"💬 {len(sub_codecs)} altyazı izi korunuyor ({', '.join(sub_codecs)} -> {s_codec})")

    # ---------- VIDEO KODLAYICI ----------
    cmd.extend(["-c:v", codec_v, "-b:v", "0"])
    if not is_vp9:
        cmd.extend(["-max_muxing_queue_size", "1024"])
    if container == "mp4":
        cmd.extend(["-movflags", "+faststart"])

    if is_vp9:
        notes.append("⚠️ DİKKAT: VP9 Kodlaması İŞLEMCİ (CPU) üzerinden %100 yükte yapılacaktır!")
        cmd.extend(["-crf", cq_val, "-quality", cfg["vp9_quality"], "-speed", cfg["vp9_speed"],
                    "-tile-columns", cfg["vp9_tiles"], "-row-mt", "1"])
        if cfg["vp9_threads"] != "Auto":
            cmd.extend(["-threads", cfg["vp9_threads"]])
        cmd.extend(["-pix_fmt", "yuv420p"])

    elif codec_v == "hevc_nvenc":
        if container == "mp4":
            cmd.extend(["-tag:v", "hvc1"])
        cmd.extend(["-preset:v", preset, "-rc:v", "vbr", "-cq:v", cq_val, "-tune:v", "uhq",
                    "-profile:v", "main10" if ten_bit else "main", "-tier:v", "main",
                    "-level:v", HEVC_LEVEL, "-spatial-aq", "1", "-rc-lookahead", "32",
                    "-bf", "4", "-b_ref_mode", "middle"])
        if ten_bit:
            cmd.extend(["-highbitdepth", "true"])
        if not cuda_frames:
            cmd.extend(["-pix_fmt", "p010le" if ten_bit else "yuv420p"])
        cmd.extend(["-temporal-aq", "1" if cfg["use_temporal_aq"] else "0"])

    elif codec_v == "av1_nvenc":
        cmd.extend(["-preset:v", preset, "-rc:v", "vbr", "-cq:v", cq_val, "-tune:v", "uhq",
                    "-rc-lookahead", "32", "-spatial-aq", "1", "-bf", "4", "-b_ref_mode", "2"])
        if ten_bit:
            cmd.extend(["-highbitdepth", "true"])
        if not cuda_frames:
            cmd.extend(["-pix_fmt", "p010le" if ten_bit else "yuv420p"])
        cmd.extend(["-temporal-aq", "1" if cfg["use_temporal_aq"] else "0"])

    elif codec_v == "h264_nvenc":
        cmd.extend(["-preset:v", preset, "-rc:v", "vbr", "-cq:v", cq_val, "-tune:v", "hq",
                    "-level:v", H264_LEVEL, "-rc-lookahead", "32", "-spatial-aq", "1",
                    "-bf", "3", "-b_ref_mode", "middle"])
        if not cuda_frames:
            cmd.extend(["-pix_fmt", "yuv420p"])
        cmd.extend(["-temporal-aq", "1" if cfg["use_temporal_aq"] else "0"])

    elif codec_v in AMF_CODECS:
        # AMD (AMF) NVENC'ten TAMAMEN farkli bir kalite modeli kullanir:
        #   NVENC: -rc vbr + -cq:v (tek kadran) + -preset p1..p7
        #   AMF  : -rc cqp + ayri -qp_i/-qp_p (0-51) + -quality
        # Kaydiricinin degeri dogrudan QP olarak gecer; olcekleme olculdu ve
        # dogrusal: qp12 -> 19688 kbps, qp36 -> 1949 kbps (1080p, temiz iniş).
        #
        # NEDEN qvbr DEGIL - bu SORU BIR KEZ OLCULDU, tekrar acilmasin:
        # AMF'de "-qvbr_quality_level" var ve teoride -cq:v'nin karsiligi.
        # Ustelik ffmpeg cqp'de "VBAQ is not supported by cqp Rate Control
        # Method, automatically disabled" diye uyariyor. Ikisi de qvbr'yi
        # dogru secim gibi gosteriyor. OLCUM TERSINI SOYLEDI (RX 9070 XT,
        # 720p detayli kaynak, VMAF, ayni bitrate ~20 Mbps):
        #     cqp  -> 92.06        qvbr -> 86.33
        # 5.7 VMAF puani fark. VBAQ'in kapanmasi onemsiz cikti cunku bu
        # surucude VBAQ'in ACIKKEN de hicbir etkisi yok: -vbaq, -preanalysis,
        # -pa_taq_mode, -pa_caq_strength, -preencode BESI DE bayt bayt ayni
        # cikti uretiyor (7240054 bayt). Bayraklar kabul ediliyor ama surucu
        # uygulamiyor. O yuzden bu ailenin hicbiri komuta eklenmiyor.
        #
        # qvbr'nin yonu de terstir (yuksek = iyi kalite), yani kaydiriciyi
        # oldugu gibi baglamak kullaniciyi yanlis yone iterdi.
        #
        # KULLANILMAYAN DIGER AMF SECENEKLERI DE OLCULDU (2026-08-16; gercek
        # icerikten 20 sn, 640x480 kayipsiz referans, VMAF + dosya boyutu):
        #     hevc_amf QP31 temel                  356 KB / 85.32
        #     + preanalysis+lookahead / vbaq /
        #       preencode / high_motion_boost /
        #       async_depth                        HEPSI AYNI: 356 KB / 85.32
        #     + usage=high_quality                 596 KB / 90.76
        #     av1_amf QP136 temel                  344 KB / 82.53
        #     + bf 2                               357 KB / 83.10
        #     + aq_mode 1                          352 KB / 79.33  (KOTU)
        # "usage" ve "bf" kaliteyi artiriyor gibi gorunuyor ama BOYUTU da
        # buyutuyorlar; tek dogru karsilastirma ESIT BOYUT:
        #     usage=high_quality 596 KB -> 90.76 iken temel 623 KB -> 91.38
        #     bf=2               357 KB -> 83.10 iken temel 353 KB -> 83.01
        # Yani ikisi de ayni egrinin uzerinde kaliyor, verim kazanci YOK.
        # Sonuc: bu secenekler komuta EKLENMIYOR; kaliteyi belirleyen sey QP
        # ile -quality on ayari.
        cmd.extend(["-rc", "cqp", "-qp_i", cq_val, "-qp_p", cq_val,
                    "-quality", cfg.get("amf_quality", "quality")])
        if codec_v in AMF_QP_B_KODEKLERI:
            # B kareleri ayri bir QP alir; verilmezse varsayilan degeri I/P ile
            # uyusmuyor. hevc_amf'te bu secenek YOK, oraya verilmez.
            cmd.extend(["-qp_b", cq_val])
        # AMF -level'i yalnizca bitstream'e yazar, bitrate'i KISITLAMAZ
        # (olculdu: level 153 ile 186 bayt bayt ayni cikti). NVENC'teki
        # tavan kusuru burada YOK, o yuzden -level eklenmiyor.
        #
        # AMF H.264 10-bit ALMAZ: "10-bit input video is not supported by AMF
        # H264 encoder" deyip isi hic baslatmiyor. ffmpeg'in kendi
        # "Supported pixel formats" listesi p010le yaziyor ama YANLIS; bu
        # yalnizca calistirarak ogrenilebiliyor.
        amf_10bit = ten_bit and codec_v != "h264_amf"
        if cfg.get("tam_gpu"):
            # Kare AMF yuzeyinde; -pix_fmt vermek zinciri sistem bellegine
            # dusurup kopyasizligi bozar. Bit derinligi kaynaktan gelir.
            notes.append("⚡ TAM GPU hattı: çözme, ölçekleme ve kodlama GPU'da, "
                         "sistem belleğine kopya yok.")
            if ten_bit:
                notes.append("ℹ️ TAM GPU hattında bit derinliği kaynaktan gelir; "
                             "'10-bit kodla' şalteri uygulanmadı.")
        else:
            cmd.extend(["-pix_fmt", "p010le" if amf_10bit else "nv12"])
        notes.append("🔴 AMD (AMF) kodlayıcısı kullanılıyor.")
        if ten_bit and codec_v == "h264_amf":
            notes.append("ℹ️ AMD H.264 kodlayıcısı 10-bit desteklemiyor; "
                         "8-bit olarak kodlanıyor. 10-bit için AV1 veya "
                         "H.265 sekmesini kullanın.")

    # Level bilgisi loga yazilir: uyumluluk sorunu yasandiginda kullanicinin
    # sebebi gorebilmesi icin (level CQ'dan bagimsiz olarak bitstream'e girer).
    if codec_v in ("hevc_nvenc", "h264_nvenc"):
        seviye = HEVC_LEVEL if codec_v == "hevc_nvenc" else H264_LEVEL
        notes.append(f"🎚️ Kodlayıcı seviyesi (level) {seviye}: bitrate tavanı "
                     "kaldırıldı, düşük CQ'da kalite gerçekten artar. Çok eski "
                     "cihazlarda oynatma sorunu çıkarsa sebebi budur.")

    # -multipass NVENC'e OZEL bir secenek. AMF'ye verilirse ffmpeg isi
    # patlatmiyor ama "has not been used for any stream" deyip SESSIZCE yok
    # sayiyor: kullanici ayari actigini sanir, hicbir etkisi olmaz.
    # (-g ise genel bir AVCodecContext secenegi, her kodlayicida gecerli.)
    if cfg["use_multipass"] and codec_v.endswith("_nvenc"):
        cmd.extend(["-multipass", "2"])
    if cfg["use_long_gop"]:
        cmd.extend(["-g", "300"])

    # ---------- SES ----------
    codec_a = cfg["codec_a"]
    if cfg["copy_audio"]:
        if probes.get("audio_copy_ok"):
            cmd.extend(["-c:a", "copy"])
            notes.append("🎵 Ses yeniden kodlanmadan kopyalanıyor (kalite kaybı yok).")
        else:
            # WebM yalnizca opus/vorbis kabul eder; boyle durumlarda isi
            # patlatmak yerine yuksek bitrate ile kodluyoruz. "Yuksek" olmasi
            # kaynagi ASMAK anlamina gelmez: 32 kbps'lik bir sesi 192k'ya
            # kodlamak yalnizca dosyayi buyutur (bkz. ses_bitrate_sinirla).
            yedek_bitrate, _ = ses_bitrate_sinirla("192k", probes.get("audio_bitrate"))
            cmd.extend(["-c:a", codec_a, "-b:a", yedek_bitrate])
            notes.append(f"⚠️ Kaynak ses '{container}' konteynerine kopyalanamıyor; "
                         f"{codec_a} {yedek_bitrate} ile yeniden kodlanacak.")
    else:
        # Kaynaktan yuksek bitrate secmek kaliteyi ARTIRMAZ, yalnizca dosyayi
        # buyutur (bkz. ses_bitrate_sinirla).
        a_bitrate, ses_notu = ses_bitrate_sinirla(cfg["a_bitrate"],
                                                  probes.get("audio_bitrate"))
        cmd.extend(["-c:a", codec_a, "-b:a", a_bitrate])
        if ses_notu:
            notes.append(ses_notu)

    for anahtar, deger in (("title", cfg["meta_title"]), ("artist", cfg["meta_artist"]),
                           ("album", cfg["meta_album"]), ("grouping", cfg["meta_grouping"])):
        if deger.strip():
            cmd.extend(["-metadata", f"{anahtar}={deger}"])

    cmd.extend(["-y", cfg["output_file"]])
    return cmd, notes


# =======================================================
# SADECE ALTYAZI EKLE (KODEK KORUNUR)
# =======================================================
def detect_sub_charenc(path, zorla=""):
    """
    Harici altyazi dosyasinin ffmpeg'e nasil verilecegini OLCER.

    (charenc, cevrim_gerekli) dondurur:
        charenc        -> "-sub_charenc" degeri; "" ise bayrak eklenmez
        cevrim_gerekli -> True ise altyazi KOPYALANAMAZ; cozulup yeniden
                          yazilmalidir (cikti UTF-8 olsun diye)

    Bu fonksiyon diske dokundugu icin build_command'a dogrudan girmez;
    sonucu `probes` sozluguyle tasinir (bkz. run_ffmpeg).
    """
    if zorla:
        # Kullanici elle sectiyse olcume bakmadan cevrim yapilir: zorlanan
        # kodlamanin ciktiya yansimasinin tek yolu altyaziyi yeniden yazmak.
        return zorla, True
    try:
        with open(path, "rb") as fh:
            ham = fh.read()
    except OSError:
        # Okunamadi (izin/yol): sessizce varsayim uretmek yerine hicbir sey
        # yapma, ffmpeg kendi acik hatasini versin.
        return "", False

    # UTF-16 BOM'u ffmpeg'in altyazi cozucusu KENDISI cevirir. "-sub_charenc
    # UTF-16" vermek cift cevrime yol acip "Unable to recode subtitle event"
    # hatasi uretiyor; "copy" ise UTF-16 baytlarini oldugu gibi gecirip
    # okunamaz bir iz birakiyor. Dogrusu: charenc VERMEDEN cevirmek.
    if ham[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "", True

    if ham.startswith(b"\xef\xbb\xbf"):
        ham = ham[3:]
    try:
        ham.decode("utf-8")
    except UnicodeDecodeError:
        return SUB_CHARENC_VARSAYILAN, True
    return "", False


def sub_kodlama_uyusmazligi(sub_file, zorlanan):
    """
    Kullanicinin ELLE sectigi altyazi kodlamasi bu dosyaya uyuyor mu?
    (hata, uyari) dondurur; ikisi de None olabilir. Diski okur, Tk'ye dokunmaz.

    hata  -> Secilen kodlama dosyayi COZEMIYOR. ffmpeg de cozemez: olculdu,
             "Invalid UTF-8 in decoded subtitles text" deyip isi 69 cikis
             koduyla birakiyor. Kuyruga almadan once durdurmak gerekir.
    uyari -> Dosya duzgun UTF-8 ama kullanici 8 bitlik bir kod sayfasi secmis.
             Bu HATA VERMEZ (her kod sayfasi her bayti "cozer") ama Turkce
             harfler bozulur: "Türkçe" -> "TÃ¼rkÃ§e". Sessiz kalmak yanlis.

    "Otomatik" secildiginde (zorlanan bos) burasi hic calismaz; olcumu
    detect_sub_charenc yapar.
    """
    if not zorlanan:
        return None, None
    try:
        with open(sub_file, "rb") as fh:
            ham = fh.read()
    except OSError:
        return None, None

    try:
        ham.decode(zorlanan)
    except (UnicodeDecodeError, LookupError):
        return (f"Seçilen '{zorlanan}' kodlaması bu altyazı dosyasını çözemiyor.\n\n"
                "FFmpeg de çözemez ve iş yarıda kalır. Altyazı kodlamasını "
                "'Otomatik' yapın ya da dosyanın gerçek kodlamasını seçin."), None

    # Dosya temiz UTF-8 iken 8 bitlik bir kod sayfasi secilmisse: hata cikmaz,
    # ama harfler bozulur. ASCII dosyalarda iki yorum ayni sonucu verir, sus.
    if zorlanan.upper().replace("-", "") not in ("UTF8", "UTF16"):
        try:
            metin = ham.decode("utf-8")
        except UnicodeDecodeError:
            return None, None
        if any(ord(ch) > 127 for ch in metin):
            return None, (f"dosya UTF-8 görünüyor ama '{zorlanan}' seçili; "
                          "Türkçe harfler bozuk çıkabilir. "
                          "Kodlamayı 'Otomatik' yapmanız önerilir.")
    return None, None


def harici_sub_codec(sub_file, container, cevrim_gerekli):
    """
    Harici altyazi dosyasinin hedef konteynere hangi codec'le yazilacagi.
    "copy" = dosya bayt bayt gecer; yalnizca UTF-8 metinde guvenlidir.
    """
    if container == "mp4":
        return "mov_text"        # MP4'un kabul ettigi tek metin altyazi
    if not cevrim_gerekli:
        return "copy"
    # Cevirmek gerekiyor: stilli dosyayi srt'ye dusurmek renk/italik bilgisini
    # siler, o yuzden ass olarak yeniden yazilir.
    return "ass" if os.path.splitext(sub_file)[1].lower() in STYLED_SUB_EXTS else "srt"


def gomulu_sub_codec(codec, container):
    """
    Kaynakta ZATEN VAR OLAN bir altyazi izinin hedef konteynere hangi codec'le
    yazilacagi. None dondurmek "tasinamaz, atlanmali" demektir.
    """
    if container == "mp4":
        if codec in BITMAP_SUB_CODECS:
            return None          # resim -> metin cevrilemez
        return "copy" if codec == "mov_text" else "mov_text"
    # MKV pratikte her seyi alir (PGS/VobSub dahil); tek istisna mov_text.
    return "srt" if codec == "mov_text" else "copy"


def remux_sub_plan(cfg, probes):
    """
    Sadece-altyazi modunda hangi altyazi izinin nasil yazilacagini belirler.
    SAF FONKSIYON.

    (izler, atlanan, harici_sira) dondurur:
        izler       -> [(map_ifadesi, codec), ...] cikti altyazi SIRASIYLA
        atlanan     -> hedef konteynere tasinamayan kaynak codec adlari
        harici_sira -> harici altyazinin cikti icindeki altyazi indeksi
                       (-metadata:s:s:N / -disposition:s:N icin)

    Izler tek tek eslenir ("0:s?" gibi toplu degil): boylece tasinamayan
    izler disarida birakilabilir ve "-c:s:N" indeksleri esleme sirasiyla
    birebir tutar.
    """
    container = cfg["container"]
    izler = []
    atlanan = []

    if cfg.get("keep_embedded_subs", True):
        for i, kaynak_codec in enumerate(probes.get("sub_codecs") or []):
            hedef = gomulu_sub_codec(kaynak_codec, container)
            if hedef is None:
                atlanan.append(kaynak_codec)
                continue
            izler.append((f"0:s:{i}", hedef))

    harici_sira = len(izler)
    izler.append(("1:0", harici_sub_codec(cfg["sub_file"], container,
                                          bool(probes.get("sub_needs_transcode")))))
    return izler, atlanan, harici_sira


def build_remux_command(cfg, probes):
    """
    "Sadece altyazi ekle" komutunu kurar. SAF FONKSIYON.

    Video ve ses akislari HIC yeniden kodlanmaz (-c:v copy -c:a copy); kaynagin
    codec'i neyse ciktida aynen kalir. Tek yapilan is harici altyazi dosyasini
    yeni bir iz olarak konteynere eklemektir. Kodlama olmadigi icin -hwaccel,
    -vf, CQ, preset gibi hicbir kodlayici ayari kullanilmaz.

    Kirpma bu modda BILEREK yok: kopyalama kare hassas degildir, kesim en yakin
    anahtar kareye kayar ve harici altyazi buna gore otelenmedigi icin cikti
    desenkron olur (bkz. _prepare_job, kullaniciyi bastan uyarir).
    """
    notes = []
    container = cfg["container"]
    sub_file = cfg["sub_file"]
    charenc = probes.get("sub_charenc") or ""

    cmd = ["ffmpeg", "-hide_banner", "-i", cfg["input_file"]]
    # -sub_charenc GIRDI BASINA bir secenektir: altyazi girdisinden ONCE
    # gelmeli, yoksa hicbir etkisi olmaz.
    if charenc:
        cmd.extend(["-sub_charenc", charenc])
    cmd.extend(["-i", sub_file])

    izler, atlanan, harici_sira = remux_sub_plan(cfg, probes)

    # 0:V:0 -> kapak resmi gibi "attached_pic" akislarini atlayan ilk video.
    cmd.extend(["-map", "0:V:0", "-map", "0:a?"])
    for map_ifadesi, _ in izler:
        cmd.extend(["-map", map_ifadesi])
    if container != "mp4":
        # ASS altyazilarin fontlari konteyner ekleri olarak gelir; MP4 ek
        # tasiyamaz, MKV tasir.
        cmd.extend(["-map", "0:t?"])
    # Bolumler acikca ilk girdiden alinir: birden fazla girdi varken ffmpeg
    # kaynagi kendi seciyor ve altyazi girdisi one gecebiliyor.
    cmd.extend(["-map_chapters", "0"])

    cmd.extend(["-c:v", "copy", "-c:a", "copy"])
    for sira, (_, codec) in enumerate(izler):
        cmd.extend([f"-c:s:{sira}", codec])

    if cfg.get("sub_lang"):
        cmd.extend([f"-metadata:s:s:{harici_sira}", f"language={cfg['sub_lang']}"])
    if cfg.get("sub_lang_label"):
        cmd.extend([f"-metadata:s:s:{harici_sira}", f"title={cfg['sub_lang_label']}"])

    if cfg.get("sub_default"):
        # Yeni iz varsayilan yapilirken ESKI varsayilan da dusurulmeli; yoksa
        # iki iz birden "default" isaretli kalir ve oynatici eskisini secer.
        #
        # "-default" (eksi onekli) YALNIZCA default bayragini kaldirir. Duz "0"
        # yazmak tum bayrak maskesini sifirliyor: olculdu, forced isaretli bir
        # iz forced'ini de kaybediyor (yabanci diyalog izleri boyle bozulur).
        cmd.extend([f"-disposition:s:{harici_sira}", "default"])
        for sira in range(len(izler)):
            if sira != harici_sira:
                cmd.extend([f"-disposition:s:{sira}", "-default"])

    if container == "mp4":
        cmd.extend(["-movflags", "+faststart"])

    for anahtar, deger in (("title", cfg["meta_title"]), ("artist", cfg["meta_artist"]),
                           ("album", cfg["meta_album"]), ("grouping", cfg["meta_grouping"])):
        if deger.strip():
            cmd.extend(["-metadata", f"{anahtar}={deger}"])

    cmd.extend(["-y", cfg["output_file"]])

    # ---------- KULLANICIYA NOTLAR ----------
    notes.append("⚡ Sadece altyazı ekleniyor: video ve ses HİÇ yeniden "
                 "kodlanmıyor, kodek ve kalite birebir korunuyor.")
    harici_codec = izler[harici_sira][1]
    if harici_codec == "copy":
        notes.append("💬 Altyazı dosyası UTF-8; olduğu gibi kopyalanıyor.")
    elif charenc:
        notes.append(f"💬 Altyazı UTF-8 değil: {charenc} olarak okunup UTF-8 "
                     f"'{harici_codec}' izine yazılıyor.")
    else:
        notes.append(f"💬 Altyazı '{harici_codec}' olarak yeniden yazılıyor "
                     "(hedef konteynerin istediği biçim).")

    korunan = len(izler) - 1
    if korunan:
        notes.append(f"💬 Kaynaktaki {korunan} altyazı izi de korunuyor.")
    if atlanan:
        notes.append(f"⚠️ {len(atlanan)} resim tabanlı altyazı izi ATLANDI "
                     f"({', '.join(atlanan)}): MP4 bunları taşıyamaz. "
                     "Korumak için konteyneri MKV seçin.")
    if container == "mp4":
        notes.append("ℹ️ MP4 altyazıyı mov_text olarak tutar: stil/renk bilgisi "
                     "korunmaz ve bazı oynatıcılar bu izi göstermez. "
                     "Uyumluluk için MKV önerilir.")
    if cfg["scale"] != "Orijinal" or color_filter_of(cfg) or cfg.get("use_bwdif"):
        notes.append("ℹ️ Ölçekleme / renk / taraklanma ayarları bu modda "
                     "UYGULANMADI: hepsi yeniden kodlama gerektirir.")

    return cmd, notes


class ReadOnlyComboBox(ctk.CTkComboBox):
    """
    Salt-okunur acilan CTkComboBox.

    CustomTkinter'in varsayilani state=NORMAL'dir, yani kutular serbest
    yazilabilir. Bu iki soruna yol aciyordu:
      1) Dogrulanmamis metin dogrudan ffmpeg komutuna gidiyordu (ornegin
         konteyner kutusuna "mkv4" yazmak bozuk bir cikti uzantisi uretir).
      2) Elle yazilan deger `command` callback'ini TETIKLEMEZ; boylece
         cozunurluk degistiginde CQ otomatigi sessizce calismaz.
    """
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("state", "readonly")
        super().__init__(*args, **kwargs)


def cuda_download_format(pix_fmt):
    """
    CUDA karelerini sistem bellegine indirirken kullanilacak piksel formati.

    hwdownload SADECE karenin gercek formatini kabul eder; yanlis format
    "Invalid output format ... for hwframe download" ile isi komple durdurur.
    Formatlar birbirinin yerine gecmez, olculen esleme (ffmpeg 8.1 / NVDEC):
        8-bit -> nv12,  10-bit -> p010le,  12-bit ve ustu -> p016le
    """
    p = (pix_fmt or "").lower()
    if any(t in p for t in ("p016", "p012", "12le", "12be", "16le", "16be")):
        return "p016le"
    if any(t in p for t in ("p010", "10le", "10be")):
        return "p010le"
    return "nv12"


def escape_filter_path(path):
    """
    Bir dosya yolunu ffmpeg filtre grafigine gomulebilir hale getirir.
    FFmpeg iki ayri kacis seviyesi kullanir:
      2. seviye (filtre secenegi degeri) : \\  :  '
      1. seviye (filtre grafigi metni)   : \\  '  [  ]  ,  ;
    Once icteki, sonra distaki seviye kacirilir. Sonuc TIRNAKSIZ kullanilmalidir;
    tek tirnak icine alinirsa apostrof iceren yollar tekrar bozulur.
    Ornek: C:\\Video\\[Grup] Dizi - 01.srt  ->  C\\\\:/Video/\\[Grup\\] Dizi - 01.srt
    """
    p = path.replace("\\", "/")
    p = "".join(("\\" + ch if ch in "\\:'" else ch) for ch in p)
    p = "".join(("\\" + ch if ch in "\\'[],;" else ch) for ch in p)
    return p


class FFmpegStudioPro(ctk.CTk, _DndBase):
    def __init__(self):
        super().__init__()
        self.title("Nvidia Cuda Video Convertor - Ultimate Edition")
        # Konum da belirtilir: Tk'nin varsayilan yerlesimi pencereyi ekranin
        # ortasina koyup altini gorev cubugunun altinda birakiyordu.
        _gen, _yuk = 900, self._uygun_yukseklik(1300)
        self.geometry("%dx%d+%d+%d" % (
            _gen, _yuk, max(0, (self.winfo_screenwidth() - _gen) // 2), 20))
        # Sabit boyut, kucuk ekranlarda pencerenin altini kesiyordu. Log alani
        # expand=True oldugu icin kucultmeyi o sogurur.
        self.resizable(True, True)
        self.minsize(880, 560)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.current_process = None
        self.is_paused = False
        self.stop_requested = False
        self.delete_requested = False
        self.current_output_file = None
        self._encode_start_time = None
        self._ffmpeg_tail = deque(maxlen=50)

        # --- KUYRUK VE KALICI AYARLAR ---
        self.job_queue = []          # collect_config() anlik goruntuleri
        self.cq_refreshers = {}      # sekme adi -> CQ etiketini tazeleyen callback
        # "Orijinal" secildiginde onerilen CQ bandi kaynagin cozunurlugundan
        # gelir; onbellek SART, cunku etiket kaydirici her oynadiginda
        # tazeleniyor ve her seferinde ffprobe kosmak arayuzu kilitlerdi.
        self._cq_boyut_onbellek = (None, None)   # (dosya yolu, (w, h))
        # {marka: True/False} - acilista OLCULUR (bkz. donanimi_uygula).
        # Tarama bitene kadar bos: hicbir sey varsayilmaz.
        self.donanim = {}
        self.last_video_dir = ""
        self.last_sub_dir = ""
        # Cikti HER ZAMAN kaynak videonun yanina yazilir. Degisken korunuyor
        # (_build_output_path genel kalsin diye) ama arayuzden ayarlanmiyor ve
        # ayarlarda saklanmiyor.
        self.output_dir = ctk.StringVar(value="")
        self.ffmpeg_dir = ctk.StringVar(value="")   # kullanicinin elle gosterdigi klasor
        self.name_with_cq = ctk.BooleanVar(value=True)
        self.trim_start = ctk.StringVar(value="")
        self.trim_end = ctk.StringVar(value="")

        # --- GÖRÜNTÜ VE RENK DEĞİŞKENLERİ ---
        self.color_preset = ctk.StringVar(value="Varsayılan (Devre Dışı)")
        self.val_brightness = ctk.DoubleVar(value=0.0)
        self.val_contrast = ctk.DoubleVar(value=1.0)
        self.val_saturation = ctk.DoubleVar(value=1.0)
        self.val_gamma = ctk.DoubleVar(value=1.0)

        self.val_brightness.trace_add("write", self._update_color_labels)
        self.val_contrast.trace_add("write", self._update_color_labels)
        self.val_saturation.trace_add("write", self._update_color_labels)
        self.val_gamma.trace_add("write", self._update_color_labels)

        # --- FFmpeg Kontrolü ---
        # FFmpeg kontrolu __init__ SONUNDA yapilir: kayitli ffmpeg klasoru
        # ayarlardan yuklendikten sonra karar verilmeli.
        self.ffmpeg_hazir = False

        try:
            ikon_yolu = self.resource_path("icon.ico")
            self.iconbitmap(ikon_yolu)
        except Exception:
            pass

        self.video_path = ctk.StringVar()
        self.sub_path = ctk.StringVar()
        # Dosya degisince onerilen CQ bandi da degisir (band kaynagin
        # cozunurlugunden turuyor). Trace kullaniliyor ki hem dosya secme
        # penceresi hem surukle-birak hem de ileride eklenecek her yol ayni
        # tazelemeyi tetiklesin.
        self.video_path.trace_add("write", lambda *a: self._refresh_all_cq_displays())

        # --- KÖK YERLEŞİM ---
        # Ayar kartları + sekmeler tek başına ~1200 px istiyor; bu 1080p bir
        # ekrana sığmaz ve "Dönüştür" butonu pencerenin altında kalıyordu.
        # Çözüm: ayarlar KAYDIRILABİLİR bir alana konur, buton ve log ise
        # kendi grid satırlarında sabit durur; hangi ekran boyutunda olursa
        # olsun ikisi de her zaman görünür.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)              # ayarlar (kaydırılabilir)
        self.grid_rowconfigure(1, weight=0)              # Dönüştür butonu
        self.grid_rowconfigure(2, weight=0)              # log (sabit: 3 satır)

        self.ust_alan = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.ust_alan.grid(row=0, column=0, sticky="nsew")

        # 1. DOSYA SEÇİM ALANI
        frame_files = self.create_card(self.ust_alan, "🎬 Medya Seçimi")
        frame_files.pack(fill="x", padx=15, pady=(10, 5))

        inner_files = ctk.CTkFrame(frame_files, fg_color="transparent")
        inner_files.pack(fill="x", padx=5, pady=5)

        inner_files.grid_columnconfigure(1, weight=1)

        # --- SATIR 0: video + altyazi ---
        # Altyazi icin ayri bir metin kutusu yok; secilen dosya dogrudan dugmenin
        # uzerinde gorunur. Dugme yalnizca altyaziyi destekleyen sekmelerde cikar
        # (bkz. on_tab_change / _tab_meta -> supports_subs).
        ctk.CTkLabel(inner_files, text="Video Dosyası:").grid(row=0, column=0, padx=(15, 5), pady=10, sticky="w")
        self.entry_vid = ctk.CTkEntry(inner_files, textvariable=self.video_path,
                                      placeholder_text="Dönüştürülecek videoyu seçin veya sürükleyin...")
        self.entry_vid.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(inner_files, text="Gözat", width=90,
                      command=self.select_video).grid(row=0, column=2, padx=5, pady=10)

        self.btn_sub = ctk.CTkButton(inner_files, text=SUB_BTN_BOS, width=170,
                                     fg_color="#555555", hover_color="#444444",
                                     command=self.select_sub)
        self.btn_sub.grid(row=0, column=3, padx=(5, 0), pady=10)
        self.btn_sub_temizle = ctk.CTkButton(inner_files, text="✕", width=28,
                                             fg_color="#7a3030", hover_color="#5e2424",
                                             command=self.clear_sub)
        self.btn_sub_temizle.grid(row=0, column=4, padx=(4, 15), pady=10)
        self.btn_sub_temizle.grid_remove()   # yalnizca altyazi secilince gorunur

        # --- SATIR 1: kucuk secenekler ---
        ctk.CTkCheckBox(inner_files, text="Dosya adına CQ ekle",
                        variable=self.name_with_cq).grid(row=1, column=1, padx=5,
                                                         pady=(0, 10), sticky="w")
        self.btn_ffmpeg = ctk.CTkButton(inner_files, text="⚙️ FFmpeg Yolu", width=170,
                                        fg_color="#555555", hover_color="#444444",
                                        command=self.select_ffmpeg_dir)
        self.btn_ffmpeg.grid(row=1, column=3, columnspan=2, padx=(5, 15), pady=(0, 10), sticky="e")

        # (Sürükle-bırak kurulumu log kutusu oluştuktan sonra yapılır - __init__ sonu)

        # 1.5. KUYRUK (medya seçiminin hemen altında)
        frame_queue = self.create_card(self.ust_alan, "📋 Dönüştürme Kuyruğu")
        frame_queue.pack(fill="x", padx=15, pady=(0, 5))

        queue_top = ctk.CTkFrame(frame_queue, fg_color="transparent")
        queue_top.pack(fill="x", padx=10, pady=(0, 5))
        self.lbl_queue = ctk.CTkLabel(queue_top, text="Kuyruk boş — 'Dönüştür' mevcut ayarları hemen çalıştırır.",
                                      font=("Arial", 11), text_color="#AAAAAA", anchor="w")
        self.lbl_queue.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(queue_top, text="➕ Kuyruğa Ekle", width=130,
                      command=self.add_to_queue).pack(side="left", padx=3)
        # Klasor modu kuyrugun bir ozelligi: tek tek eklemek yerine klasordeki
        # tum videolari ayni ayarlarla bir seferde ekler.
        ctk.CTkButton(queue_top, text="📁 Klasör Ekle", width=125, fg_color="#2fa572",
                      hover_color="#1e6b4a",
                      command=self.select_folder).pack(side="left", padx=3)
        ctk.CTkButton(queue_top, text="➖ Sondakini Sil", width=120, fg_color="#555555",
                      hover_color="#444444", command=self.remove_last_from_queue).pack(side="left", padx=3)
        ctk.CTkButton(queue_top, text="🧹 Temizle", width=90, fg_color="#555555",
                      hover_color="#444444", command=self.clear_queue).pack(side="left", padx=3)

        self.txt_queue = ctk.CTkTextbox(frame_queue, height=56, font=("Consolas", 11),
                                        fg_color="#1A1A1A", corner_radius=8)
        self.txt_queue.pack(fill="x", padx=10, pady=(0, 10))
        self.txt_queue.configure(state="disabled")


        # 2. GÖRÜNTÜ VE RENK AYARLARI ALANI
        frame_color = self.create_card(self.ust_alan, "🎨 Görüntü & Renk Ayarları (Tüm Sekmeler İçin)")
        frame_color.pack(fill="x", padx=15, pady=(0, 5))

        inner_color = ctk.CTkFrame(frame_color, fg_color="transparent")
        inner_color.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(inner_color, text="Ayar Profili:").grid(row=0, column=0, padx=15, pady=5, sticky="w")
        self.cb_preset = ReadOnlyComboBox(
            inner_color,
            variable=self.color_preset,
            values=["Varsayılan (Devre Dışı)", "Karanlık Video Kurtarma", "Özel Ayarlar"],
            command=self.on_color_preset_change,
            width=250
        )
        self.cb_preset.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        # --- KIRPMA + ONIZLEME (yeni kart acmamak icin ayni satira) ---
        frame_trim = ctk.CTkFrame(inner_color, fg_color="transparent")
        frame_trim.grid(row=0, column=2, padx=(15, 5), pady=5, sticky="w")
        ctk.CTkLabel(frame_trim, text="Kırpma  Baş:").pack(side="left", padx=(0, 4))
        ctk.CTkEntry(frame_trim, textvariable=self.trim_start, width=70,
                     placeholder_text="00:00").pack(side="left")
        ctk.CTkLabel(frame_trim, text="Bitiş:").pack(side="left", padx=(8, 4))
        ctk.CTkEntry(frame_trim, textvariable=self.trim_end, width=70,
                     placeholder_text="sonuna").pack(side="left")
        ctk.CTkButton(frame_trim, text="🖼️ Önizleme", width=110,
                      command=self.show_preview_frame).pack(side="left", padx=(12, 0))

        self.frame_sliders = ctk.CTkFrame(inner_color, fg_color="transparent")
        self.frame_sliders.grid(row=1, column=0, columnspan=3, sticky="we", padx=10, pady=5)
        self.frame_sliders.grid_remove() 

        # Brightness (-1.0 to 1.0)
        ctk.CTkLabel(self.frame_sliders, text="Parlaklık:").grid(row=0, column=0, sticky="w", padx=5)
        self.slider_bright = ctk.CTkSlider(self.frame_sliders, variable=self.val_brightness, from_=-1.0, to=1.0, number_of_steps=40, width=150)
        self.slider_bright.grid(row=0, column=1, padx=5, pady=2)
        self.lbl_bright_val = ctk.CTkLabel(self.frame_sliders, text="0.00", width=30)
        self.lbl_bright_val.grid(row=0, column=2, padx=5)

        # Contrast (0.0 to 2.0)
        ctk.CTkLabel(self.frame_sliders, text="Kontrast:").grid(row=0, column=3, sticky="w", padx=(15,5))
        self.slider_cont = ctk.CTkSlider(self.frame_sliders, variable=self.val_contrast, from_=0.0, to=2.0, number_of_steps=40, width=150)
        self.slider_cont.grid(row=0, column=4, padx=5, pady=2)
        self.lbl_cont_val = ctk.CTkLabel(self.frame_sliders, text="1.00", width=30)
        self.lbl_cont_val.grid(row=0, column=5, padx=5)

        # Saturation (0.0 to 3.0)
        ctk.CTkLabel(self.frame_sliders, text="Doygunluk:").grid(row=1, column=0, sticky="w", padx=5)
        self.slider_sat = ctk.CTkSlider(self.frame_sliders, variable=self.val_saturation, from_=0.0, to=3.0, number_of_steps=60, width=150)
        self.slider_sat.grid(row=1, column=1, padx=5, pady=2)
        self.lbl_sat_val = ctk.CTkLabel(self.frame_sliders, text="1.00", width=30)
        self.lbl_sat_val.grid(row=1, column=2, padx=5)

        # Gamma (0.1 to 3.0)
        ctk.CTkLabel(self.frame_sliders, text="Gamma:").grid(row=1, column=3, sticky="w", padx=(15,5))
        self.slider_gamma = ctk.CTkSlider(self.frame_sliders, variable=self.val_gamma, from_=0.1, to=3.0, number_of_steps=58, width=150)
        self.slider_gamma.grid(row=1, column=4, padx=5, pady=2)
        self.lbl_gamma_val = ctk.CTkLabel(self.frame_sliders, text="1.00", width=30)
        self.lbl_gamma_val.grid(row=1, column=5, padx=5)

        # 3. SEKMELER
        self.tabview = ctk.CTkTabview(self.ust_alan, command=self.on_tab_change)
        self.tabview.pack(fill="x", padx=15, pady=5)

        self.tabs = {}

        self.create_tab("AV1 (Standart)", "av1_nvenc")
        self.create_tab("H.265 (Standart)", "hevc_nvenc")
        self.create_tab("H.264 (Standart)", "h264_nvenc")
        # Sekme adlari AMF_SEKME_ADI'ndan gelir: "cok kucuk" uyarisi kullaniciyi
        # ada gore yonlendiriyor, iki yerde ayri yazilsa biri eskirdi.
        for amf_kodek, amf_sekme in AMF_SEKME_ADI.items():
            self.create_amd_tab(amf_sekme, amf_kodek)
        self.create_tamgpu_tab(TAMGPU_SEKME)
        self.create_vp9_tab("VP9 (Google VOD)")
        self.create_cuda_tab("⚡ SAF CUDA")
        self.create_remux_tab("💬 SADECE ALTYAZI")

        # Acilis sekmesi BURADA SECILMEZ; donanim taramasindan SONRA secilir
        # (bkz. donanimi_uygula). Sebep olculdu: CTkTabview.set() 100 ms
        # sonrasina "secili olmayan sekmeleri gizle" isi planliyor. Burada
        # "SAF CUDA" secilip hemen ardindan o sekme "donanimi yok" diye
        # silinince, gecikmeli is ARTIK OLMAYAN bir adi koruyor ve yerine
        # gecen sekmenin cercevesini de gizliyordu. Sonuc: acilista sekme
        # seridi doluyken icerik alani BOS geliyor ve ancak kullanici bir
        # sekmeye tiklayinca duzeliyordu.

        # 4. BAŞLAT BUTONU
        self.btn_start = ctk.CTkButton(
            self, text="🚀 SEÇİLİ SEKMEYE GÖRE DÖNÜŞTÜR",
            font=("Arial", 16, "bold"), height=50, corner_radius=25,
            command=self.start_thread
        )
        self.btn_start.grid(row=1, column=0, sticky="ew", padx=15, pady=10)

        self.on_tab_change()

        # 5. LOG VE İLERLEME EKRANI
        frame_log = self.create_card(self, "📟 FFmpeg Terminal ve Durum")
        frame_log.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 15))

        frame_prog_controls = ctk.CTkFrame(frame_log, fg_color="transparent")
        frame_prog_controls.pack(fill="x", padx=10, pady=(5, 5))

        self.progress_bar = ctk.CTkProgressBar(frame_prog_controls, height=18, progress_color="#00FF00")
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_bar.set(0)

        self.lbl_progress = ctk.CTkLabel(frame_prog_controls, text="% 0.0", font=("Arial", 15, "bold"), text_color="#00FF00", width=60)
        self.lbl_progress.pack(side="left", padx=(0, 5))

        self.lbl_eta = ctk.CTkLabel(frame_prog_controls, text="", font=("Arial", 11), text_color="#AAAAAA", width=90)
        self.lbl_eta.pack(side="left", padx=(0, 10))

        self.btn_pause = ctk.CTkButton(frame_prog_controls, text="⏸️ Pause", width=70, state="disabled", fg_color="#1f538d", command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=3)

        self.btn_stop = ctk.CTkButton(frame_prog_controls, text="⏹️ İptal", width=70, state="disabled", fg_color="#FF8C00", hover_color="#CC7000", command=self.stop_process)
        self.btn_stop.pack(side="left", padx=3)

        self.btn_delete = ctk.CTkButton(frame_prog_controls, text="🗑️ Sil", width=60, state="disabled", fg_color="#FF0000", hover_color="#CC0000", command=self.delete_process)
        self.btn_delete.pack(side="left", padx=3)

        # 3 satirlik terminal: Consolas 11'de satir 18 px. Sabit tutulur (grid
        # agirligi 0) ki pencere buyudugunde artan yer ayarlara gitsin.
        self.txt_log = ctk.CTkTextbox(frame_log, height=LOG_SATIR_SAYISI * 18 + 8,
                                      font=("Consolas", 11), text_color="#00FF00",
                                      fg_color="#000000", corner_radius=10)
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.txt_log.configure(state="disabled")

        self.on_tab_change()

        # --- Sürükle & Bırak (log kutusu hazır olduktan sonra) ---
        self._setup_drag_and_drop()

        # --- KAYITLI AYARLAR (tüm widget'lar oluştuktan sonra) ---
        self.load_settings()
        self._refresh_queue_view()

        # FFmpeg durumu: ayarlardaki klasör yüklendikten SONRA karara bağlanır.
        # Bulunamazsa kullanıcıya doğrudan klasör seçme seçeneği sunulur.
        self.check_ffmpeg()

        # Donanım taraması EN SON: doğru ffmpeg ikilisi belli olduktan sonra
        # ölçüm yapılmalı. ~0.3 sn sürer (ölçüldü: NVENC 74 ms, AMF 243 ms).
        self.donanimi_uygula()

    # =======================================================
    # UI: RENK AYARLARI FONKSİYONLARI
    # =======================================================
    def on_color_preset_change(self, choice):
        if choice == "Özel Ayarlar":
            self.frame_sliders.grid()
        else:
            self.frame_sliders.grid_remove()

    def _update_color_labels(self, *args):
        try:
            self.lbl_bright_val.configure(text=f"{self.val_brightness.get():.2f}")
            self.lbl_cont_val.configure(text=f"{self.val_contrast.get():.2f}")
            self.lbl_sat_val.configure(text=f"{self.val_saturation.get():.2f}")
            self.lbl_gamma_val.configure(text=f"{self.val_gamma.get():.2f}")
        except Exception:
            pass

    # =======================================================
    # DRAG & DROP
    # =======================================================
    def _setup_drag_and_drop(self):
        if not HAS_DND:
            self.log("ℹ️ Sürükle-bırak devre dışı ('tkinterdnd2' kurulu değil). "
                     "Etkinleştirmek için: pip install tkinterdnd2")
            return
        try:
            # tkdnd Tcl paketini yukler ve mixin'i bu pencereye baglar.
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._on_drop)
        except Exception as e:
            # Sessizce yutma: eskiden bos bir 'except: pass' vardi ve ozelligin
            # hic calismadigi yillarca fark edilmiyordu.
            self.log(f"⚠️ Sürükle-bırak başlatılamadı: {e}")

    def _on_drop(self, event):
        # Birden fazla dosya birakildiginda event.data "{C:/a b.mkv} C:/c.srt"
        # bicimindedir; ayristirmayi Tcl'e birakmak bosluklu yollari da cozer.
        try:
            paths = [p for p in self.tk.splitlist(event.data) if p]
        except Exception:
            paths = [event.data.strip('{}')]

        video = next((p for p in paths if os.path.splitext(p)[1].lower() in VIDEO_EXTS), None)
        sub = next((p for p in paths if os.path.splitext(p)[1].lower() in SUB_EXTS), None)

        if video:
            self.video_path.set(video)
            self.log(f"Video Sürüklendi: {os.path.basename(video)}")
        if sub:
            self.sub_path.set(sub)
            self.log(f"Altyazı Sürüklendi: {os.path.basename(sub)}")
        if not video and not sub and paths:
            self.log(f"⚠️ Desteklenmeyen dosya türü: {os.path.basename(paths[0])}")

    # =======================================================
    # KONTROL FONKSİYONLARI
    # =======================================================
    def toggle_pause(self):
        if not self.current_process: return

        if not HAS_PSUTIL:
            messagebox.showerror("Eksik Modül", "Durdurma (Pause) özelliği için işletim sistemi düzeyinde 'psutil' modülü gereklidir.\n\nLütfen terminali açıp şu komutu çalıştırın:\npip install psutil")
            return

        try:
            p = psutil.Process(self.current_process.pid)
            if self.is_paused:
                p.resume()
                self.is_paused = False
                self.btn_pause.configure(text="⏸️ Pause", fg_color="#1f538d")
                self.log("▶️ İŞLEM DEVAM ETTİRİLİYOR...")
            else:
                p.suspend()
                self.is_paused = True
                self.btn_pause.configure(text="▶️ Devam", fg_color="#2fa572")
                self.log("⏸️ İŞLEM DONDURULDU! (Ekran kartı beklemede...)")
        except Exception as e:
            self.log(f"⚠️ Duraklatma Hatası: {e}")

    def _resume_if_paused(self, p):
        """Donmus bir sureci durdurmadan once devam ettirir."""
        if self.is_paused and HAS_PSUTIL:
            try:
                psutil.Process(p.pid).resume()
            except Exception:
                pass
            self.is_paused = False
            self.btn_pause.configure(text="⏸️ Pause", fg_color="#1f538d")

    def _graceful_stop(self, p):
        """
        FFmpeg'e stdin uzerinden 'q' gonderir. FFmpeg o anki kareyi bitirip
        konteyneri duzgun kapatir; boylece o ana kadar kodlanan kisim
        oynatilabilir kalir. kill() ile durdurulan MP4'te moov atom yazilmadigi
        icin dosya tamamen bozuk oluyordu.
        """
        try:
            p.stdin.write("q")
            p.stdin.flush()
        except Exception:
            # Sureç zaten kapanmis ya da stdin kullanilamiyor -> son care
            self._force_kill(p)
            return
        self.log("⏹️ Durduruluyor... (dosya düzgün kapatılıyor, büyük dosyalarda biraz sürebilir)")
        # FFmpeg yanit vermezse 15 sn sonra zorla sonlandir
        self.after(15000, lambda: self._force_kill(p))

    def _force_kill(self, p):
        try:
            if p.poll() is None:
                self.log("⚠️ FFmpeg yanıt vermedi, süreç zorla sonlandırılıyor.")
                p.kill()
        except Exception:
            pass

    def stop_process(self):
        p = self.current_process
        if p:
            cevap = messagebox.askyesno("İptal Onayı", "Mevcut render işlemini iptal etmek istediğinize emin misiniz?\n\nO ana kadar kodlanan bölüm dosyada kalır ve oynatılabilir.")
            if cevap:
                self.stop_requested = True
                self._resume_if_paused(p)
                self._graceful_stop(p)

    def delete_process(self):
        p = self.current_process
        if p:
            cevap = messagebox.askyesno("Sil Onayı", "DİKKAT! İşlem durdurulacak ve şu ana kadar yaratılan yarım dosya DİSKTEN SİLİNECEK.\nEmin misiniz?")
            if cevap:
                self.stop_requested = True
                self.delete_requested = True
                self._resume_if_paused(p)
                # Dosya nasilsa silinecek; konteyneri duzgun kapatmak icin beklemenin
                # anlami yok (MP4'te +faststart tum dosyayi yeniden yazar).
                self._force_kill(p)

    def on_closing(self):
        self.save_settings()
        if self.current_process is not None and self.current_process.poll() is None:
            try:
                self.current_process.kill()
            except Exception:
                pass
        self.destroy()

    def resource_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def create_card(self, parent, title, **kwargs):
        card = ctk.CTkFrame(parent, corner_radius=15, border_width=1, border_color="#3A3A3A", fg_color="#242424", **kwargs)
        lbl = ctk.CTkLabel(card, text=title, font=("Segoe UI", 15, "bold"), text_color="#DDDDDD")
        lbl.pack(anchor="w", padx=15, pady=(10, 5))
        return card

    # =======================================================
    # ORTAK KART URETICILERI
    # (create_tab ile create_cuda_tab arasindaki kopya kod buraya toplandi)
    # =======================================================
    AUDIO_VALUES = [SES_KOPYALA] + [f"{k}k" for k in SES_BITRATE_ADIMLARI]
    PRESET_VALUES = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
    SCALE_VALUES = ["Orijinal", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K"]
    VP9_AUDIO_VALUES = [SES_KOPYALA, "64k", "96k", "128k", "192k"]

    # Kayitli ayarlar yuklenirken dogrulama icin: combobox'lar salt-okunur
    # oldugundan gecersiz bir deger kutuda takili kalir ve ffmpeg'e gider.
    ALLOWED_VALUES = {
        "container": ["mkv", "mp4", "webm"],
        "audio_bitrate": AUDIO_VALUES,
        "preset": PRESET_VALUES,
        "scale": SCALE_VALUES,
        "interp_algo": ["Otomatik", "bilinear", "bicubic", "lanczos"],
        # NVENC (SAF CUDA) ve AMF (TAM GPU) sekmeleri ayni degisken adini
        # kullanir; ikisinin degerleri de gecerli sayilmali, yoksa kaydedilmis
        # ayar dogrulamadan gecemez ve sessizce yok sayilir.
        "selected_codec": (["AV1 (av1_nvenc)", "H.265 (hevc_nvenc)", "H.264 (h264_nvenc)"]
                           + [f"{ad.split(' ')[0]} ({kod})"
                              for kod, ad in AMF_SEKME_ADI.items()]),
        "amf_sr_algo": list(AMF_SR_ALGORITMALARI),
        "vp9_quality": ["good (Önerilen)", "best (Aşırı Yavaş)", "realtime"],
        "vp9_speed": ["0 (Maksimum Kalite)", "1 (VOD Önerisi)", "2 (Standart)", "3 (Hızlı)", "4", "5 (En Hızlı)"],
        "vp9_tiles": ["0 (Tek Sütun)", "1 (Düşük Çöz. için)", "2 (1080p için)", "3 (4K/1440p için)", "4 (8K)"],
        "vp9_threads": ["Auto", "2", "4", "8", "16", "32"],
        "sub_lang": list(SUB_DIL_SECENEKLERI),
        "sub_charenc": list(SUB_CHARENC_SECENEKLERI),
        "amf_quality": AMF_QUALITY_VALUES,
        "cozucu": list(COZUCU_SECENEKLERI),
    }

    def _create_audio_card(self, parent, tab_vars, pady):
        card = self.create_card(parent, "🎵 Ses Kalitesi")
        card.pack(fill="x", pady=pady)
        ReadOnlyComboBox(card, variable=tab_vars["audio_bitrate"],
                         values=self.AUDIO_VALUES).pack(fill="x", padx=15, pady=(0, 15))
        return card

    def _create_nvenc_card(self, parent, tab_vars, title, on_cq_change):
        """Preset + CQ slider karti. (lbl_title, lbl_status, slider) dondurur."""
        card = self.create_card(parent, title)
        card.pack(fill="x", pady=10)
        ctk.CTkLabel(card, text="NVENC Preset:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card, variable=tab_vars["preset"],
                         values=self.PRESET_VALUES).pack(fill="x", padx=15, pady=(0, 15))

        lbl_title = ctk.CTkLabel(card, text=f"CQ (Kalite): {tab_vars['cq'].get()}", font=("Arial", 13, "bold"))
        lbl_status = ctk.CTkLabel(card, text="", font=("Arial", 11, "italic"))
        lbl_title.pack(anchor="w", padx=15, pady=(5, 0))
        lbl_status.pack(anchor="w", padx=15, pady=(0, 5))

        slider = ctk.CTkSlider(card, from_=0, to=51, number_of_steps=51,
                               variable=tab_vars["cq"], command=on_cq_change)
        slider.pack(fill="x", padx=15, pady=(0, 15))
        return lbl_title, lbl_status, slider

    def _add_toggle(self, parent, text, variable, aciklama, son=False):
        """Bir onay kutusu ve hemen altina ne ise yaradigini anlatan kisa not."""
        ctk.CTkCheckBox(parent, text=text, variable=variable).pack(anchor="w", padx=15, pady=(6, 0))
        # height verilmezse CTkLabel tek satir icin bile 28 px yer kapliyor;
        # 6 salterde bu ~70 px gereksiz kaydirma demek.
        ctk.CTkLabel(parent, text=aciklama, font=("Arial", 10, "italic"),
                     text_color="#8A8A8A", justify="left", anchor="w",
                     height=16, wraplength=430).pack(anchor="w", padx=(40, 12),
                                                     pady=(0, 10 if son else 1))

    # Salter kartinda kac sutun kullanilacagi. 3 sutunda aciklamalar tek satira
    # sigacak sekilde kisaltildi; iki satira tasarsa kazanc kaybolur.
    SALTER_SUTUN = 3

    def _create_toggles_card(self, parent, tab_vars, title, bwdif_text, cuda=False):
        """
        Kontrol salterleri karti. Sekmenin ALTINDA tam genislikte, salterler
        yan yana yerlestirilir; dikey olarak sag sutunda dizildiginde tek basina
        ~354 px yer kapliyor ve sekme yuksekligini o belirliyordu.
        Karti yerlestirmez - cagiran grid/pack ile konumlandirir.
        """
        card = self.create_card(parent, title)

        ogeler = [
            (bwdif_text, tab_vars["bwdif"],
             "GPU'da tarak izlerini giderir." if cuda
             else "Tarak izlerini giderir (taraklı kaynak için)."),
            ("Zamansal AQ (temporal-aq)", tab_vars["temporal_aq"],
             "Biti hareketli sahnelere kaydırır."),
            ("Çift Geçiş (-multipass 2)", tab_vars["multipass"],
             "Daha yavaş, zor sahnelerde daha kararlı."),
            ("Uzun GOP (-g 300)", tab_vars["long_gop"],
             "Dosya küçülür, sarma kabalaşır."),
            ("Kaynaktan büyütme yapma", tab_vars["no_upscale"],
             "Büyütme yapmaz, biti boşa harcamaz."),
            ("10-bit kodla (main10)", tab_vars["ten_bit"],
             "Bantlanmayı azaltır; kapalıysa uyum artar."),
        ]

        kafes = ctk.CTkFrame(card, fg_color="transparent")
        kafes.pack(fill="x", padx=10, pady=(0, 10))
        for i in range(self.SALTER_SUTUN):
            kafes.grid_columnconfigure(i, weight=1, uniform="salter")

        for sira, (metin, degisken, aciklama) in enumerate(ogeler):
            satir, sutun = divmod(sira, self.SALTER_SUTUN)
            hucre = ctk.CTkFrame(kafes, fg_color="transparent")
            hucre.grid(row=satir, column=sutun, sticky="nsew", padx=4, pady=(4, 2))
            ctk.CTkCheckBox(hucre, text=metin, variable=degisken).pack(anchor="w")
            ctk.CTkLabel(hucre, text=aciklama, font=("Arial", 10, "italic"),
                         text_color="#8A8A8A", justify="left", anchor="w",
                         height=16, wraplength=260).pack(anchor="w", padx=(26, 0), pady=(1, 0))
        return card

    def _uygun_yukseklik(self, istenen):
        """
        Pencere yuksekligini ekranin KULLANILABILIR alanina sigdirir.
        Gorev cubugu hesaba katilmazsa pencerenin alti onun altinda kalir.
        """
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                alan = wintypes.RECT()
                # SPI_GETWORKAREA = 0x0030 -> gorev cubugu haric masaustu alani
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(alan), 0):
                    kullanilabilir = alan.bottom - alan.top
                else:
                    kullanilabilir = self.winfo_screenheight() - 80
            else:
                kullanilabilir = self.winfo_screenheight() - 80
            # Pencere cercevesi + baslik cubugu icin pay birak
            return max(560, min(istenen, kullanilabilir - 60))
        except Exception:
            return istenen

    def _tab_meta(self, is_pure_cuda, is_vp9, accent, supports_subs=True,
                  is_remux=False, is_tamgpu=False):
        """Sekme davranisini isim icinde metin aramak yerine veri olarak tasir."""
        return {
            "is_pure_cuda": is_pure_cuda,
            "is_vp9": is_vp9,
            "accent": accent,             # (renk, hover, yazi rengi) - baslat butonu
            "supports_subs": supports_subs,
            # True ise kodlama YOK: video/ses kopyalanir, yalnizca altyazi eklenir.
            "is_remux": is_remux,
            # True ise kare AMF yuzeyinde kalir (kopyasiz hat, bkz.
            # create_tamgpu_tab). Cozucu artik burada belirlenir, sekme
            # icindeki bir listeyle degil.
            "is_tamgpu": is_tamgpu,
        }

    def _nvenc_tab_vars(self, container_default, cq_default):
        """Her iki NVENC sekmesinin paylastigi degisken seti."""
        return {
            "container": ctk.StringVar(value=container_default),
            "audio_bitrate": ctk.StringVar(value=SES_KOPYALA),
            "preset": ctk.StringVar(value="p7"),
            "cq": ctk.IntVar(value=cq_default),
            # Tk degiskeni DEGIL, duz sayi: en son OTOMATIK konan CQ. Dosya
            # degisince kadrani ancak kullanici ellememisse tazeliyoruz ve
            # bunu anlamanin tek yolu bu (bkz. _update_cq_display). Ayarlar
            # kaydedilirken suzuluyor (hasattr(v, "get") kosulu).
            "cq_auto": cq_default,
            "scale": ctk.StringVar(value="Orijinal"),
            "metadata_title": ctk.StringVar(value=""),
            "metadata_artist": ctk.StringVar(value=""),
            "metadata_album": ctk.StringVar(value=""),
            "metadata_grouping": ctk.StringVar(value=""),
            "bwdif": ctk.BooleanVar(value=False),
            "temporal_aq": ctk.BooleanVar(value=True),
            "multipass": ctk.BooleanVar(value=False),
            "long_gop": ctk.BooleanVar(value=False),
            "no_upscale": ctk.BooleanVar(value=True),
            "ten_bit": ctk.BooleanVar(value=True),
        }

    def _create_metadata_card(self, parent, tab_vars):
        card_meta = self.create_card(parent, "🏷️ Metadata Eklemeleri")
        card_meta.pack(fill="x", pady=10)
        meta_grid = ctk.CTkFrame(card_meta, fg_color="transparent")
        meta_grid.pack(fill="x", padx=10, pady=(0, 10))

        for i, (label, key) in enumerate([("Title:", "metadata_title"), ("Artist:", "metadata_artist"), ("Album:", "metadata_album"), ("Group:", "metadata_grouping")]):
            ctk.CTkLabel(meta_grid, text=label).grid(row=i, column=0, sticky="w", padx=5, pady=2)
            ctk.CTkEntry(meta_grid, textvariable=tab_vars[key], width=180).grid(row=i, column=1, pady=2)
        return card_meta

    # =======================================================
    # UI/UX: DİNAMİK SEKME VE HAYALET ALTYAZI ALANI
    # =======================================================
    def on_tab_change(self):
        # Sekme adinda metin aramak yerine sekmenin kendi metadata'si okunur
        # (bkz. _tab_meta): sekme adi degisince mantik sessizce bozulmaz.
        tab_vars = self.tabs.get(self.tabview.get(), {})
        color, hover, text_color = tab_vars.get("accent", ("#1f538d", "#14375e", "white"))

        if tab_vars.get("supports_subs", True):
            self.btn_sub.grid()
            if self.sub_path.get():
                self.btn_sub_temizle.grid()
        else:
            self.btn_sub.grid_remove()
            self.btn_sub_temizle.grid_remove()

        self.btn_start.configure(fg_color=color, hover_color=hover, text_color=text_color)
        self.tabview.configure(segmented_button_selected_color=color, segmented_button_selected_hover_color=hover)

    # =======================================================
    # ORTAK CQ SLIDER GÜNCELLEME
    # =======================================================
    def _kaynak_boyut_cq(self):
        """
        CQ bandi icin kaynagin (genislik, yukseklik) degeri; yoksa None.
        Onbellekli: bkz. _cq_boyut_onbellek.
        """
        yol = self.video_path.get()
        if not yol or not os.path.isfile(yol):
            return None
        if self._cq_boyut_onbellek[0] != yol:
            self._cq_boyut_onbellek = (yol, self.get_video_resolution(yol))
        boyut = self._cq_boyut_onbellek[1]
        return boyut if boyut and boyut[0] and boyut[1] else None

    def _update_cq_display(self, codec, tab_vars, lbl_cq_title, lbl_cq_status, slider_cq, label_prefix="CQ (Kalite)"):
        v = int(float(tab_vars["cq"].get()))
        current_scale = tab_vars["scale"].get()

        kaynak = self._kaynak_boyut_cq()
        min_cq, max_cq = get_cq_range(codec, current_scale, kaynak)

        # "Orijinal"de band kaynagin cozunurlugundan geldigi icin DOSYA
        # DEGISINCE kayar. Kullanici kadrani ELLEMEDIYSE (deger hala en son
        # otomatik konan degerse) yeni bandin kalite ucuna otur; elle bir
        # deger sectiyse ASLA dokunma. Bu olmadan sekme 1080p varsayilaniyla
        # aciliyor ve 4K bir dosya yuklenince kirmizi uyarida oylece
        # bekliyordu -- kullanicinin fark etmesi gerekiyordu.
        varsayilan = get_cq_default(codec, current_scale, kaynak)
        if (tab_vars.get("cq_auto") is not None and v == tab_vars["cq_auto"]
                and v != varsayilan):
            v = varsayilan
            tab_vars["cq_auto"] = v
            tab_vars["cq"].set(v)
            slider_cq.set(v)

        lbl_cq_title.configure(text=f"{label_prefix}: {v}")

        # Bandin neye gore secildigini yaz: "Orijinal"de sayilar kaynaga gore
        # degisiyor ve sebebi gorunmezse kullanici kadranin kendiliginden
        # oynadigini saniyor.
        band_eki = ""
        if current_scale == "Orijinal" and kaynak:
            ad = cozunurluk_bandi(*kaynak)
            if ad:
                band_eki = f" — {ad} kaynak"

        if min_cq <= v <= max_cq:
            lbl_cq_status.configure(text=f"✨ Önerilen Aralık ({min_cq}-{max_cq}){band_eki}", text_color="#00FF00")
            slider_cq.configure(progress_color="#00FF00")
        elif v < min_cq:
            lbl_cq_status.configure(text=f"⚠️ Gereksiz Büyük Dosya (< {min_cq}){band_eki}", text_color="#FFA500")
            slider_cq.configure(progress_color="#FFA500")
        else:
            lbl_cq_status.configure(text=f"❌ Çamurlaşma Riski (> {max_cq}){band_eki}", text_color="#FF4444")
            slider_cq.configure(progress_color="#FF4444")

    def _auto_set_cq(self, codec, scale, tab_vars, slider_cq, lbl_cq_title, lbl_cq_status, label_prefix="CQ (Kalite)"):
        val = get_cq_default(codec, scale, self._kaynak_boyut_cq())
        # Otomatik konan degeri isaretle: kullanicinin elle sectigi bir degeri
        # dosya degisiminde ezmemek icin tek dayanak bu (bkz. _update_cq_display).
        tab_vars["cq_auto"] = val
        tab_vars["cq"].set(val)
        slider_cq.set(val)
        self._update_cq_display(codec, tab_vars, lbl_cq_title, lbl_cq_status, slider_cq, label_prefix)

    # =======================================================
    # VP9 SEKMESİ
    # =======================================================
    def create_vp9_tab(self, tab_name):
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        tab_vars = {
            "codec": "libvpx-vp9",
            "container": ctk.StringVar(value="webm"),
            "audio_bitrate": ctk.StringVar(value=SES_KOPYALA),
            "cq": ctk.IntVar(value=31),
            "cq_auto": 31,          # bkz. _nvenc_tab_vars: elle secim korumasi
            "scale": ctk.StringVar(value="Orijinal"),
            "vp9_quality": ctk.StringVar(value="good (Önerilen)"),
            "vp9_speed": ctk.StringVar(value="1 (VOD Önerisi)"),
            "vp9_tiles": ctk.StringVar(value="2 (1080p için)"),
            "vp9_threads": ctk.StringVar(value="Auto"),
            "no_upscale": ctk.BooleanVar(value=True),
            "metadata_title": ctk.StringVar(value=""),
            "metadata_artist": ctk.StringVar(value=""),
            "metadata_album": ctk.StringVar(value=""),
            "metadata_grouping": ctk.StringVar(value=""),
        }
        tab_vars.update(self._tab_meta(is_pure_cuda=False, is_vp9=True,
                                       accent=("#8e44ad", "#732d91", "white")))
        self.tabs[tab_name] = tab_vars

        main_grid = ctk.CTkFrame(frame, fg_color="transparent")
        main_grid.pack(fill="both", expand=True)
        main_grid.columnconfigure(0, weight=1)
        main_grid.columnconfigure(1, weight=1)

        col_left = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_left.grid(row=0, column=0, sticky="nsew", padx=5)

        def on_cq_change_vp9(*args):
            self._update_cq_display("libvpx-vp9", tab_vars, lbl_cq_title, lbl_cq_status, slider_cq, "Google VOD CQ")

        def on_vp9_scale_change(choice):
            self._auto_set_cq("libvpx-vp9", choice, tab_vars, slider_cq, lbl_cq_title, lbl_cq_status, "Google VOD CQ")
            if choice in ["4K", "1440p"]: tab_vars["vp9_tiles"].set("3 (4K/1440p için)")
            elif choice in ["1080p", "720p", "Orijinal"]: tab_vars["vp9_tiles"].set("2 (1080p için)")
            else: tab_vars["vp9_tiles"].set("1 (Düşük Çöz. için)")

        card_format = self.create_card(col_left, "📦 Format & Ses")
        card_format.pack(fill="x", pady=(0, 10))
        ReadOnlyComboBox(card_format, variable=tab_vars["container"], values=["webm", "mkv"]).pack(fill="x", padx=15, pady=(0, 5))
        ctk.CTkLabel(card_format, text="* VP9 için WebM standarttır (Audio: Opus)", font=("Arial", 10, "italic"), text_color="gray").pack(anchor="w", padx=15, pady=(0, 5))
        ReadOnlyComboBox(card_format, variable=tab_vars["audio_bitrate"], values=self.VP9_AUDIO_VALUES).pack(fill="x", padx=15, pady=(5, 15))

        card_vp9 = self.create_card(col_left, "🧠 VP9 İşlemci Motoru (CPU)")
        card_vp9.pack(fill="x", pady=10)

        ctk.CTkLabel(card_vp9, text="-quality (Genel Kalite):").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_vp9, variable=tab_vars["vp9_quality"], values=["good (Önerilen)", "best (Aşırı Yavaş)", "realtime"]).pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(card_vp9, text="-speed (0 Yavaş - 5 Hızlı):").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_vp9, variable=tab_vars["vp9_speed"], values=["0 (Maksimum Kalite)", "1 (VOD Önerisi)", "2 (Standart)", "3 (Hızlı)", "4", "5 (En Hızlı)"]).pack(fill="x", padx=15, pady=(0, 10))

        lbl_cq_title = ctk.CTkLabel(card_vp9, text=f"Google VOD CQ: {tab_vars['cq'].get()}", font=("Arial", 13, "bold"))
        lbl_cq_status = ctk.CTkLabel(card_vp9, text="", font=("Arial", 11, "italic"))

        lbl_cq_title.pack(anchor="w", padx=15, pady=(5, 0))
        lbl_cq_status.pack(anchor="w", padx=15, pady=(0, 5))

        slider_cq = ctk.CTkSlider(card_vp9, from_=0, to=63, number_of_steps=63, variable=tab_vars["cq"], command=on_cq_change_vp9)
        slider_cq.pack(fill="x", padx=15, pady=(0, 15))

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 Çözünürlük & İş Parçacığı")
        card_res.pack(fill="x", pady=(0, 10))

        cb_scale = ReadOnlyComboBox(card_res, variable=tab_vars["scale"], values=["Orijinal", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K"], command=on_vp9_scale_change)
        cb_scale.pack(fill="x", padx=15, pady=(10, 15))

        ctk.CTkLabel(card_res, text="-tile-columns (Bölme):").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_res, variable=tab_vars["vp9_tiles"], values=["0 (Tek Sütun)", "1 (Düşük Çöz. için)", "2 (1080p için)", "3 (4K/1440p için)", "4 (8K)"]).pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(card_res, text="-threads (CPU Çekirdek Kullanımı):").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_res, variable=tab_vars["vp9_threads"], values=["Auto", "2", "4", "8", "16", "32"]).pack(fill="x", padx=15, pady=(0, 10))
        self._add_toggle(card_res, "Kaynaktan büyütme yapma", tab_vars["no_upscale"],
                         "Hedef çözünürlük kaynaktan büyükse ölçekleme atlanır; "
                         "büyütmek kalite katmaz, sadece dosyayı şişirir.", son=True)

        on_cq_change_vp9()
        self.cq_refreshers[tab_name] = on_cq_change_vp9

        self._create_metadata_card(col_right, tab_vars)

    # =======================================================
    # STANDART SEKMELER
    # =======================================================
    def create_tab(self, tab_name, codec_name):
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        is_av1 = codec_name == "av1_nvenc"
        # Tabloyla elle senkron tutulan kopya deger yerine tek kaynaktan okunur.
        tab_vars = self._nvenc_tab_vars("mkv" if is_av1 else "mp4",
                                        get_cq_default(codec_name, "Orijinal"))
        tab_vars["codec"] = codec_name
        # Sekme ozellikleri isim icinde metin aramak yerine burada saklanir;
        # boylece sekme adi degistirildiginde mantik sessizce bozulmaz.
        tab_vars.update(self._tab_meta(is_pure_cuda=False, is_vp9=False, accent=(
            ("#1f538d", "#14375e", "white") if is_av1 else
            ("#2fa572", "#1e6b4a", "white") if codec_name == "hevc_nvenc" else
            ("#c0392b", "#922b21", "white"))))
        self.tabs[tab_name] = tab_vars

        main_grid = ctk.CTkFrame(frame, fg_color="transparent")
        main_grid.pack(fill="both", expand=True)
        main_grid.columnconfigure(0, weight=1)
        main_grid.columnconfigure(1, weight=1)

        col_left = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_left.grid(row=0, column=0, sticky="nsew", padx=5)

        def on_cq_change(*args):
            self._update_cq_display(codec_name, tab_vars, lbl_cq_title, lbl_cq_status, slider_cq)

        def on_scale_change(choice):
            self._auto_set_cq(codec_name, choice, tab_vars, slider_cq, lbl_cq_title, lbl_cq_status)

        if is_av1:
            card_format = self.create_card(col_left, "📦 Format Konteyner")
            card_format.pack(fill="x", pady=(0, 10))
            ReadOnlyComboBox(card_format, variable=tab_vars["container"], values=["mkv", "mp4"]).pack(fill="x", padx=15, pady=(0, 5))
            ctk.CTkLabel(card_format, text="* MKV: libopus | MP4: aac", font=("Arial", 10, "italic"), text_color="gray").pack(anchor="w", padx=15, pady=(0, 10))

        self._create_audio_card(col_left, tab_vars, pady=(0 if is_av1 else 10, 10))
        lbl_cq_title, lbl_cq_status, slider_cq = self._create_nvenc_card(
            col_left, tab_vars, "⚙️ Nvenc Motoru", on_cq_change)

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 Çözünürlük")
        card_res.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_res, text="Akıllı Ölçeklendirme (Lanczos):").pack(anchor="w", padx=15)

        cb_scale = ReadOnlyComboBox(card_res, variable=tab_vars["scale"], values=self.SCALE_VALUES, command=on_scale_change)
        cb_scale.pack(fill="x", padx=15, pady=(0, 15))

        on_cq_change()
        self.cq_refreshers[tab_name] = on_cq_change

        self._create_metadata_card(col_right, tab_vars)
        # Salterler sekmenin ALTINDA, iki sutuna yayilarak: sag sutunda dikey
        # dizildiginde sekme yuksekligini tek basina belirliyordu.
        kart_salter = self._create_toggles_card(main_grid, tab_vars, "🛠️ Kontrol Şalterleri",
                                                "Taraklanmayı Gider (bwdif)")
        kart_salter.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=(10, 0))

    # =======================================================
    # AMD (AMF) SEKMELERİ
    # =======================================================
    def create_amd_tab(self, tab_name, codec_name):
        """
        AMD donanim kodlayicisi sekmesi. Yapisi NVENC sekmeleriyle ayni tutuldu
        (kuyruk, klasor modu, altyazi, metadata hepsi ortak calissin diye);
        farkli olan yalnizca kodlayici kartinin icerigidir:
            NVENC: -preset p1..p7 + -cq:v
            AMF  : -quality quality/balanced/speed + -qp_i/-qp_p
        """
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        is_av1 = codec_name == "av1_amf"
        tab_vars = self._nvenc_tab_vars("mkv" if is_av1 else "mp4",
                                        get_cq_default(codec_name, "Orijinal"))
        tab_vars["codec"] = codec_name
        # NVENC'e ozel salterler AMF'de yok; kart kurulurken sorulmasin diye
        # degiskenleri birakiyoruz ama komuta girmiyorlar (bkz. build_command).
        tab_vars["amf_quality"] = ctk.StringVar(value="quality")
        tab_vars["cozucu"] = ctk.StringVar(value=list(COZUCU_SECENEKLERI)[0])
        tab_vars.update(self._tab_meta(is_pure_cuda=False, is_vp9=False,
                                       accent=("#c0392b", "#922b21", "white")))
        self.tabs[tab_name] = tab_vars

        main_grid = ctk.CTkFrame(frame, fg_color="transparent")
        main_grid.pack(fill="both", expand=True)
        main_grid.columnconfigure(0, weight=1)
        main_grid.columnconfigure(1, weight=1)

        col_left = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_left.grid(row=0, column=0, sticky="nsew", padx=5)

        def on_cq_change(*args):
            self._update_cq_display(codec_name, tab_vars, lbl_cq_title,
                                    lbl_cq_status, slider_cq, "QP (Kalite)")

        card_format = self.create_card(col_left, "📦 Format Konteyner")
        card_format.pack(fill="x", pady=(0, 10))
        ReadOnlyComboBox(card_format, variable=tab_vars["container"],
                         values=["mkv", "mp4"]).pack(fill="x", padx=15, pady=(0, 10))

        self._create_audio_card(col_left, tab_vars, pady=(0, 10))

        card_amf = self.create_card(col_left, "🔴 AMD Motoru (AMF)")
        card_amf.pack(fill="x", pady=10)
        ctk.CTkLabel(card_amf, text="Kalite Ön Ayarı:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_amf, variable=tab_vars["amf_quality"],
                         values=AMF_QUALITY_VALUES).pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(card_amf, text="Kod çözücü (decoder):").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_amf, variable=tab_vars["cozucu"],
                         values=list(COZUCU_SECENEKLERI)).pack(fill="x", padx=15, pady=(0, 5))
        ctk.CTkLabel(card_amf,
                     text="Otomatik: AV1 kaynakta yazılım, diğerlerinde GPU.\n"
                          "Donanım CPU'yu rahatlatır ama ölçümde AV1'de %25 yavaştı;\n"
                          "yazılım hızlıdır ama işlemciyi çalıştırır.",
                     font=("Arial", 10, "italic"), text_color="gray",
                     justify="left", anchor="w").pack(anchor="w", padx=15, pady=(0, 12))

        lbl_cq_title = ctk.CTkLabel(card_amf, text=f"QP (Kalite): {tab_vars['cq'].get()}",
                                    font=("Arial", 13, "bold"))
        lbl_cq_status = ctk.CTkLabel(card_amf, text="", font=("Arial", 11, "italic"))
        lbl_cq_title.pack(anchor="w", padx=15, pady=(5, 0))
        lbl_cq_status.pack(anchor="w", padx=15, pady=(0, 5))
        # Kaydiricinin ust siniri KODEGE gore: av1_amf 0-255, digerleri 0-51.
        # Hepsini 51'de tutmak AV1'i kullanilamaz yapiyordu (bkz. AMF_QP_TAVANI).
        tavan = amf_qp_tavani(codec_name)
        slider_cq = ctk.CTkSlider(card_amf, from_=0, to=tavan, number_of_steps=tavan,
                                  variable=tab_vars["cq"], command=on_cq_change)
        slider_cq.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkLabel(card_amf,
                     text=f"* Bu kodlayıcının QP ölçeği 0-{tavan}. Düşük = büyük dosya.",
                     font=("Arial", 10, "italic"), text_color="gray",
                     anchor="w").pack(anchor="w", padx=15, pady=(0, 10))

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 Çözünürlük")
        card_res.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_res, text="Akıllı Ölçeklendirme (Lanczos):").pack(anchor="w", padx=15)

        def on_scale_change(secim):
            # Cozunurluk degisince QP'yi o cozunurlugun olculen ortasina cek -
            # NVENC sekmeleriyle ayni davranis.
            self._auto_set_cq(codec_name, secim, tab_vars, slider_cq,
                              lbl_cq_title, lbl_cq_status, "QP (Kalite)")

        ReadOnlyComboBox(card_res, variable=tab_vars["scale"], values=self.SCALE_VALUES,
                         command=on_scale_change).pack(fill="x", padx=15, pady=(0, 15))

        on_cq_change()
        self.cq_refreshers[tab_name] = on_cq_change

        self._create_metadata_card(col_right, tab_vars)

        # NVENC'e ozgu salterler (temporal-aq, multipass, b_ref_mode) AMF'de
        # karsiliksiz; yalnizca gercekten uygulanabilenler gosteriliyor.
        kart_salter = self.create_card(main_grid, "🛠️ Kontrol Şalterleri")
        kafes = ctk.CTkFrame(kart_salter, fg_color="transparent")
        kafes.pack(fill="x", padx=10, pady=(0, 10))
        for i in range(3):
            kafes.grid_columnconfigure(i, weight=1, uniform="salter")
        for sira, (metin, degisken, aciklama) in enumerate([
            ("Taraklanmayı Gider (bwdif)", tab_vars["bwdif"],
             "Tarak izlerini giderir (CPU'da çalışır)."),
            ("Kaynaktan büyütme yapma", tab_vars["no_upscale"],
             "Büyütme yapmaz, biti boşa harcamaz."),
            ("10-bit kodla (Main 10)", tab_vars["ten_bit"],
             "Bantlanmayı azaltır; kapalıysa uyum artar."),
        ]):
            hucre = ctk.CTkFrame(kafes, fg_color="transparent")
            hucre.grid(row=0, column=sira, sticky="nsew", padx=4, pady=(4, 2))
            ctk.CTkCheckBox(hucre, text=metin, variable=degisken).pack(anchor="w")
            ctk.CTkLabel(hucre, text=aciklama, font=("Arial", 10, "italic"),
                         text_color="#8A8A8A", justify="left", anchor="w",
                         height=16, wraplength=260).pack(anchor="w", padx=(26, 0), pady=(1, 0))
        kart_salter.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=(10, 0))

    # =======================================================
    # SAF CUDA SEKMESİ
    # =======================================================
    def create_tamgpu_tab(self, tab_name):
        """
        TAM GPU (AMF) sekmesi: cozme, olcekleme ve kodlama GPU'da kalir, kare
        hic sistem bellegine inmez.

        Neden ayri sekme: bu hatta altyazi gomme, renk filtresi ve taraklanma
        giderme CALISAMIYOR. Eskiden bu bir "kod cozucu" secenegiydi ve
        secildiginde bu ozellikler sessizce atlaniyordu - kullanici altyazi
        secip uzun bir kodlamadan sonra altyazisiz dosya buluyordu. Burada o
        secenekler HIC GOSTERILMIYOR; yalnizca olculerek calistigi dogrulanan
        yetenekler var (bkz. AMF_SR_YALNIZ_CALISIR olcumu).
        """
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        tab_vars = self._nvenc_tab_vars("mkv", get_cq_default("av1_amf", "Orijinal"))
        tab_vars["selected_codec"] = ctk.StringVar(value="AV1 (av1_amf)")
        tab_vars["amf_quality"] = ctk.StringVar(value="quality")
        # Paylasilan degisken setinde "kaynaktan buyutme yapma" ACIK gelir ve
        # bu sekmede o salter YOK. Acik birakilirsa buyutme sessizce iptal
        # olur; HQ buyutme ozelligi de zaten buyutme demek oldugu icin
        # tamamen olu kalirdi (olculdu: sr_amf hic komuta girmiyordu).
        tab_vars["no_upscale"].set(False)
        tab_vars["amf_sr"] = ctk.BooleanVar(value=False)
        tab_vars["amf_sr_algo"] = ctk.StringVar(value=list(AMF_SR_ALGORITMALARI)[0])
        tab_vars["amf_frc"] = ctk.BooleanVar(value=False)
        tab_vars.update(self._tab_meta(is_pure_cuda=False, is_vp9=False,
                                       accent=("#c0392b", "#922b21", "white"),
                                       supports_subs=False, is_tamgpu=True))
        self.tabs[tab_name] = tab_vars

        main_grid = ctk.CTkFrame(frame, fg_color="transparent")
        main_grid.pack(fill="both", expand=True)
        main_grid.columnconfigure(0, weight=1)
        main_grid.columnconfigure(1, weight=1)
        col_left = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_left.grid(row=0, column=0, sticky="nsew", padx=5)

        def secili_kodek():
            return tab_vars["selected_codec"].get().split("(")[1].split(")")[0]

        # En son uygulanan QP tavani; her kaydirici hareketinde widget'i
        # yeniden yapilandirmamak icin tutuluyor.
        son_tavan = {"deger": None}

        def tavani_uygula(kodek):
            """
            QP olcegini KODEGE uydurur (av1_amf 0-255, digerleri 0-51) ve
            eldeki deger tavanin ustundeyse gecerli bir degere ceker.

            OLCULDU, bu kontrol olmadan gercek bir kusur cikiyor: ayarlar geri
            yuklenirken kodek H.265 olarak gelse bile kaydirici AV1 icin
            kurulmus 0-255 olceginde kaliyor; oradan secilen QP ffmpeg'e
            gidince "Error opening output files: Result too large" ile
            duruyor - kullanicinin anlamasi imkansiz bir mesaj.
            """
            tavan = amf_qp_tavani(kodek)
            if son_tavan["deger"] != tavan:
                slider_cq.configure(to=tavan, number_of_steps=tavan)
                lbl_olcek.configure(text=f"* Bu kodlayıcının QP ölçeği 0-{tavan}. "
                                         "Düşük = büyük dosya.")
                son_tavan["deger"] = tavan
            if int(float(tab_vars["cq"].get())) > tavan:
                yeni = get_cq_default(kodek, tab_vars["scale"].get(),
                                      self._kaynak_boyut_cq())
                tab_vars["cq_auto"] = yeni
                tab_vars["cq"].set(yeni)
                slider_cq.set(yeni)

        def on_cq_change(*args):
            kodek = secili_kodek()
            tavani_uygula(kodek)
            self._update_cq_display(kodek, tab_vars, lbl_cq_title,
                                    lbl_cq_status, slider_cq, "QP (Kalite)")

        card_codec = self.create_card(col_left, "🔴 Donanım Motoru (AMF, kopyasız)")
        card_codec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_codec, text="Kodlayıcı:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_codec, variable=tab_vars["selected_codec"],
                         values=[f"{ad.split(' ')[0]} ({kod})"
                                 for kod, ad in AMF_SEKME_ADI.items()],
                         command=lambda secim: on_kodek_degisti(secim)
                         ).pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(card_codec, text="Konteyner:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_codec, variable=tab_vars["container"],
                         values=["mkv", "mp4"]).pack(fill="x", padx=15, pady=(0, 15))

        self._create_audio_card(col_left, tab_vars, pady=10)

        card_amf = self.create_card(col_left, "⚙️ AMF Ön Ayarları")
        card_amf.pack(fill="x", pady=10)
        ctk.CTkLabel(card_amf, text="Kalite Ön Ayarı:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_amf, variable=tab_vars["amf_quality"],
                         values=AMF_QUALITY_VALUES).pack(fill="x", padx=15, pady=(0, 10))
        lbl_cq_title = ctk.CTkLabel(card_amf, text="QP (Kalite):", font=("Arial", 13, "bold"))
        lbl_cq_status = ctk.CTkLabel(card_amf, text="", font=("Arial", 11, "italic"))
        lbl_cq_title.pack(anchor="w", padx=15, pady=(5, 0))
        lbl_cq_status.pack(anchor="w", padx=15, pady=(0, 5))
        tavan = amf_qp_tavani("av1_amf")
        slider_cq = ctk.CTkSlider(card_amf, from_=0, to=tavan, number_of_steps=tavan,
                                  variable=tab_vars["cq"], command=on_cq_change)
        slider_cq.pack(fill="x", padx=15, pady=(0, 5))
        lbl_olcek = ctk.CTkLabel(card_amf, text="", font=("Arial", 10, "italic"),
                                 text_color="gray", anchor="w")
        lbl_olcek.pack(anchor="w", padx=15, pady=(0, 10))

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 Çözünürlük (GPU'da)")
        card_res.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_res, text="Ölçekleme:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_res, variable=tab_vars["scale"], values=self.SCALE_VALUES,
                         command=lambda secim: self._auto_set_cq(
                             secili_kodek(), secim, tab_vars, slider_cq,
                             lbl_cq_title, lbl_cq_status, "QP (Kalite)")
                         ).pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(card_res, text="HQ büyütme algoritması:").pack(anchor="w", padx=15)
        cb_sr_algo = ReadOnlyComboBox(card_res, variable=tab_vars["amf_sr_algo"],
                                      values=list(AMF_SR_ALGORITMALARI))
        cb_sr_algo.pack(fill="x", padx=15, pady=(0, 15))

        self._create_metadata_card(col_right, tab_vars)

        kart_salter = self.create_card(main_grid, "🛠️ TAM GPU Seçenekleri")
        kafes = ctk.CTkFrame(kart_salter, fg_color="transparent")
        kafes.pack(fill="x", padx=10, pady=(0, 10))
        for i in range(3):
            kafes.grid_columnconfigure(i, weight=1, uniform="salter")

        def on_hq_degisti():
            """
            HQ buyutme acikken 10-bit ve kare katlama KAPATILIR.
            Olculdu: sr_amf baska bir AMF filtresiyle birlesince 6 kosuda 1
            cokuyor, ucu bir arada ise ffmpeg tamamen kilitleniyor. Salterleri
            acik birakip sessizce atlamak yerine gorunur bicimde kapatiyoruz.
            """
            hq = tab_vars["amf_sr"].get()
            for cb in (cb_10bit, cb_frc):
                cb.configure(state="disabled" if hq else "normal")
            if hq:
                tab_vars["ten_bit"].set(False)
                tab_vars["amf_frc"].set(False)
            lbl_hq_not.configure(
                text=("HQ büyütme açık: 10-bit ve kare katlama kullanılamaz "
                      "(ölçüldü, birlikte kilitleniyor)." if hq else ""))

        for sira, (metin, degisken, aciklama, komut) in enumerate([
            ("HQ büyütme (AMD sr_amf)", tab_vars["amf_sr"],
             "Donanımsal super-resolution. Yalnız çalışır.", on_hq_degisti),
            ("10-bit kodla (vpp_amf)", tab_vars["ten_bit"],
             "Bantlanmayı azaltır. Bu hatta 10-bit sadece böyle alınır.", None),
            ("Kare hızını 2 katına çıkar", tab_vars["amf_frc"],
             "Hareket interpolasyonu (30->60). Dosya büyür.", None),
        ]):
            hucre = ctk.CTkFrame(kafes, fg_color="transparent")
            hucre.grid(row=0, column=sira, sticky="nsew", padx=4, pady=(4, 2))
            cb = ctk.CTkCheckBox(hucre, text=metin, variable=degisken,
                                 command=komut) if komut else \
                 ctk.CTkCheckBox(hucre, text=metin, variable=degisken)
            cb.pack(anchor="w")
            ctk.CTkLabel(hucre, text=aciklama, font=("Arial", 10, "italic"),
                         text_color="#8A8A8A", justify="left", anchor="w",
                         height=16, wraplength=260).pack(anchor="w", padx=(26, 0), pady=(1, 0))
            if sira == 1:
                cb_10bit = cb
            elif sira == 2:
                cb_frc = cb
        lbl_hq_not = ctk.CTkLabel(kart_salter, text="", font=("Arial", 10, "italic"),
                                  text_color="#FFA500", anchor="w")
        lbl_hq_not.pack(anchor="w", padx=15, pady=(0, 8))
        ctk.CTkLabel(kart_salter,
                     text="Bu sekmede altyazı gömme, renk filtresi ve taraklanma "
                          "giderme YOKTUR: kare GPU'da kaldığı için bunların AMF "
                          "karşılığı yok. Gerekiyorsa AV1/H.265/H.264 (AMD) "
                          "sekmelerini kullanın. Seçtiğiniz çözünürlük kaynaktan "
                          "büyükse burada BÜYÜTÜLÜR (büyütme koruması yok; HQ "
                          "büyütme zaten bunun için).",
                     font=("Arial", 10, "italic"), text_color="#8A8A8A",
                     justify="left", anchor="w", wraplength=760).pack(anchor="w", padx=15, pady=(0, 10))

        def on_kodek_degisti(secim):
            kodek = secim.split("(")[1].split(")")[0]
            tavani_uygula(kodek)
            tab_vars["container"].set("mkv" if kodek == "av1_amf" else "mp4")
            # Kodek degisince QP'yi o kodegin olculen bandina cek: olcekler
            # birbirine cevrilemez (AV1'de 144 iyi kalite, H.265'te gecersiz).
            self._auto_set_cq(kodek, tab_vars["scale"].get(), tab_vars, slider_cq,
                              lbl_cq_title, lbl_cq_status, "QP (Kalite)")

        on_kodek_degisti(tab_vars["selected_codec"].get())
        on_hq_degisti()
        self.cq_refreshers[tab_name] = on_cq_change

    def create_cuda_tab(self, tab_name):
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        tab_vars = self._nvenc_tab_vars("mkv", get_cq_default("av1_nvenc", "Orijinal"))
        tab_vars["selected_codec"] = ctk.StringVar(value="AV1 (av1_nvenc)")
        # "Otomatik" = scale_cuda varsayilani (bicubic). Olcumlerimde hicbir
        # algoritma digerine belirgin ustunluk kurmadigi icin varsayilan
        # bilerek degistirilmedi; secim kullaniciya birakildi.
        tab_vars["interp_algo"] = ctk.StringVar(value="Otomatik")
        tab_vars.update(self._tab_meta(is_pure_cuda=True, is_vp9=False,
                                       accent=("#76b900", "#5a8d00", "black"),
                                       supports_subs=False))
        self.tabs[tab_name] = tab_vars

        main_grid = ctk.CTkFrame(frame, fg_color="transparent")
        main_grid.pack(fill="both", expand=True)
        main_grid.columnconfigure(0, weight=1)
        main_grid.columnconfigure(1, weight=1)

        col_left = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_left.grid(row=0, column=0, sticky="nsew", padx=5)

        def _get_cuda_codec():
            codec_full = tab_vars["selected_codec"].get()
            return codec_full.split("(")[1].split(")")[0]

        def on_cq_change(*args):
            codec = _get_cuda_codec()
            self._update_cq_display(codec, tab_vars, lbl_cq_title, lbl_cq_status, slider_cq)

        def on_cuda_scale_change(choice):
            codec = _get_cuda_codec()
            self._auto_set_cq(codec, choice, tab_vars, slider_cq, lbl_cq_title, lbl_cq_status)

        def on_cuda_codec_change(choice):
            # Etiket metninde arama yapmak yerine zaten ayristirilan codec adi kullanilir.
            codec = choice.split("(")[1].split(")")[0]
            tab_vars["container"].set("mkv" if codec == "av1_nvenc" else "mp4")
            self._auto_set_cq(codec, tab_vars["scale"].get(), tab_vars, slider_cq, lbl_cq_title, lbl_cq_status)

        card_codec = self.create_card(col_left, "🚀 Donanım Motoru (VRAM)")
        card_codec.pack(fill="x", pady=(0, 10))
        cb_codec = ReadOnlyComboBox(card_codec, variable=tab_vars["selected_codec"], values=["AV1 (av1_nvenc)", "H.265 (hevc_nvenc)", "H.264 (h264_nvenc)"], command=on_cuda_codec_change)
        cb_codec.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(card_codec, text="Konteyner:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_codec, variable=tab_vars["container"], values=["mp4", "mkv"]).pack(fill="x", padx=15, pady=(0, 15))

        self._create_audio_card(col_left, tab_vars, pady=10)
        lbl_cq_title, lbl_cq_status, slider_cq = self._create_nvenc_card(
            col_left, tab_vars, "⚙️ Nvenc Ön Ayarları", on_cq_change)

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 CUDA Çözünürlük (scale_cuda)")
        card_res.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_res, text="Donanımsal GPU Ölçekleme:").pack(anchor="w", padx=15)

        cb_scale = ReadOnlyComboBox(card_res, variable=tab_vars["scale"], values=self.SCALE_VALUES, command=on_cuda_scale_change)
        cb_scale.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(card_res, text="Ölçekleme Algoritması:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_res, variable=tab_vars["interp_algo"],
                         values=["Otomatik", "bilinear", "bicubic", "lanczos"]).pack(fill="x", padx=15, pady=(0, 15))

        on_cq_change()
        self.cq_refreshers[tab_name] = on_cq_change

        self._create_metadata_card(col_right, tab_vars)

        kart_salter = self._create_toggles_card(main_grid, tab_vars, "🛠️ CUDA Kontrol Şalterleri",
                                                "Donanımsal Tarak Giderici (yadif_cuda)", cuda=True)
        kart_salter.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=(10, 0))

    # =======================================================
    # SADECE ALTYAZI SEKMESİ (KODEK KORUNUR)
    # =======================================================
    def create_remux_tab(self, tab_name):
        """
        Kodlama yapmayan sekme: video ve ses akislari kopyalanir, yalnizca
        secilen altyazi dosyasi yeni bir iz olarak eklenir. Kodlayici ayari
        (CQ, preset, cozunurluk, ses bitrate) bu sekmede BILEREK yoktur -
        hicbiri kullanilmiyor, gostermek yanlis beklenti yaratirdi.
        """
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        tab_vars = {
            "codec": "copy",
            "container": ctk.StringVar(value="mkv"),
            "sub_lang": ctk.StringVar(value="Türkçe (tur)"),
            "sub_charenc": ctk.StringVar(value=list(SUB_CHARENC_SECENEKLERI)[0]),
            "sub_default": ctk.BooleanVar(value=True),
            "keep_subs": ctk.BooleanVar(value=True),
            "metadata_title": ctk.StringVar(value=""),
            "metadata_artist": ctk.StringVar(value=""),
            "metadata_album": ctk.StringVar(value=""),
            "metadata_grouping": ctk.StringVar(value=""),
        }
        tab_vars.update(self._tab_meta(is_pure_cuda=False, is_vp9=False,
                                       accent=("#d68910", "#a9690a", "black"),
                                       is_remux=True))
        self.tabs[tab_name] = tab_vars

        main_grid = ctk.CTkFrame(frame, fg_color="transparent")
        main_grid.pack(fill="both", expand=True)
        main_grid.columnconfigure(0, weight=1)
        main_grid.columnconfigure(1, weight=1)

        col_left = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_left.grid(row=0, column=0, sticky="nsew", padx=5)

        card_bilgi = self.create_card(col_left, "⚡ Yeniden Kodlama Yok")
        card_bilgi.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            card_bilgi,
            text="Video ve ses akışları olduğu gibi kopyalanır; kaynağın\n"
                 "kodek'i ve kalitesi birebir korunur. Sadece altyazı izi\n"
                 "eklenir, bu yüzden işlem saniyeler sürer.",
            font=("Arial", 11), text_color="#AAAAAA", justify="left", anchor="w"
        ).pack(anchor="w", padx=15, pady=(0, 12))

        card_format = self.create_card(col_left, "📦 Çıkış Konteyneri")
        card_format.pack(fill="x", pady=(0, 10))
        ReadOnlyComboBox(card_format, variable=tab_vars["container"],
                         values=["mkv", "mp4"]).pack(fill="x", padx=15, pady=(0, 5))
        ctk.CTkLabel(card_format,
                     text="* MKV her kodek'i ve her altyazı türünü alır (önerilen).\n"
                          "* MP4 altyazıyı mov_text'e çevirmek zorundadır: stil\n"
                          "  bilgisi korunmaz, resim tabanlı izler taşınamaz.",
                     font=("Arial", 10, "italic"), text_color="gray",
                     justify="left", anchor="w").pack(anchor="w", padx=15, pady=(0, 12))

        card_kod = self.create_card(col_left, "🔤 Altyazı Karakter Kodlaması")
        card_kod.pack(fill="x", pady=(0, 10))
        ReadOnlyComboBox(card_kod, variable=tab_vars["sub_charenc"],
                         values=list(SUB_CHARENC_SECENEKLERI)).pack(fill="x", padx=15, pady=(0, 5))
        ctk.CTkLabel(card_kod,
                     text="Otomatik: dosya UTF-8 ise olduğu gibi kopyalanır,\n"
                          "değilse Windows-1254 varsayılıp UTF-8'e çevrilir.\n"
                          "Türkçe harfler bozuk çıkarsa buradan zorlayın.",
                     font=("Arial", 10, "italic"), text_color="gray",
                     justify="left", anchor="w").pack(anchor="w", padx=15, pady=(0, 12))

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_iz = self.create_card(col_right, "💬 Altyazı İzi")
        card_iz.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_iz, text="Dil etiketi:").pack(anchor="w", padx=15)
        ReadOnlyComboBox(card_iz, variable=tab_vars["sub_lang"],
                         values=list(SUB_DIL_SECENEKLERI)).pack(fill="x", padx=15, pady=(0, 10))
        self._add_toggle(card_iz, "Varsayılan altyazı yap", tab_vars["sub_default"],
                         "Oynatıcı açılışta bu izi seçer; kaynaktaki eski "
                         "varsayılan işareti kaldırılır.")
        self._add_toggle(card_iz, "Kaynaktaki altyazı izlerini koru", tab_vars["keep_subs"],
                         "Kapatılırsa videoda gömülü olan altyazılar atılır, "
                         "yalnızca eklediğiniz dosya kalır.", son=True)

        self._create_metadata_card(col_right, tab_vars)

    def select_video(self):
        path = filedialog.askopenfilename(
            title="Dönüştürülecek Videoyu Seçin",
            initialdir=self.last_video_dir or None,
            filetypes=[("Tüm Video Dosyaları", " ".join("*" + e for e in VIDEO_EXTS)), ("Tüm Dosyalar", "*.*")]
        )
        if path:
            self.last_video_dir = os.path.dirname(path)
            self.video_path.set(path)
            self.log(f"Video Seçildi: {os.path.basename(path)}")

    def select_sub(self):
        path = filedialog.askopenfilename(
            initialdir=self.last_sub_dir or None,
            filetypes=[("Altyazı Dosyası", " ".join("*" + e for e in SUB_EXTS))])
        if path:
            self.last_sub_dir = os.path.dirname(path)
            self.sub_path.set(path)
            self._refresh_sub_button()
            self.log(f"Altyazı Eklendi: {os.path.basename(path)}")

    # =======================================================
    # KUYRUK
    # =======================================================
    def _refresh_queue_view(self):
        self.txt_queue.configure(state="normal")
        self.txt_queue.delete("1.0", tk.END)
        for i, job in enumerate(self.job_queue, 1):
            if job.get("is_remux"):
                self.txt_queue.insert(tk.END, "%2d. %-38s  ALTYAZI %s -> %s\n" % (
                    i, os.path.basename(job["input_file"])[:38],
                    os.path.basename(job["sub_file"])[:20], job["container"]))
                continue
            etiket = "VP9" if job["is_vp9"] else job["codec_v"].split("_")[0].upper()
            self.txt_queue.insert(tk.END, "%2d. %-38s  %s %s CQ%s -> %s\n" % (
                i, os.path.basename(job["input_file"])[:38], etiket,
                job["scale"], job["cq_val"], job["container"]))
        self.txt_queue.configure(state="disabled")
        if self.job_queue:
            self.lbl_queue.configure(
                text=f"{len(self.job_queue)} iş kuyrukta — 'Dönüştür' hepsini sırayla çalıştırır.",
                text_color="#00FF00")
        else:
            self.lbl_queue.configure(
                text="Kuyruk boş — 'Dönüştür' mevcut ayarları hemen çalıştırır.",
                text_color="#AAAAAA")

    def add_to_queue(self):
        if self.current_process is not None:
            messagebox.showinfo("Kuyruk", "Dönüştürme sürerken kuyruğa ekleyebilirsiniz, "
                                          "ancak mevcut çalışma bittikten sonra işlenir.")
        job = self._prepare_job()
        if job is None:
            return
        self.job_queue.append(job)
        self._refresh_queue_view()
        self.log(f"➕ Kuyruğa eklendi ({len(self.job_queue)}): {os.path.basename(job['output_file'])}")

    # =======================================================
    # KLASORDEKI TUM VIDEOLAR (TOPLU EKLEME)
    # =======================================================
    def _klasordeki_videolar(self, klasor, alt_klasorler):
        """Klasordeki video dosyalarini alfabetik sirali dondurur."""
        bulunan = []
        if alt_klasorler:
            for kok, _, dosyalar in os.walk(klasor):
                for d in dosyalar:
                    if os.path.splitext(d)[1].lower() in VIDEO_EXTS:
                        bulunan.append(os.path.join(kok, d))
        else:
            try:
                for d in os.listdir(klasor):
                    tam = os.path.join(klasor, d)
                    if os.path.isfile(tam) and os.path.splitext(d)[1].lower() in VIDEO_EXTS:
                        bulunan.append(tam)
            except OSError:
                return []
        return sorted(bulunan)

    def _alt_klasorde_video_var_mi(self, klasor):
        """Alt klasorleri sormaya deger mi? (bos yere soru sormamak icin)"""
        try:
            for kok, _, dosyalar in os.walk(klasor):
                if os.path.normpath(kok) == os.path.normpath(klasor):
                    continue
                if any(os.path.splitext(d)[1].lower() in VIDEO_EXTS for d in dosyalar):
                    return True
        except OSError:
            pass
        return False

    def _eslesen_altyazi(self, video_yolu):
        """
        Videonun YANINDAKI ayni adli altyaziyi bulur.

        Klasor modunda tek bir altyaziyi 50 videoya takmak sacma olurdu; her
        video kendi altyazisiyla eslesir:
            Film.mkv -> Film.srt, Film.tr.srt, Film.tur.srt, Film.eng.ass ...
        Turkce sonekli olanlar once denenir (kullanicinin varsayilan dili).
        """
        kok = os.path.splitext(video_yolu)[0]
        klasor = os.path.dirname(video_yolu) or "."
        taban = os.path.basename(kok).lower()

        # 1) Birebir ayni ad
        for uzanti in SUB_EXTS:
            aday = kok + uzanti
            if os.path.isfile(aday):
                return aday

        # 2) Dil sonekli adlar: "Film.tr.srt" gibi
        try:
            adaylar = [d for d in os.listdir(klasor)
                       if os.path.splitext(d)[1].lower() in SUB_EXTS
                       and d.lower().startswith(taban + ".")]
        except OSError:
            return ""
        if not adaylar:
            return ""

        def oncelik(ad):
            orta = ad.lower()[len(taban) + 1:].rsplit(".", 1)[0]
            return (0 if orta in ("tr", "tur", "turkce", "türkçe") else 1, ad.lower())

        return os.path.join(klasor, sorted(adaylar, key=oncelik)[0])

    def select_folder(self):
        """
        Bir klasordeki TUM videolari, o an secili sekme ayarlariyla kuyruga ekler.

        Ayarlar bir kez okunur ve her dosyaya aynen uygulanir; tek fark girdi
        dosyasi ve (altyazi destekleyen sekmelerde) o videoyla eslesen altyazidir.
        """
        klasor = filedialog.askdirectory(
            title="Videoların bulunduğu klasörü seçin",
            initialdir=self.last_video_dir or None)
        if not klasor:
            return

        alt_klasorler = False
        if self._alt_klasorde_video_var_mi(klasor):
            alt_klasorler = messagebox.askyesno(
                "Alt Klasörler",
                "Alt klasörlerde de video var.\n\nOnlar da eklensin mi?\n\n"
                "Evet: alt klasörler dahil\nHayır: yalnızca bu klasör")

        videolar = self._klasordeki_videolar(klasor, alt_klasorler)
        if not videolar:
            messagebox.showinfo("Video Bulunamadı",
                                f"Seçilen klasörde desteklenen video yok:\n{klasor}")
            return

        self.last_video_dir = klasor
        tab_vars = self.tabs.get(self.tabview.get(), {})
        altyazi_destegi = tab_vars.get("supports_subs", True)
        is_remux = tab_vars.get("is_remux", False)

        self.log(f"📁 {len(videolar)} video taranıyor: {klasor}")
        self.update_idletasks()

        # Altyazi eslestirmesi ONCE yapilir (ucuz, diske tek bakis) - cunku
        # sonucu kullaniciya sormamiz gerekebiliyor.
        eslesmeler = {v: (self._eslesen_altyazi(v) if altyazi_destegi else "")
                      for v in videolar}
        eslesen_sayi = sum(1 for a in eslesmeler.values() if a)

        # Kodlayan sekmelerde altyazi GOMULUR ve geri alinamaz. Klasordeki
        # altyazilari sessizce videolara yakmak buyuk bir surpriz olurdu;
        # bir kez soruyoruz. Sadece-altyazi sekmesinde soru anlamsiz (isin ta
        # kendisi altyazi eklemek).
        if eslesen_sayi and not is_remux:
            if not messagebox.askyesno(
                    "Altyazılar Bulundu",
                    f"{eslesen_sayi} videonun yanında aynı adlı altyazı dosyası var.\n\n"
                    "Bu altyazılar videonun GÖRÜNTÜSÜNE GÖMÜLSÜN mü?\n"
                    "(Gömülen altyazı sonradan kapatılamaz.)\n\n"
                    "Hayır derseniz videolar altyazısız dönüştürülür."):
                eslesmeler = {v: "" for v in videolar}
                eslesen_sayi = 0

        isler, atlanan, mevcut_olanlar = [], [], []
        # Kendi ciktilarimizi tekrar girdi olarak almamak icin: ikinci kez
        # calistirildiginda klasor artik "x_HEVC_1080p_CQ31.mkv" gibi dosyalarla
        # dolu olur ve onlar da kuyruga girerdi.
        ciktilar = set()

        for sira, video in enumerate(videolar, 1):
            alt = eslesmeler[video]
            cfg = self.collect_config(input_file=video, sub_file=alt)

            if is_remux and not alt:
                atlanan.append((video, "eşleşen altyazı dosyası yok"))
                continue
            sorun = self._job_sorunu(cfg)
            if sorun:
                atlanan.append((video, sorun[1].splitlines()[0]))
                continue

            ciktilar.add(os.path.normcase(cfg["output_file"]))
            if os.path.exists(cfg["output_file"]):
                mevcut_olanlar.append(cfg)
            isler.append(cfg)

            # Cozunurluk olcumu (buyutme korumasi) dosya basina bir ffprobe
            # calistirabiliyor; arayuz donmus gibi gorunmesin.
            if sira % 5 == 0:
                self.update_idletasks()

        # Kendi ciktisi olan girdileri ele
        onceki = len(isler)
        isler = [c for c in isler
                 if os.path.normcase(c["input_file"]) not in ciktilar]
        if onceki != len(isler):
            atlanan.append((f"{onceki - len(isler)} dosya",
                            "bu ayarların çıktısı olduğu için atlandı"))
        # KIMLIGE gore suzuyoruz: sozlukleri "==" ile karsilastirmak hem yavas
        # hem de ayni ayarli iki kaydi birbirine karistirabilir.
        kalan = {id(c) for c in isler}
        mevcut_olanlar = [c for c in mevcut_olanlar if id(c) in kalan]

        if not isler:
            messagebox.showinfo(
                "Eklenecek İş Yok",
                "Klasördeki videoların hiçbiri eklenemedi.\n\n"
                + "\n".join(f"• {os.path.basename(v)}: {n}" for v, n in atlanan[:10]))
            return

        # Uzerine yazma SORUSU BIR KEZ sorulur: 40 dosya icin 40 kez sormak
        # kullanilamaz bir arayuz olurdu.
        if mevcut_olanlar:
            cevap = messagebox.askyesnocancel(
                "Bazı Çıktılar Zaten Var",
                f"{len(mevcut_olanlar)} videonun çıktısı klasörde zaten mevcut.\n\n"
                "Evet: üzerine yazılsın\n"
                "Hayır: bu dosyalar atlansın\n"
                "İptal: hiçbir şey eklenmesin")
            if cevap is None:
                self.log("⚠️ Klasör ekleme iptal edildi.")
                return
            if not cevap:
                atlanacak = {id(c) for c in mevcut_olanlar}
                isler = [c for c in isler if id(c) not in atlanacak]
                atlanan.append((f"{len(mevcut_olanlar)} dosya", "çıktısı zaten var"))
                if not isler:
                    messagebox.showinfo("Eklenecek İş Yok",
                                        "Tüm çıktılar zaten mevcut; hiçbir iş eklenmedi.")
                    return

        self.job_queue.extend(isler)
        self._refresh_queue_view()
        self.log(f"📁 Kuyruğa {len(isler)} iş eklendi (klasör: {os.path.basename(klasor)})")
        for cfg in isler:
            self._sub_kodlama_uyar(cfg)
        for video, neden in atlanan:
            self.log(f"   ⏭️ Atlandı — {os.path.basename(video)}: {neden}")

        ozet = f"{len(isler)} video kuyruğa eklendi."
        if atlanan:
            ozet += f"\n{len(atlanan)} kayıt atlandı (ayrıntılar terminalde)."
        ozet += "\n\n'Dönüştür' düğmesi hepsini sırayla işler."
        messagebox.showinfo("Klasör Eklendi", ozet)

    def remove_last_from_queue(self):
        if self.job_queue:
            job = self.job_queue.pop()
            self._refresh_queue_view()
            self.log(f"➖ Kuyruktan çıkarıldı: {os.path.basename(job['input_file'])}")

    def clear_queue(self):
        if self.job_queue and messagebox.askyesno("Kuyruğu Temizle",
                                                  f"{len(self.job_queue)} iş kuyruktan silinecek. Emin misiniz?"):
            self.job_queue.clear()
            self._refresh_queue_view()
            self.log("🧹 Kuyruk temizlendi.")

    # =======================================================
    # ONIZLEME KARESI
    # =======================================================
    def show_preview_frame(self):
        """
        Kodlamayla AYNI filtre zincirini tek kareye uygulayip acar. Renk
        ayarlarini 40 dakikalik bir encode baslatmadan gorebilmek icin.
        """
        if not self.video_path.get():
            messagebox.showerror("Hata", "Önce bir video seçin!")
            return
        if not os.path.isfile(self.video_path.get()):
            messagebox.showerror("Hata", "Seçilen video dosyası bulunamadı.")
            return

        cfg = self.collect_config()
        self.log("🖼️ Önizleme karesi üretiliyor...")

        def _worker():
            try:
                probes = {
                    "cuda_frames": (self.can_use_cuda_frames(cfg["input_file"])
                                    if cfg["is_pure_cuda"] else False),
                    "pix_fmt": self.get_video_pix_fmt(cfg["input_file"]),
                }
                # Kirpma yoksa videonun ortasindan bir kare al: ilk kare cogu
                # zaman siyah acilis olur ve renk ayarini degerlendirmeye yaramaz.
                zaman = parse_time(cfg.get("trim_start"))
                if zaman is None:
                    sure = self.get_video_duration(cfg["input_file"])
                    zaman = sure / 2 if sure > 0 else 0.0
                png = os.path.join(tempfile.gettempdir(), "nvconv_onizleme.png")
                cmd = build_preview_command(cfg, probes, png, zaman)
                cmd[0] = FFMPEG_BIN
                sonuc = subprocess.run(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                    errors="replace", timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if sonuc.returncode == 0 and os.path.exists(png):
                    self._thread_safe_log(f"🖼️ Önizleme hazır ({zaman:.1f}. saniye): {png}")
                    os.startfile(png)
                else:
                    self._thread_safe_log("❌ Önizleme üretilemedi:")
                    for satir in (sonuc.stderr or "").strip().splitlines()[-6:]:
                        self._thread_safe_log(satir)
            except Exception as e:
                self._thread_safe_log(f"❌ Önizleme hatası: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def clear_sub(self):
        """Secili altyaziyi kaldirir."""
        if self.sub_path.get():
            self.log(f"Altyazı kaldırıldı: {os.path.basename(self.sub_path.get())}")
        self.sub_path.set("")
        self._refresh_sub_button()

    def _refresh_sub_button(self):
        """
        Altyazi dugmesi secili dosyayi kendi uzerinde gosterir (ayri bir metin
        kutusu tutmamak icin). Secim varsa yanina temizleme dugmesi cikar.
        """
        yol = self.sub_path.get()
        if yol:
            ad = os.path.basename(yol)
            if len(ad) > 20:
                ad = ad[:17] + "…"
            self.btn_sub.configure(text=f"💬 {ad}", fg_color="#2fa572", hover_color="#1e6b4a")
            if self.tabs.get(self.tabview.get(), {}).get("supports_subs", True):
                self.btn_sub_temizle.grid()
        else:
            self.btn_sub.configure(text=SUB_BTN_BOS, fg_color="#555555", hover_color="#444444")
            self.btn_sub_temizle.grid_remove()

    # =======================================================
    # FFMPEG KONUMU
    # =======================================================
    def apply_ffmpeg_dir(self, klasor):
        """
        Verilen klasordeki ikilileri devreye almaya calisir.
        (basarili_mi, mesaj) dondurur; dosyalarin varligi yetmez, GERCEKTEN
        calistiklari '-version' ile dogrulanir (yanlis mimari, eksik DLL vb.).
        """
        onceki = (FFMPEG_BIN, FFPROBE_BIN)
        ffmpeg_yolu, ffprobe_yolu = resolve_tools(klasor or None)
        if tools_usable(ffmpeg_yolu, ffprobe_yolu):
            self.ffmpeg_dir.set(klasor or "")
            self.ffmpeg_hazir = True
            return True, ffmpeg_yolu
        # Geri al: bozuk bir secim mevcut calisan kurulumu bozmasin.
        resolve_tools(self.ffmpeg_dir.get() or None)
        if not tools_usable(*onceki):
            self.ffmpeg_hazir = False
        return False, ffmpeg_yolu

    def select_ffmpeg_dir(self):
        """Kullanicidan ffmpeg.exe/ffprobe.exe iceren klasoru secmesini ister."""
        klasor = filedialog.askdirectory(
            title="ffmpeg ve ffprobe dosyalarının bulunduğu klasörü seçin",
            initialdir=self.ffmpeg_dir.get() or None)
        if not klasor:
            return
        tamam, yol = self.apply_ffmpeg_dir(klasor)
        if tamam:
            self.log(f"✅ FFmpeg ayarlandı: {yol}")
            messagebox.showinfo("FFmpeg Hazır", f"FFmpeg başarıyla ayarlandı:\n{yol}")
            self.save_settings()
        else:
            messagebox.showerror(
                "Geçersiz Klasör",
                "Seçilen klasörde çalışan ffmpeg/ffprobe bulunamadı.\n\n"
                "Klasörün içinde (veya altındaki bin klasöründe) "
                f"{'ffmpeg.exe ve ffprobe.exe' if os.name == 'nt' else 'ffmpeg ve ffprobe'} "
                "dosyaları olmalı."
            )

    def check_ffmpeg(self):
        """
        Acilista FFmpeg durumunu belirler. Bulunamazsa kullaniciya dogrudan
        klasor secme secenegi sunulur (hata verip birakmak yerine).
        """
        self.ffmpeg_hazir = tools_usable(FFMPEG_BIN, FFPROBE_BIN)
        if self.ffmpeg_hazir:
            self.log(f"🔧 FFmpeg: {FFMPEG_BIN}")
            return

        self.log("❌ FFmpeg bulunamadı.")
        cevap = messagebox.askyesno(
            "FFmpeg Bulunamadı",
            "Bu program çalışmak için FFmpeg ve FFprobe'a ihtiyaç duyar.\n"
            "Sistemde otomatik olarak bulunamadı.\n\n"
            "FFmpeg zaten bilgisayarınızda kuruluysa klasörünü şimdi "
            "göstermek ister misiniz?\n\n"
            "(Hayır derseniz: ffmpeg dosyalarını bu programın yanına kopyalayın "
            "veya https://ffmpeg.org/download.html adresinden kurun.)"
        )
        if cevap:
            self.select_ffmpeg_dir()

    # =======================================================
    # DONANIMA GÖRE SEKME GÖRÜNÜRLÜĞÜ
    # =======================================================
    def donanimi_uygula(self):
        """
        Makinede hangi marka varsa yalnizca onun sekmelerini birakir.

        Neden gerekli: kodlayan sekmelerin hepsi bir markaya bagli. NVIDIA
        karti sokulmus bir makinede uygulama NVENC sekmelerini gostermeye
        devam ederse kullanici "Dönüştür"e basana kadar sorunu fark etmiyor,
        sonra ham "Cannot load nvcuda.dll" hatasi aliyor. Bu birebir yasandi.

        Marka SORULMAZ, OLCULUR (bkz. donanim_bul): kart degisince uygulama
        kendini ayarlar, kullanicidan bir sey yapmasi beklenmez.
        """
        if not self.ffmpeg_hazir:
            self.log("ℹ️ FFmpeg hazır olmadığı için donanım taraması atlandı.")
            return

        self.donanim = donanim_bul()
        bulunan = [DONANIM[m]["ad"] for m, v in self.donanim.items() if v]
        self.log("🔎 Donanım taraması: " +
                 (", ".join(bulunan) + " bulundu" if bulunan
                  else "donanımsal kodlayıcı bulunamadı"))

        silinecek = []
        for marka, var_mi in self.donanim.items():
            if not var_mi:
                silinecek.extend(DONANIM[marka]["sekmeler"])

        # ACILIS SEKMESI SILMEDEN ONCE SECILIR. Sebep OLCULDU: CTkTabview.set()
        # 100 ms sonrasina "secili olmayanlari gizle" isi planliyor ve delete()
        # silinen sekme SECILI ise kendiliginden set() cagiriyor. Once silip
        # sonra secince iki set() ust uste biniyor; birincinin gecikmeli isi
        # ikincinin cercevesini de gizliyor ve icerik alani BOS kaliyordu
        # (iz kaydi: set('H.264 (AMD)') -> set('AV1 (AMD)') ->
        #  forget_all(exclude='H.264 (AMD)') -> forget_all(exclude='AV1 (AMD)')).
        # Silinmeyecek bir sekmeyi ONCE secince delete() hic set() cagirmaz ve
        # geriye tek bir gecikmeli is kalir.
        # Kullanicinin ayarlardan gelen sekme secimi hayattaysa ONA DOKUNMA:
        # gereksiz bir set() ikinci bir gecikmeli is demek, ustelik secimi de
        # ezerdi (olculdu: kayitli sekme H.264 iken AV1'e atliyordu).
        kalacak = [ad for ad in self.tabs if ad not in silinecek]
        if kalacak:
            simdiki = self.tabview.get()
            hedef = (simdiki if simdiki in kalacak else
                     VARSAYILAN_SEKME if VARSAYILAN_SEKME in kalacak else kalacak[0])
            if simdiki != hedef:
                self.tabview.set(hedef)

        for ad in silinecek:
            if ad not in self.tabs:
                continue
            try:
                self.tabview.delete(ad)
            except Exception:
                continue
            self.tabs.pop(ad, None)
            self.cq_refreshers.pop(ad, None)

        if silinecek:
            self.log(f"   {len(silinecek)} sekme gizlendi (donanımı yok): "
                     + ", ".join(silinecek))
        if not bulunan:
            self.log("   ⚠️ Yalnızca CPU (VP9) ve altyazı modu kullanılabilir.")

        # Secim yukarida, SILMEDEN ONCE yapildi. Burada yalnizca beklenmedik
        # bir durumda (secili sekme yine de yok olduysa) toparlanir.
        kalan = [ad for ad in self.tabs]
        if kalan and self.tabview.get() not in self.tabs:
            self.tabview.set(kalan[0])
        self.on_tab_change()
        # Gecikmeli isler bittikten sonra son bir kontrol (bkz. asagidaki not).
        self.after(250, self._sekme_cercevesini_garantile)

    def _sekme_cercevesini_garantile(self):
        """
        Secili sekmenin cercevesi ekranda degilse yeniden yerlestirir.

        Neden gerekli: CTkTabview.set() 100 ms SONRASINA "secili olmayan
        sekmeleri gizle" isi planliyor. Acilista birden fazla secim yapiliyor
        (ayarlardan gelen sekme + donanim taramasindan sonraki duzeltme) ve
        eski is, yeni secilen sekmenin cercevesini de gizleyebiliyor. Sonuc:
        sekme seridi doluyken icerik alani BOS. Zamanlamayi CTk belirledigi
        icin tek saglam yol, isler bittikten sonra sonuca BAKMAK.
        """
        try:
            ad = self.tabview.get()
            if ad in self.tabs and not self.tabview.tab(ad).winfo_ismapped():
                self.tabview.set(ad)
        except Exception:
            pass

    def _refresh_all_cq_displays(self):
        """Ayarlar yuklendikten sonra CQ etiket/renklerini tazeler."""
        for fn in self.cq_refreshers.values():
            try:
                fn()
            except Exception:
                pass

    def log(self, message):
        self.txt_log.configure(state='normal')
        try:
            last_line = self.txt_log.get("end-2c linestart", "end-1c").strip()
            if message.startswith("frame=") and last_line.startswith("frame="):
                self.txt_log.delete("end-2c linestart", "end")
                self.txt_log.insert(tk.END, "\n" + message)
            else:
                self.txt_log.insert(tk.END, message + "\n")
        except Exception:
            self.txt_log.insert(tk.END, message + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.configure(state='disabled')

    def _thread_safe_log(self, message):
        self.after(0, self.log, message)

    def _thread_safe_progress(self, pct):
        def _update():
            self.progress_bar.set(pct / 100.0)
            self.lbl_progress.configure(text=f"% {pct:.1f}")
        self.after(0, _update)

    def _thread_safe_eta(self, text):
        # DIKKAT: CTkLabel.configure(self, require_redraw=False, **kwargs) seklindedir.
        # Sozluk konumsal gecirilirse require_redraw'a dusare ve metin hic uygulanmaz.
        self.after(0, lambda: self.lbl_eta.configure(text=text))

    def get_subtitle_codecs(self, filepath):
        """Kaynaktaki altyazi izlerinin codec adlarini dondurur (yoksa bos liste)."""
        try:
            cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 's',
                   '-show_entries', 'stream=codec_name',
                   '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return [s.strip() for s in result.stdout.splitlines() if s.strip()]
        except Exception:
            return []

    def get_video_codec(self, filepath):
        """Kaynak videonun codec adini dondurur (bulunamazsa '')."""
        try:
            cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
                   '-show_entries', 'stream=codec_name',
                   '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            vals = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            return vals[0] if vals else ""
        except Exception:
            return ""

    def renk_etiketi_var_mi(self, filepath):
        """
        Kaynakta renk metadata'si (primaries/transfer/matrix) tanimli mi?

        Tanimsizsa cikti yanlis etiketleniyor: olculdu, etiketsiz 8-bit bir
        kaynak 10-bit'e cevrilince cikti BT.2020 + SMPTE2084 (HDR) damgasi
        aliyor ve goruntu kirmiziya caliyor. Bkz. build_filters.
        """
        try:
            cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
                   '-show_entries',
                   'stream=color_primaries,color_transfer,color_space',
                   '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            degerler = [s.strip().lower() for s in result.stdout.splitlines() if s.strip()]
            if not degerler:
                return False
            # ffprobe tanimsiz alanlar icin "unknown"/"N/A" dondurur
            return any(d not in ("unknown", "n/a", "unspecified", "reserved")
                       for d in degerler)
        except Exception:
            # Okunamadiysa etiket VAR say: gereksiz yere damgalamak, dogru
            # etiketli bir HDR kaynagi BT.709'a cevirmekten daha risklidir.
            return True

    def get_video_pix_fmt(self, filepath):
        """Kaynak videonun piksel formatini dondurur (bulunamazsa '')."""
        try:
            cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
                   '-show_entries', 'stream=pix_fmt',
                   '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            vals = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            return vals[0] if vals else ""
        except Exception:
            return ""

    def get_video_resolution(self, filepath):
        """Kaynak videonun (genislik, yukseklik) degerini dondurur; okunamazsa (0, 0)."""
        try:
            cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
                   '-show_entries', 'stream=width,height',
                   '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            vals = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            return (int(vals[0]), int(vals[1])) if len(vals) >= 2 else (0, 0)
        except Exception:
            return (0, 0)

    def get_audio_bitrate(self, filepath):
        """
        Kaynagin ilk ses akisinin bitrate'i (kbps); okunamazsa None.

        None YAYGIN ve normaldir: MKV gibi konteynerlerde akis basina bitrate
        yazmayabilir. O durumda sinirlama yapilmaz (bkz. ses_bitrate_sinirla).
        """
        try:
            sonuc = subprocess.run(
                [FFPROBE_BIN, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=bit_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1", filepath],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            ham = (sonuc.stdout or "").strip().splitlines()
            return round(int(ham[0]) / 1000) if ham and ham[0].isdigit() else None
        except Exception:
            return None

    def can_copy_audio(self, filepath, container):
        """
        Kaynak sesin hedef konteynere KOPYALANABILDIGINI dener (0.5 sn deneme muxu).
        Uyumluluk tablosu ezberlemek yerine olcuyoruz; ornegin WebM yalnizca
        opus/vorbis kabul ederken MKV ve MP4 test ettigim her codec'i aldi.
        """
        tmp = os.path.join(
            os.environ.get("TEMP", os.path.dirname(filepath)),
            "_nvconv_actest." + container
        )
        cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-i", filepath,
               "-map", "0:a:0", "-c:a", "copy", "-t", "0.5", "-y", tmp]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0
        except Exception:
            return False
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def can_use_cuda_frames(self, filepath):
        """
        Kaynagin NVDEC ile cozulup GERCEKTEN CUDA karesi uretip uretmedigini olcer.

        Desteklenen codec listesini ezberlemek yerine tek kare deneriz: NVDEC
        destegi GPU nesline ve surucu surumune gore degisir. ffmpeg, NVDEC girdiyi
        cozemedigi zaman -hwaccel_output_format cuda'yi SESSIZCE yok sayip yazilim
        cozucusune duser; sonra scale_cuda/yadif_cuda sistem bellegindeki kareyi
        alamayip "Function not implemented" ile isi komple durdurur.
        Maliyet ~0.2 sn; dakikalarca surecek bir kodlamanin oncesinde ihmal edilebilir.
        """
        cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
               "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
               "-i", filepath, "-frames:v", "1",
               # 256: NVENC'in minimum kare boyutunun uzerinde olmali
               "-vf", "scale_cuda=w=256:h=256",
               "-c:v", "hevc_nvenc", "-f", "null", "-"]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_video_duration(self, filepath):
        """
        Video suresini saniye cinsinden dondurur (bulunamazsa 0.0).

        stderr AYRI tutulur: ffprobe'un cozucu uyarilari ("error while decoding"
        gibi, -v error seviyesinde cikar) stdout'a karisirsa float() patlar ve
        gayet donusturulebilir bir dosyada ilerleme cubugu bastan sona 0'da kalir.
        Erken kareleri hasarli dosyalarda bu birebir yasaniyordu.
        """
        def _probe(entries, select=None):
            cmd = [FFPROBE_BIN, '-v', 'error']
            if select:
                cmd += ['-select_streams', select]
            cmd += ['-show_entries', entries,
                    '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            try:
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                return [s.strip() for s in result.stdout.splitlines() if s.strip()]
            except Exception:
                return []

        # 1) konteyner suresi, 2) video akisinin suresi
        for entries, select in (('format=duration', None), ('stream=duration', 'v:0')):
            for val in _probe(entries, select):
                try:
                    d = float(val)
                    if d > 0:
                        return d
                except ValueError:
                    continue

        # 3) matroska/webm sureyi akis etiketinde tutar: 00:00:05.000000000
        for val in _probe('stream_tags=DURATION', 'v:0'):
            try:
                h, m, s = val.split(':')
                d = float(h) * 3600 + float(m) * 60 + float(s)
                if d > 0:
                    return d
            except Exception:
                continue

        return 0.0

    def _build_output_path(self, cfg):
        """Cikti dosyasi adini uretir. Saf fonksiyon - Tk'ye dokunmaz."""
        klasor, dosya_adi = os.path.split(cfg["input_file"])
        if cfg.get("output_dir"):
            klasor = cfg["output_dir"]
        isim, _ = os.path.splitext(dosya_adi)

        # Sadece-altyazi modunda codec/CQ/olcekleme etiketlerinin hicbiri anlam
        # tasimaz (hicbiri degismiyor); ad yalnizca ne yapildigini soyler.
        if cfg.get("is_remux"):
            return os.path.join(klasor, f"{isim}_Altyazili.{cfg['container']}")

        etiket_codec = "VP9" if cfg["is_vp9"] else cfg["codec_v"].split('_')[0].upper()
        etiket_scale = cfg["scale"] if cfg["scale"] != "Orijinal" else "Orijinal"
        etiket_bwdif = "_Deint" if cfg["use_bwdif"] else ""
        # CQ etiketi olmadan ayni videoyu iki farkli kaliteyle denemek ayni
        # dosya adina yaziyor ve gereksiz "uzerine yaz?" sorusu cikiyordu.
        etiket_cq = f"_CQ{cfg['cq_val']}" if cfg.get("name_with_cq") else ""
        etiket_trim = "_Kirpik" if (parse_time(cfg.get("trim_start")) or
                                    parse_time(cfg.get("trim_end"))) else ""
        return os.path.join(
            klasor,
            f"{isim}_{etiket_codec}_{etiket_scale}{etiket_bwdif}{etiket_cq}{etiket_trim}.{cfg['container']}"
        )

    # =======================================================
    # AYAR KALICILIGI
    # =======================================================
    def _settings_snapshot(self):
        """Kaydedilecek ayarlari toplar (ana thread)."""
        data = {
            # Eski ayar dosyalarindaki 128k ses varsayilani bir KEZ "Kopyala"ya
            # cevrilir; bu bayrak islemin tekrarlanmasini engeller (kullanici
            # bilerek 128k'ya donmusse ikinci kez ezmeyelim).
            "ses_varsayilani_kopyala_gocu": True,
            # QP varsayilani bandin ALT ucundan UST ucuna gecti; kaydedilmis
            # eski degerlerin yeni davranisi bir kez devralmasi icin bayrak.
            "cq_ust_sinir_gocu": True,
            "aktif_sekme": self.tabview.get(),
            "son_video_klasoru": self.last_video_dir,
            "son_altyazi_klasoru": self.last_sub_dir,
            "ffmpeg_klasoru": self.ffmpeg_dir.get(),
            "ada_cq_ekle": self.name_with_cq.get(),
            "renk_profili": self.color_preset.get(),
            "parlaklik": self.val_brightness.get(),
            "kontrast": self.val_contrast.get(),
            "doygunluk": self.val_saturation.get(),
            "gamma": self.val_gamma.get(),
            "sekmeler": {},
        }
        for ad, tab_vars in self.tabs.items():
            data["sekmeler"][ad] = {
                k: v.get() for k, v in tab_vars.items() if hasattr(v, "get")
            }
        return data

    def save_settings(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(self._settings_snapshot(), fh, ensure_ascii=False, indent=1)
        except Exception:
            pass  # ayar kaydedilememesi programi engellememelidir

    def load_settings(self):
        """
        Kayitli ayarlari yukler. Bozuk/eski dosya programi acilmaz hale
        getirmemeli: her deger tek tek ve dogrulanarak uygulanir.
        """
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return
        if not isinstance(data, dict):
            return

        def ata(var, deger, gecerli=None):
            if deger is None:
                return
            try:
                if gecerli is not None and deger not in gecerli:
                    return
                var.set(deger)
            except Exception:
                pass

        self.last_video_dir = data.get("son_video_klasoru") or ""
        self.last_sub_dir = data.get("son_altyazi_klasoru") or ""
        ffmpeg_kl = data.get("ffmpeg_klasoru") or ""
        if ffmpeg_kl and os.path.isdir(ffmpeg_kl):
            self.ffmpeg_dir.set(ffmpeg_kl)
            resolve_tools(ffmpeg_kl)
        ata(self.name_with_cq, data.get("ada_cq_ekle"))
        ata(self.color_preset, data.get("renk_profili"),
            ["Varsayılan (Devre Dışı)", "Karanlık Video Kurtarma", "Özel Ayarlar"])
        for var, anahtar in ((self.val_brightness, "parlaklik"), (self.val_contrast, "kontrast"),
                             (self.val_saturation, "doygunluk"), (self.val_gamma, "gamma")):
            deger = data.get(anahtar)
            if isinstance(deger, (int, float)):
                ata(var, float(deger))

        for ad, kayit in (data.get("sekmeler") or {}).items():
            tab_vars = self.tabs.get(ad)
            if not tab_vars or not isinstance(kayit, dict):
                continue
            for anahtar, deger in kayit.items():
                var = tab_vars.get(anahtar)
                if var is None or not hasattr(var, "set"):
                    continue
                # Combobox'lar salt-okunur oldugu icin gecersiz bir kayitli deger
                # kutuda "takili" kalirdi; bu yuzden listeye karsi dogruluyoruz.
                gecerli = self.ALLOWED_VALUES.get(anahtar)
                if gecerli is not None and deger not in gecerli:
                    continue
                try:
                    var.set(deger)
                except Exception:
                    pass

        # --- ESKI SES VARSAYILANI GOCU (bir kez) ---
        # Ses varsayilani "128k yeniden kodla" idi ve kaydedilmis ayarlar bunu
        # yeni varsayilanin (Kopyala) uzerine yaziyordu. O deger kullanicinin
        # BILEREK sectigi bir sey degil, eski varsayilanin kalintisi: OLCULDU,
        # 32 kbps'lik bir kaynakta sesi 19 MB'tan 72 MB'a cikariyor ve ciktiyi
        # kaynaktan buyuk yapiyordu. Yalnizca tam olarak eski varsayilan
        # duruyorsa degistirilir; baska bir deger secilmisse dokunulmaz.
        if not data.get("ses_varsayilani_kopyala_gocu"):
            gocen = []
            for ad, tab_vars in self.tabs.items():
                var = tab_vars.get("audio_bitrate")
                if var is not None and var.get() == "128k":
                    var.set(SES_KOPYALA)
                    gocen.append(ad)
            if gocen:
                self.log(f"ℹ️ Ses ayarı {len(gocen)} sekmede 'Kopyala' yapıldı "
                         "(eski varsayılan 128k idi; kaynaktan yüksek bitrate "
                         "kaliteyi artırmaz, dosyayı büyütür). İstediğiniz "
                         "sekmede geri değiştirebilirsiniz.")

        # --- QP VARSAYILANI GOCU (bir kez) ---
        # Varsayilan artik onerilen bandin UST ucu (en tutumlu, olculen VMAF
        # ~90 noktasi). Kaydedilmis eski degerler bunu ezerdi. Restore edilen
        # degeri "otomatik konmus" sayarak isaretliyoruz: boylece kaynak
        # yuklenince deger yeni varsayilana oturur. Kullanici bundan SONRA
        # elle bir deger secerse bir daha dokunulmaz (bkz. _update_cq_display).
        if not data.get("cq_ust_sinir_gocu"):
            for tab_vars in self.tabs.values():
                if hasattr(tab_vars.get("cq"), "get"):
                    try:
                        tab_vars["cq_auto"] = int(float(tab_vars["cq"].get()))
                    except Exception:
                        pass
            self.log("ℹ️ QP varsayılanı, önerilen bandın en tutumlu ucuna "
                     "alındı (kaynağın çözünürlüğüne göre). Kadranı elle "
                     "değiştirirseniz seçiminiz korunur.")

        aktif = data.get("aktif_sekme")
        if aktif in self.tabs:
            try:
                self.tabview.set(aktif)
            except Exception:
                pass
        self.on_tab_change()
        self._refresh_all_cq_displays()

    def collect_config(self, input_file=None, sub_file=None):
        """
        Tum Tk degiskenlerini ANA THREAD'de okuyup duz bir sozluge kopyalar.
        Tkinter thread-safe degildir; worker thread'in StringVar/widget okumasi
        en iyi ihtimalle bayat deger, en kotusunde kilitlenme demektir.
        Worker (run_ffmpeg) bundan sonra yalnizca bu sozlugu gorur.

        input_file / sub_file verilirse arayuzdeki secimin YERINE gecer; klasor
        modu boylece ayni ayarlari her dosya icin yeniden kullanabiliyor
        (bkz. select_folder). Verilmezse eski davranis birebir korunur.
        """
        tab_name = self.tabview.get()
        tab_vars = self.tabs[tab_name]
        is_pure_cuda = tab_vars["is_pure_cuda"]
        is_vp9 = tab_vars["is_vp9"]
        is_remux = tab_vars.get("is_remux", False)

        def oku(anahtar, varsayilan=""):
            """Sekmede olmayan degiskenleri varsayilanla karsilar.

            Sadece-altyazi sekmesinde kodlayici ayarlari (CQ, cozunurluk, ses
            bitrate) HIC yoktur; onlari kosulsuz okumak KeyError verirdi.
            """
            var = tab_vars.get(anahtar)
            return var.get() if hasattr(var, "get") else varsayilan

        # Kodlayicisini sekme icinden secturen sekmeler (SAF CUDA ve TAM GPU)
        # "selected_codec" tasir; digerlerinde kodlayici sekmenin kendisidir.
        if "selected_codec" in tab_vars:
            codec_v = tab_vars["selected_codec"].get().split("(")[1].split(")")[0]
        else:
            codec_v = tab_vars["codec"]

        cfg = {
            "tab_name": tab_name,
            "is_pure_cuda": is_pure_cuda,
            "is_vp9": is_vp9,
            "is_remux": is_remux,
            "codec_v": codec_v,
            "input_file": input_file if input_file is not None else self.video_path.get(),
            "sub_file": sub_file if sub_file is not None else self.sub_path.get(),
            "container": tab_vars["container"].get(),
            "a_bitrate": oku("audio_bitrate", SES_KOPYALA),
            # Sadece-altyazi modunda CQ diye bir sey yok; "-" dosya adinda ve
            # kuyruk listesinde okunabilir bir yer tutucu olarak kalir.
            "cq_val": str(oku("cq", "-")),
            "scale": oku("scale", "Orijinal"),
            "preset": oku("preset", ""),
            "meta_title": tab_vars["metadata_title"].get(),
            "meta_artist": tab_vars["metadata_artist"].get(),
            "meta_album": tab_vars["metadata_album"].get(),
            "meta_grouping": tab_vars["metadata_grouping"].get(),
            "use_bwdif": tab_vars["bwdif"].get() if "bwdif" in tab_vars else False,
            "use_temporal_aq": tab_vars["temporal_aq"].get() if "temporal_aq" in tab_vars else False,
            "use_multipass": tab_vars["multipass"].get() if "multipass" in tab_vars else False,
            "use_long_gop": tab_vars["long_gop"].get() if "long_gop" in tab_vars else False,
            "no_upscale": tab_vars["no_upscale"].get() if "no_upscale" in tab_vars else False,
            "ten_bit": tab_vars["ten_bit"].get() if "ten_bit" in tab_vars else True,
            "interp_algo": tab_vars["interp_algo"].get() if "interp_algo" in tab_vars else "Otomatik",
            "amf_quality": oku("amf_quality", "quality"),
            # TAM GPU sekmesine ozgu (digerlerinde bu degiskenler yok).
            "amf_sr": tab_vars["amf_sr"].get() if "amf_sr" in tab_vars else False,
            "amf_sr_algo": AMF_SR_ALGORITMALARI.get(oku("amf_sr_algo", ""), AMF_SR_VARSAYILAN_ALGO),
            "amf_frc": tab_vars["amf_frc"].get() if "amf_frc" in tab_vars else False,
            "output_dir": self.output_dir.get().strip(),
            "name_with_cq": self.name_with_cq.get(),
            "trim_start": self.trim_start.get(),
            "trim_end": self.trim_end.get(),
            "color_preset": self.color_preset.get(),
            "brightness": self.val_brightness.get(),
            "contrast": self.val_contrast.get(),
            "saturation": self.val_saturation.get(),
            "gamma": self.val_gamma.get(),
        }

        if is_vp9:
            cfg["vp9_quality"] = tab_vars["vp9_quality"].get().split(" ")[0]
            cfg["vp9_speed"] = tab_vars["vp9_speed"].get().split(" ")[0]
            cfg["vp9_tiles"] = tab_vars["vp9_tiles"].get().split(" ")[0]
            cfg["vp9_threads"] = tab_vars["vp9_threads"].get()

        if is_remux:
            # Kutulardaki etiketler ("Türkçe (tur)") degil, ffmpeg'in bekledigi
            # degerler tasinir; etiketin sade hali altyazi izinin adi olur.
            etiket = oku("sub_lang", "Belirtilmedi")
            cfg["sub_lang"] = SUB_DIL_SECENEKLERI.get(etiket, "")
            cfg["sub_lang_label"] = etiket.split(" (")[0] if cfg["sub_lang"] else ""
            cfg["sub_charenc_zorla"] = SUB_CHARENC_SECENEKLERI.get(
                oku("sub_charenc", ""), "")
            cfg["sub_default"] = bool(oku("sub_default", False))
            cfg["keep_embedded_subs"] = bool(oku("keep_subs", True))
            # WebM metin altyazi tasiyamaz; bu sekme zaten onu sunmuyor ama
            # elle duzenlenmis bir ayar dosyasi kutuya sokabilir.
            if cfg["container"] not in ("mkv", "mp4"):
                cfg["container"] = "mkv"

        # ---- DONANIMSAL COZUCU SECIMI ----
        # Kodlayicinin markasi cozucunun de markasini belirler. VP9 (CPU
        # kodlayici) icin marka onemsiz: makinede ne varsa onun cozucusu
        # kullanilir, hicbiri yoksa yazilim cozucusune dusulur.
        def amd_cozucu():
            """
            AMD'de donanim cozucusu HER KAYNAKTA kazandirmiyor. Varsayilan
            "Otomatik" kaynagin kodegine bakar (bkz. D3D11VA_ISTEMEYEN_KODEKLER);
            kullanici sekmeden elle de zorlayabilir.
            ffprobe yalnizca bu dal icin calisir, NVIDIA makinesinde degil.
            """
            tercih = COZUCU_SECENEKLERI.get(oku("cozucu", ""), "oto")
            if tercih == "tamgpu":
                return "amf"
            if tercih == "donanim":
                return "d3d11va"
            if tercih == "yazilim":
                return ""
            kaynak = self.get_video_codec(cfg["input_file"])
            return "" if kaynak in D3D11VA_ISTEMEYEN_KODEKLER else "d3d11va"

        if tab_vars.get("is_tamgpu"):
            # Kopyasiz hat: cozucu de AMF olmak ZORUNDA. Olculdu, "-hwaccel
            # d3d11va -hwaccel_output_format amf" birlesimi cokuyor.
            cfg["hwaccel"] = "amf"
            cfg["tam_gpu"] = True
        elif codec_v in AMF_CODECS:
            cfg["hwaccel"] = amd_cozucu()
            cfg["tam_gpu"] = False
        elif codec_v.endswith("_nvenc"):
            cfg["hwaccel"] = "cuda"
        elif self.donanim.get(NVIDIA):
            cfg["hwaccel"] = "cuda"
        elif self.donanim.get(AMD):
            cfg["hwaccel"] = amd_cozucu()
        else:
            cfg["hwaccel"] = ""

        cfg["codec_a"] = "libopus" if cfg["container"] in ("mkv", "webm") else "aac"
        cfg["copy_audio"] = cfg["a_bitrate"].startswith("Kopyala")

        # --- BUYUTME KORUMASI ---
        # Kaynaktan buyuk bir hedef secildiyse olcekleme tamamen atlanir. Boylece
        # cikti adi da dogru kalir ("_4K" yazip 1080p uretmeyiz); ayrica bosuna
        # bit harcanmaz. Cozunurluk ana thread'de okunur (bkz. collect_config).
        cfg["upscale_blocked"] = False
        if cfg["no_upscale"] and cfg["scale"] != "Orijinal":
            hedef = SCALE_MAP.get(cfg["scale"])
            w, h = self.get_video_resolution(cfg["input_file"])
            if hedef and w and h and hedef >= max(w, h):
                cfg["scale"] = "Orijinal"
                cfg["upscale_blocked"] = True
                cfg["source_resolution"] = f"{w}x{h}"

        # AMD kodlayicilari cok kucuk kareyi reddediyor. Cikacak kare boyutunu
        # burada (ana thread'de) belirleyip cfg'ye koyuyoruz ki dogrulama
        # ffprobe'u tekrar calistirmak zorunda kalmasin.
        #
        # Bu bir YAKLASIK degerdir, birebir tahmin degil: av1_amf genisligi
        # kendi hizasina yuvarliyor (olculdu: 854 -> 856). Amac minimum kare
        # denetimi oldugu icin birkac pikselluk sapma onemsiz.
        #
        # OLCULDU (2026-08-16): yuvarlama YALNIZCA av1_amf'te var; hevc_amf
        # ayni kaynakta 854'u aynen koruyor. Kodlayicinin "-align" secenegi
        # bunu COZMUYOR: align=none yine 856 veriyor, align=64x16 ve
        # align=1080p ise "Resolution incorrect for alignment mode" ile
        # kodlayiciyi acmiyor. Bu yuzden -align komuta HIC eklenmiyor.
        if codec_v in AMF_CODECS:
            if cfg["scale"] != "Orijinal" and SCALE_MAP.get(cfg["scale"]):
                # Olcekleme uzun kenari sabitler; kisa kenar en-boy oranindan
                # gelir. Kaynak orani bilinmiyorsa 16:9 varsayilir.
                uzun = SCALE_MAP[cfg["scale"]]
                w, h = self.get_video_resolution(cfg["input_file"])
                # Kisa kenar CIFT olmali: olcekleme filtresi "-2" kullaniyor,
                # yani ffmpeg'in urettigi boyut da cifte yuvarlanir. Tek sayi
                # hesaplamak kullaniciya gosterilen olcuyu yanlis yapardi.
                def cift(x):
                    return max(2, round(x / 2) * 2)
                if w and h:
                    if w >= h:
                        cfg["cikti_boyutu"] = (uzun, cift(uzun * h / w))
                    else:
                        cfg["cikti_boyutu"] = (cift(uzun * w / h), uzun)
                else:
                    cfg["cikti_boyutu"] = (uzun, cift(uzun * 9 / 16))
            else:
                cfg["cikti_boyutu"] = self.get_video_resolution(cfg["input_file"])

        cfg["output_file"] = self._build_output_path(cfg)
        return cfg

    # Dogrulama mesajlari tek yerde: tekli secim de klasor modu da AYNI
    # kurallari uygulasin diye. Basligi ve metni dondurur, sorun yoksa None.
    def _job_sorunu(self, cfg):
        """cfg ile ilgili sorunu (baslik, metin) olarak dondurur; yoksa None."""
        if not os.path.isfile(cfg["input_file"]):
            return ("Hata", f"Video dosyası bulunamadı:\n{cfg['input_file']}")
        if cfg["output_dir"] and not os.path.isdir(cfg["output_dir"]):
            return ("Hata", f"Çıkış klasörü bulunamadı:\n{cfg['output_dir']}")

        # AMD donanim kodlayicisi cok kucuk kareyi kabul etmiyor. Onlemezsek
        # kullanici yalnizca "encoder->Init() failed with error 5" goruyor.
        #
        # Sinir KODEGE GORE degisir (bkz. AMF_MIN_KARE): ayni kare H.265'te
        # cokerken H.264 ve AV1'de sorunsuz kodlaniyor. Eskiden ucune de en
        # kotu durum uygulandigi icin calisan sekmeler de engelleniyordu.
        if cfg["codec_v"] in AMF_CODECS and cfg.get("cikti_boyutu"):
            w, h = cfg["cikti_boyutu"]
            min_w, min_h = AMF_MIN_KARE[cfg["codec_v"]]
            if w and h and (w < min_w or h < min_h):
                sekme = AMF_SEKME_ADI[cfg["codec_v"]]
                # Tavsiye DURUMA GORE degisir; hepsi ayni sirayla denenir.
                calisan = amf_kabul_eden_sekmeler(w, h)
                if calisan:
                    # En iyi cikis yolu: kareyi oldugu gibi kabul eden bir
                    # donanim sekmesi. Ne yeniden olcekleme, ne CPU'ya dusme.
                    oneri = (f"Bu dosya {' ya da '.join(calisan)} sekmesinde "
                             "OLDUĞU GİBİ dönüşür; çözünürlüğü değiştirmeniz "
                             "gerekmez.\n\nBu sekmede kalmak isterseniz daha "
                             "yüksek bir çözünürlük seçin ('Kaynaktan büyütme "
                             "yapma' şalteri kapalı olmalı).")
                elif cfg.get("upscale_blocked"):
                    # "Daha yuksek cozunurluk secin" demek tek basina cikmaz
                    # sokak: buyutme korumasi acikken secilen cozunurluk
                    # sessizce "Orijinal"e donuyor ve kullanici ayni hatayi
                    # tekrar aliyor.
                    oneri = ("Daha yüksek bir çözünürlük seçtiniz ama "
                             "'Kaynaktan büyütme yapma' şalteri açık olduğu için "
                             "uygulanmadı.\n\nO şalteri kapatın ya da bu dosyayı "
                             "VP9 (CPU) sekmesiyle dönüştürün.")
                else:
                    oneri = ("Daha yüksek bir çözünürlük seçin — bunun için "
                             "'Kaynaktan büyütme yapma' şalterini de kapatmanız "
                             "gerekir.\n\nYa da bu dosyayı VP9 (CPU) sekmesiyle "
                             "dönüştürün; orada böyle bir sınır yok.")
                return (f"Görüntü {sekme} İçin Çok Küçük",
                        f"Çıkacak kare {w}x{h}. {sekme} kodlayıcısı en az "
                        f"{min_w}x{min_h} ister ve bunun altında hata verip "
                        f"durur.\n\n{oneri}")

        if cfg["is_remux"]:
            if not cfg["sub_file"]:
                return ("Altyazı Seçilmedi",
                        "Bu sekme yalnızca altyazı ekler; eklenecek altyazı dosyasını "
                        "seçin.\n\n'💬 Altyazı Ekle' düğmesini kullanabilir veya "
                        "dosyayı pencereye sürükleyebilirsiniz.")
            if not os.path.isfile(cfg["sub_file"]):
                return ("Hata", f"Altyazı dosyası bulunamadı:\n{cfg['sub_file']}")
            # Elle secilen kodlama dosyayi cozemiyorsa ffmpeg de cozemez;
            # dakikalarca surecek bir kuyrugu bosuna baslatmayalim.
            kod_hata, _ = sub_kodlama_uyusmazligi(cfg["sub_file"],
                                                  cfg.get("sub_charenc_zorla", ""))
            if kod_hata:
                return ("Altyazı Kodlaması Uyuşmuyor",
                        f"{os.path.basename(cfg['sub_file'])}\n\n{kod_hata}")
            # Kirpma burada BILEREK engellenir. Olculdu (ffmpeg 9.0):
            #   * -ss girdi tarafinda verilirse harici altyazi videoyla birlikte
            #     otelenmiyor ve cikti desenkron oluyor.
            #   * -ss cikis tarafinda verilirse senkron dogru ama kopyalama
            #     anahtar kareye bagli oldugu icin GOP'u seyrek kaynaklarda tum
            #     video paketleri dusuyor: 0 kareli, sessizce bozuk bir dosya.
            # Kare hassas kirpma yeniden kodlama ister; bu modun varlik sebebi
            # ise tam olarak yeniden kodlamamak.
            if (cfg.get("trim_start") or "").strip() or (cfg.get("trim_end") or "").strip():
                return ("Kırpma Bu Modda Kullanılamaz",
                        "Sadece altyazı ekleme modunda kırpma yapılamaz: kopyalama kare "
                        "hassas değildir, kesim en yakın anahtar kareye kayar ve altyazı "
                        "kayması olur.\n\nKırpma alanlarını boşaltın ya da kırpma için "
                        "kodlama yapan sekmelerden birini kullanın.")

        for anahtar, etiket in (("trim_start", "Başlangıç"), ("trim_end", "Bitiş")):
            ham = (cfg.get(anahtar) or "").strip()
            if ham and parse_time(ham) is None:
                return ("Hata", f"Kırpma {etiket} değeri anlaşılamadı: '{ham}'\n\n"
                                "Beklenen biçim: 90  |  01:30  |  00:01:30.5")
        bas, son = parse_time(cfg.get("trim_start")), parse_time(cfg.get("trim_end"))
        if bas and son and son <= bas:
            return ("Hata", "Kırpma bitişi başlangıçtan sonra olmalı.")
        return None

    def _sub_kodlama_uyar(self, cfg):
        """
        Kodlama secimi dosyayi bozacak gibiyse loga bir satir dusur.
        Hata degil: is calisir, ama harfler bozuk cikabilir. Engellemek yerine
        gorunur kilmak dogru olan - kullanici bilerek zorlamis olabilir.
        """
        if not cfg.get("is_remux"):
            return
        _, uyari = sub_kodlama_uyusmazligi(cfg.get("sub_file", ""),
                                           cfg.get("sub_charenc_zorla", ""))
        if uyari:
            self.log(f"⚠️ {os.path.basename(cfg['sub_file'])}: {uyari}")

    def _prepare_job(self):
        """
        Mevcut arayuz durumundan bir is tanimi uretir; dogrulama ve kullanici
        onaylari ANA THREAD'de burada alinir. Uygun degilse None doner.
        """
        if not self.video_path.get():
            messagebox.showerror("Hata", "Önce dönüştürülecek videoyu seçin!")
            return None

        cfg = self.collect_config()

        sorun = self._job_sorunu(cfg)
        if sorun:
            messagebox.showerror(*sorun)
            return None
        self._sub_kodlama_uyar(cfg)

        if os.path.exists(cfg["output_file"]):
            if not messagebox.askyesno(
                    "Dosya Zaten Var",
                    f"'{os.path.basename(cfg['output_file'])}' zaten mevcut.\n\nÜzerine yazmak istiyor musunuz?"):
                self.log("⚠️ İşlem iptal edildi (dosya üzerine yazma reddedildi).")
                return None
        return cfg

    def start_thread(self):
        # Kuyruk doluysa onu isle; bos ise mevcut ayarlarla tek is calistir
        # (eski davranis birebir korunur).
        if self.job_queue:
            jobs = list(self.job_queue)
        else:
            job = self._prepare_job()
            if job is None:
                return
            jobs = [job]

        self.progress_bar.set(0)
        self.lbl_progress.configure(text="% 0.0")
        self.lbl_eta.configure(text="")

        # --- BUTONLARI HAZIRLA ---
        self.btn_start.configure(state="disabled", text="⏳ MOTOR ÇALIŞIYOR...")
        self.btn_pause.configure(state="normal", text="⏸️ Pause", fg_color="#1f538d")
        self.btn_stop.configure(state="normal")
        self.btn_delete.configure(state="normal")
        self.stop_requested = False
        self.delete_requested = False
        self.is_paused = False
        self._encode_start_time = None

        threading.Thread(target=self.run_queue, args=(jobs,), daemon=True).start()

    def run_queue(self, jobs):
        """Isleri sirayla calistirir. Kullanici iptal ederse kuyruk durur."""
        try:
            toplam = len(jobs)
            for sira, cfg in enumerate(jobs, 1):
                if self.stop_requested:
                    self._thread_safe_log(f"⏹️ Kuyruk durduruldu ({sira - 1}/{toplam} tamamlandı).")
                    break
                if toplam > 1:
                    self._thread_safe_log("")
                    self._thread_safe_log(f"📋 KUYRUK {sira}/{toplam}: {os.path.basename(cfg['input_file'])}")
                self.current_output_file = cfg["output_file"]
                self.delete_requested = False
                self.run_ffmpeg(cfg, son_is=(sira == toplam))
                if not self.stop_requested and toplam > 1:
                    self.after(0, self._pop_finished_job)
            if toplam > 1 and not self.stop_requested:
                self._thread_safe_log(f"🏁 KUYRUKTAKİ {toplam} İŞİN TAMAMI BİTTİ.")
        finally:
            def _bitir():
                self.btn_start.configure(state="normal", text="🚀 SEÇİLİ SEKMEYE GÖRE DÖNÜŞTÜR")
                self.btn_pause.configure(state="disabled", text="⏸️ Pause")
                self.btn_stop.configure(state="disabled")
                self.btn_delete.configure(state="disabled")
                self._refresh_queue_view()
            self.after(0, _bitir)
            self.current_process = None

    def _pop_finished_job(self):
        if self.job_queue:
            self.job_queue.pop(0)
            self._refresh_queue_view()

    def _kaynak_akis_dokumu(self, kaynak):
        """
        Kaynagin akis yapisini kisa bicimde dondurur (hata dokumu icin).
        Okunamazsa aciklayici bir satir dondurur; hata yolunu ASLA patlatmaz.
        """
        try:
            sonuc = subprocess.run(
                [FFPROBE_BIN, "-v", "error", "-show_entries",
                 "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,"
                 "r_frame_rate,sample_rate,channels,channel_layout:"
                 "format=format_name,duration,bit_rate",
                 "-of", "default=noprint_wrappers=1", kaynak],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return (sonuc.stdout or "").strip() or (sonuc.stderr or "").strip() or "(bos)"
        except Exception as e:
            return f"(okunamadi: {e})"

    def _hata_logu_yaz(self, cfg, cmd, cikis_kodu, bozuk_ad=None):
        """
        Basarisiz isin dokumunu ciktinin yanina ".hata.log" olarak yazar ve
        yolu dondurur (hicbir yere yazilamazsa None).

        Neden dosya: hata penceresi "log ekranina bakin" diyor ama o kutu 3
        satir gosteriyor ve salt-okunur oldugu icin metni kopyalamak zor.
        Hatayi cozmek icin gereken her sey (komut, cikis kodu, ffmpeg'in son
        satirlari, is ayarlari, kaynagin akis yapisi) tek dosyada olmazsa
        kullanicidan parca parca ekran goruntusu istemek gerekiyor.

        Yazma HATA YOLUNDA calisiyor: burada cikan bir istisna asil hatayi
        gizlerdi, o yuzden her sey try icinde ve basarisizlik sessiz.
        """
        satirlar = [
            "=" * 70,
            f"NvidiaConvertor hata dokumu - {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            f"Cikis kodu   : {cikis_kodu}",
            f"Sekme        : {cfg.get('tab_name')}",
            f"Kodlayici    : {cfg.get('codec_v')}    CQ/QP: {cfg.get('cq_val')}",
            f"Olcek        : {cfg.get('scale')}    Cikacak kare: {cfg.get('cikti_boyutu')}",
            f"Cozucu       : hwaccel={cfg.get('hwaccel') or '-'}  tam_gpu={bool(cfg.get('tam_gpu'))}",
            f"Konteyner    : {cfg.get('container')}    10-bit: {cfg.get('ten_bit')}",
            f"Ses          : {cfg.get('codec_a')}  bitrate={cfg.get('a_bitrate')}  kopyala={cfg.get('copy_audio')}",
            f"Altyazi      : {cfg.get('sub_file') or '-'}",
            f"Kaynak       : {cfg.get('input_file')}",
            f"Cikti        : {cfg.get('output_file')}",
            f"Yarim dosya  : {bozuk_ad or '-'}",
            f"ffmpeg       : {FFMPEG_BIN}",
            "",
            "--- CALISTIRILAN KOMUT " + "-" * 47,
            komut_metni(cmd),
            "",
            "--- KAYNAGIN AKIS YAPISI (ffprobe) " + "-" * 35,
            self._kaynak_akis_dokumu(cfg.get("input_file") or ""),
            "",
            "--- FFMPEG'IN SON CIKTISI " + "-" * 44,
        ]
        satirlar.extend(self._ffmpeg_tail)
        metin = "\n".join(satirlar) + "\n"

        # Once ciktinin yanina; orasi yazilamazsa (salt-okunur klasor, USB
        # cikarilmis vb.) hatayi kaybetmemek icin TEMP'e dus.
        temel = cfg.get("output_file") or ""
        adaylar = []
        if temel:
            adaylar.append(temel + ".hata.log")
        adaylar.append(os.path.join(tempfile.gettempdir(),
                                    "NvidiaConvertor_hata.log"))
        for yol in adaylar:
            try:
                with open(yol, "w", encoding="utf-8") as f:
                    f.write(metin)
                return yol
            except Exception:
                continue
        return None

    def _mark_broken_output(self, output_file):
        """
        Basarisiz bir isin geride biraktigi yarim/bos dosyayi ".bozuk" ekiyle
        isaretler ve yeni adi dondurur (dosya yoksa None).

        Neden silmiyoruz: kullanici bazen yarim ciktiya bakmak isteyebilir.
        Ama adi oldugu gibi birakmak tehlikeli - klasorde normal bir cikti gibi
        gorunuyor ve "donusmus" saniliyordu (tipik olarak 0 bayt oluyor).
        """
        try:
            if not os.path.isfile(output_file):
                return None
            boyut = os.path.getsize(output_file)
            hedef = output_file + ".bozuk"
            # Windows'ta cikan surecin tutamaci bir an gec birakilabiliyor
            for deneme in range(4):
                try:
                    os.replace(output_file, hedef)   # varsa eskisini ezer
                    self._thread_safe_log(
                        f"🚫 Yarım kalan çıktı işaretlendi ({boyut} bayt): "
                        f"{os.path.basename(hedef)}"
                    )
                    return hedef
                except OSError:
                    if deneme == 3:
                        raise
                    time.sleep(0.5)
        except Exception as e:
            self._thread_safe_log(f"⚠️ Bozuk çıktı işaretlenemedi: {e}")
        return None

    def run_ffmpeg(self, cfg, son_is=True):
        """
        Worker thread. DIKKAT: Bu metot hicbir Tk degiskenine/widget'ina DOKUNMAZ.
        Butun ayarlar ve kullanici onaylari ana thread'de alinip cfg ile gelir;
        UI'a geri bildirim yalnizca _thread_safe_* yardimcilari uzerinden yapilir.
        """
        try:
            active_tab_name = cfg["tab_name"]
            input_file = cfg["input_file"]
            container = cfg["container"]
            output_file = cfg["output_file"]

            total_duration = self.get_video_duration(input_file)
            if total_duration > 0:
                self._thread_safe_log(f"⏱️ Video Toplam Süresi: {total_duration:.2f} saniye")
            else:
                self._thread_safe_log("⚠️ Video süresi okunamadı: ilerleme çubuğu ve ETA çalışmayacak. (Dönüştürme normal şekilde devam eder.)")

            # --- OLCUMLER ---
            # Komut kurmak icin gereken, ancak ancak GERCEKTEN denenerek
            # ogrenilebilecek her sey burada toplanir; build_command bunlari
            # veri olarak alir ve kendisi hicbir olcum yapmaz (saf fonksiyon).
            is_remux = cfg.get("is_remux", False)
            kaynak_pix = "" if is_remux else self.get_video_pix_fmt(input_file)
            cuda_frames = self.can_use_cuda_frames(input_file) if cfg["is_pure_cuda"] else False

            # 12-bit + renk filtresi: NVDEC kareyi cozebiliyor ama RAM'e
            # indirilemiyor. Isi patlatmak yerine filtreleri CPU'ya aliyoruz.
            if cuda_frames and color_filter_of(cfg) and not cuda_color_roundtrip_ok(kaynak_pix):
                cuda_frames = False
                self._thread_safe_log(
                    f"⚠️ {kaynak_pix} kaynakta renk filtresi GPU belleğine indirilemiyor; "
                    "filtreler CPU'da çalışacak (kodlama yine NVENC)."
                )

            # Sadece-altyazi modunda gomulu izler HER konteynerde onemli: harici
            # altyazinin cikti indeksi ve "-c:s:N" eslemesi onlarin sayisina bagli.
            if is_remux:
                gomulu_subs = (self.get_subtitle_codecs(input_file)
                               if cfg.get("keep_embedded_subs", True) else [])
                sub_charenc, sub_cevrim = detect_sub_charenc(
                    cfg["sub_file"], cfg.get("sub_charenc_zorla", ""))
            else:
                gomulu_subs = (self.get_subtitle_codecs(input_file)
                               if container == "mkv" and not cfg["sub_file"] else [])
                sub_charenc, sub_cevrim = "", False

            probes = {
                "cuda_frames": cuda_frames,
                "pix_fmt": kaynak_pix,
                # Remux'ta kare hic dokunulmadigi icin etiket de aynen kalir.
                "renk_etiketsiz": (False if is_remux
                                   else not self.renk_etiketi_var_mi(input_file)),
                "sub_codecs": gomulu_subs,
                "sub_charenc": sub_charenc,
                "sub_needs_transcode": sub_cevrim,
                "audio_copy_ok": (self.can_copy_audio(input_file, container)
                                  if cfg["copy_audio"] and not is_remux else False),
                # "Kopyala" secili olsa da olculur: kopyalama basarisiz olursa
                # devreye giren yedek bitrate de kaynagi asmamali.
                "audio_bitrate": (None if is_remux
                                  else self.get_audio_bitrate(input_file)),
            }

            cmd, notes = build_command(cfg, probes)
            for note in notes:
                self._thread_safe_log(note)

            self._thread_safe_log("=" * 60)
            self._thread_safe_log(f"🎬 İŞLEM BAŞLIYOR: {active_tab_name} Sekmesi")
            self._thread_safe_log(f"⚙️ ÇALIŞTIRILAN FFmpeg KOMUTU:\n{komut_metni(cmd)}")
            self._thread_safe_log("=" * 60)

            # Saf builder mantiksal "ffmpeg" adini uretir (log okunakli kalsin);
            # calistirmadan hemen once gercek yola cevrilir.
            cmd[0] = FFMPEG_BIN
            self.current_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,   # iptalde 'q' gonderebilmek icin (bkz. _graceful_stop)
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            self._encode_start_time = time.time()

            # Hata aninda gosterilmek uzere son ciktilar saklanir. FFmpeg'in gercek
            # hata satirlari ("Could not open encoder before EOF", "Conversion failed!"
            # vb.) asagidaki log filtresinden gecmez; hata durumunda bu tampon dokulur.
            self._ffmpeg_tail = deque(maxlen=50)

            for line in self.current_process.stdout:
                line = line.strip()

                if line:
                    self._ffmpeg_tail.append(line)

                if "time=" in line and total_duration > 0:
                    try:
                        time_str = line.split("time=")[1].split(" ")[0]
                        h, m, s = time_str.split(":")
                        current_sec = float(h) * 3600 + float(m) * 60 + float(s)

                        pct = min((current_sec / total_duration) * 100, 100.0)
                        self._thread_safe_progress(pct)

                        # ETA hesaplama
                        if pct > 0 and self._encode_start_time:
                            elapsed = time.time() - self._encode_start_time
                            estimated_total = elapsed / (pct / 100.0)
                            remaining = estimated_total - elapsed
                            if remaining > 3600:
                                eta_text = f"ETA: {int(remaining//3600)}s {int((remaining%3600)//60)}dk"
                            elif remaining > 60:
                                eta_text = f"ETA: {int(remaining//60)}dk {int(remaining%60)}sn"
                            else:
                                eta_text = f"ETA: {int(remaining)}sn"
                            self._thread_safe_eta(eta_text)
                    except Exception:
                        pass

                if line.startswith("frame=") or "Error" in line or "fps=" in line:
                    self._thread_safe_log(line)

            self.current_process.wait()

            # --- İPTAL / SİLME İŞLEMİ KONTROLÜ ---
            if self.stop_requested:
                self._thread_safe_log("⚠️ İŞLEM KULLANICI TARAFINDAN İPTAL EDİLDİ.")
                if not self.delete_requested and self.current_process.returncode == 0:
                    self._thread_safe_log(f"💾 O ana kadar kodlanan bölüm kaydedildi ve oynatılabilir:\n{os.path.basename(output_file)}")
                self.after(0, self.progress_bar.set, 0)
                self.after(0, lambda: self.lbl_progress.configure(text="% 0.0"))
                self.after(0, lambda: self.lbl_eta.configure(text=""))

                if self.delete_requested:
                    time.sleep(1.5)
                    try:
                        if os.path.exists(self.current_output_file):
                            os.remove(self.current_output_file)
                            self._thread_safe_log("🗑️ YARIM KALAN ÇÖP DOSYA BAŞARIYLA SİLİNDİ.")
                    except Exception as e:
                        self._thread_safe_log(f"⚠️ Dosya silinemedi: İzin reddedildi veya dosya kullanımda. Hata: {e}")
                return

            # --- BAŞARILI BİTİŞ ---
            if self.current_process.returncode == 0:
                self.after(0, self.progress_bar.set, 1.0)
                self.after(0, lambda: self.lbl_progress.configure(text="% 100.0"))
                self.after(0, lambda: self.lbl_eta.configure(text="Tamamlandı!"))
                self._thread_safe_log("=" * 60)
                self._thread_safe_log(f"🎉 İŞLEM KUSURSUZ TAMAMLANDI!")

                # Klasor/ses/dialog yalnizca kuyrugun SON isinde: 10 islik bir
                # kuyrukta 10 kez explorer acmak kimsenin istedigi sey degil.
                if son_is:
                    try:
                        abs_out_path = os.path.abspath(output_file)
                        subprocess.Popen(f'explorer /select,"{abs_out_path}"')
                    except Exception as e:
                        self._thread_safe_log(f"Klasör açılamadı: {e}")

                    try:
                        winsound.PlaySound(r"C:\Windows\Media\notify.wav", winsound.SND_FILENAME | winsound.SND_ASYNC)
                    except Exception:
                        pass

                    self.after(0, messagebox.showinfo, "Başarılı", f"Arşivleme tamamlandı!\n\nDosya:\n{os.path.basename(output_file)}")
            else:
                self._thread_safe_log("=" * 60)
                self._thread_safe_log(f"❌ KRİTİK HATA OLUŞTU (çıkış kodu: {self.current_process.returncode})")
                self._thread_safe_log("--- FFmpeg'in son çıktısı ---")
                for tail_line in self._ffmpeg_tail:
                    self._thread_safe_log(tail_line)
                self._thread_safe_log("=" * 60)

                bozuk_ad = self._mark_broken_output(output_file)

                # Log kutusu 3 satir gosteriyor ve kopyalanamiyor; hatayi
                # cozebilmek icin gereken her sey dosyaya da yazilir.
                log_yolu = self._hata_logu_yaz(cfg, cmd,
                                               self.current_process.returncode,
                                               bozuk_ad)
                if log_yolu:
                    self._thread_safe_log(f"📄 Hata dökümü yazıldı: {log_yolu}")

                ek_mesaj = ""
                if bozuk_ad:
                    ek_mesaj = f"\n\nYarım kalan çıktı şu adla işaretlendi:\n{os.path.basename(bozuk_ad)}"
                if log_yolu:
                    ek_mesaj += ("\n\nHatanın tam dökümü şu dosyaya yazıldı "
                                 "(komut, ffmpeg çıktısı ve kaynağın akış "
                                 f"yapısı dahil):\n{log_yolu}")
                self.after(0, messagebox.showerror, "Hata",
                           "FFmpeg bir hata döndürdü. Detaylar için siyah log ekranına bakın." + ek_mesaj)

        except Exception as e:
            self._thread_safe_log(f"❌ BEKLENMEYEN HATA: {str(e)}")
        finally:
            # Butonlari run_queue sifirlar: kuyrugun ortasinda "Baslat"in tekrar
            # aktiflesmesi ikinci bir kuyrugun paralel baslamasina yol acardi.
            self.current_process = None

if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        myappid = 'borasavkar.nvidia.cuda.Video.convertor.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = FFmpegStudioPro()
    app.mainloop()