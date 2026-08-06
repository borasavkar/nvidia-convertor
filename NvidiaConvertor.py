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
    }
}

# Varsayilanlar ilgili araligin ortasidir (tablodaki mevcut degerlerin kurali).
# av1 icin "1080p" anahtari eksikti; "default" (45) devreye girip araligin
# (38-45) tam TEPESINE dusuyordu, digerlerinin aksine.
CQ_DEFAULTS = {
    # "default" (= "Orijinal" secimi) bilerek 45'te birakildi: kaynak cozunurlugu
    # bilinmedigi icin mevcut davranisi degistirmemek adina dokunulmadi.
    "av1_nvenc": {"4K": 47, "1440p": 44, "1080p": 41, "720p": 35, "480p": 30,
                  "360p": 27, "240p": 25, "default": 45},
    "hevc_nvenc": {"4K": 35, "1440p": 33, "1080p": 31, "720p": 26, "480p": 22,
                   "360p": 20, "240p": 18, "default": 31},
    "h264_nvenc": {"4K": 29, "1440p": 27, "1080p": 26, "720p": 21, "480p": 18,
                   "360p": 15, "240p": 13, "default": 26},
    "libvpx-vp9": {"4K": 15, "1440p": 24, "1080p": 31, "720p": 32, "480p": 33, "360p": 36, "240p": 37, "default": 31}
}

SCALE_MAP = {
    "240p": 426, "360p": 640, "480p": 854, "720p": 1280,
    "1080p": 1920, "1440p": 2560, "4K": 3840
}

# Dosya secimi ve surukle-birak ayni listeyi kullanir (birbirinden sapmasin diye)
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.ts', '.vob', '.y4m',
              '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg')
SUB_EXTS = ('.srt', '.ass', '.vtt')


def get_cq_range(codec, scale):
    codec_ranges = CQ_RANGES.get(codec, CQ_RANGES["hevc_nvenc"])
    return codec_ranges.get(scale, codec_ranges["default"])


def get_cq_default(codec, scale):
    codec_defaults = CQ_DEFAULTS.get(codec, CQ_DEFAULTS["hevc_nvenc"])
    return codec_defaults.get(scale, codec_defaults["default"])


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


def build_filters(cfg, probes):
    """
    Video filtre zincirini kurar. SAF FONKSIYON.
    Hem gercek kodlama hem de onizleme karesi ayni zinciri kullanir; boylece
    onizlemede gordugun goruntu ciktida elde edecegin goruntudur.
    """
    notes = []
    cuda_frames = probes.get("cuda_frames", False)
    vf_filters = []

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

    return vf_filters, notes


def build_preview_command(cfg, probes, cikti_png, zaman=None):
    """
    Tek karelik onizleme komutu. Kodlama komutuyla AYNI filtre zincirini
    kullanir (build_filters), boylece onizleme ciktiyi temsil eder.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-hwaccel", "cuda"]
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

    cmd = ["ffmpeg", "-hwaccel", "cuda"]
    if cuda_frames:
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
                    "-level:v", "auto", "-spatial-aq", "1", "-rc-lookahead", "32",
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
                    "-rc-lookahead", "32", "-spatial-aq", "1", "-bf", "3",
                    "-b_ref_mode", "middle"])
        if not cuda_frames:
            cmd.extend(["-pix_fmt", "yuv420p"])
        cmd.extend(["-temporal-aq", "1" if cfg["use_temporal_aq"] else "0"])

    if cfg["use_multipass"]:
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
            # patlatmak yerine yuksek bitrate ile kodluyoruz.
            cmd.extend(["-c:a", codec_a, "-b:a", "192k"])
            notes.append(f"⚠️ Kaynak ses '{container}' konteynerine kopyalanamıyor; "
                         f"{codec_a} 192k ile yeniden kodlanacak.")
    else:
        cmd.extend(["-c:a", codec_a, "-b:a", cfg["a_bitrate"]])

    for anahtar, deger in (("title", cfg["meta_title"]), ("artist", cfg["meta_artist"]),
                           ("album", cfg["meta_album"]), ("grouping", cfg["meta_grouping"])):
        if deger.strip():
            cmd.extend(["-metadata", f"{anahtar}={deger}"])

    cmd.extend(["-y", cfg["output_file"]])
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
        self.last_video_dir = ""
        self.last_sub_dir = ""
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

        # --- KÖK YERLEŞİM ---
        # Ayar kartları + sekmeler tek başına ~1200 px istiyor; bu 1080p bir
        # ekrana sığmaz ve "Dönüştür" butonu pencerenin altında kalıyordu.
        # Çözüm: ayarlar KAYDIRILABİLİR bir alana konur, buton ve log ise
        # kendi grid satırlarında sabit durur; hangi ekran boyutunda olursa
        # olsun ikisi de her zaman görünür.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=6)              # ayarlar (kaydırılabilir)
        self.grid_rowconfigure(1, weight=0)              # Dönüştür butonu
        self.grid_rowconfigure(2, weight=1, minsize=170)  # log

        self.ust_alan = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.ust_alan.grid(row=0, column=0, sticky="nsew")

        # 1. DOSYA SEÇİM ALANI
        frame_files = self.create_card(self.ust_alan, "🎬 Medya Seçimi")
        frame_files.pack(fill="x", padx=15, pady=(10, 5))

        inner_files = ctk.CTkFrame(frame_files, fg_color="transparent")
        inner_files.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(inner_files, text="Video Dosyası:").grid(row=0, column=0, padx=15, pady=10, sticky="w")
        self.entry_vid = ctk.CTkEntry(inner_files, textvariable=self.video_path, width=450, placeholder_text="Dönüştürülecek videoyu seçin veya sürükleyin...")
        self.entry_vid.grid(row=0, column=1, padx=10, pady=10)
        ctk.CTkButton(inner_files, text="Gözat", width=100, command=self.select_video).grid(row=0, column=2, padx=10)

        self.lbl_sub = ctk.CTkLabel(inner_files, text="Altyazı (Opsiyonel):")
        self.lbl_sub.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="w")
        self.entry_sub = ctk.CTkEntry(inner_files, textvariable=self.sub_path, width=450, placeholder_text="Hardsub için SRT seçin...")
        self.entry_sub.grid(row=1, column=1, padx=10, pady=(0, 15))
        self.btn_sub = ctk.CTkButton(inner_files, text="Gözat", width=100, command=self.select_sub)
        self.btn_sub.grid(row=1, column=2, padx=10, pady=(0, 15))

        # --- CIKIS KLASORU ---
        ctk.CTkLabel(inner_files, text="Çıkış Klasörü:").grid(row=2, column=0, padx=15, pady=(0, 15), sticky="w")
        ctk.CTkEntry(inner_files, textvariable=self.output_dir, width=450,
                     placeholder_text="Boş bırakılırsa kaynak videonun yanına yazılır").grid(row=2, column=1, padx=10, pady=(0, 15))
        frame_out = ctk.CTkFrame(inner_files, fg_color="transparent")
        frame_out.grid(row=2, column=2, padx=10, pady=(0, 15), sticky="w")
        ctk.CTkButton(frame_out, text="Gözat", width=100, command=self.select_output_dir).pack(side="left")
        ctk.CTkCheckBox(inner_files, text="Dosya adına CQ ekle",
                        variable=self.name_with_cq).grid(row=3, column=1, padx=10, pady=(0, 10), sticky="w")
        self.btn_ffmpeg = ctk.CTkButton(inner_files, text="⚙️ FFmpeg Yolu", width=100,
                                        fg_color="#555555", hover_color="#444444",
                                        command=self.select_ffmpeg_dir)
        self.btn_ffmpeg.grid(row=3, column=2, padx=10, pady=(0, 10))

        # (Sürükle-bırak kurulumu log kutusu oluştuktan sonra yapılır - __init__ sonu)

        # 1.5. GÖRÜNTÜ VE RENK AYARLARI ALANI
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

        # 2. SEKMELER
        self.tabview = ctk.CTkTabview(self.ust_alan, command=self.on_tab_change)
        self.tabview.pack(fill="x", padx=15, pady=5)

        self.tabs = {}

        self.create_tab("AV1 (Standart)", "av1_nvenc")
        self.create_tab("H.265 (Standart)", "hevc_nvenc")
        self.create_tab("H.264 (Standart)", "h264_nvenc")
        self.create_vp9_tab("VP9 (Google VOD)")
        self.create_cuda_tab("⚡ SAF CUDA")

        self.tabview.set("⚡ SAF CUDA")

        # 2.5. KUYRUK
        frame_queue = self.create_card(self.ust_alan, "📋 Dönüştürme Kuyruğu")
        frame_queue.pack(fill="x", padx=15, pady=(0, 5))

        queue_top = ctk.CTkFrame(frame_queue, fg_color="transparent")
        queue_top.pack(fill="x", padx=10, pady=(0, 5))
        self.lbl_queue = ctk.CTkLabel(queue_top, text="Kuyruk boş — 'Dönüştür' mevcut ayarları hemen çalıştırır.",
                                      font=("Arial", 11), text_color="#AAAAAA", anchor="w")
        self.lbl_queue.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(queue_top, text="➕ Kuyruğa Ekle", width=130,
                      command=self.add_to_queue).pack(side="left", padx=3)
        ctk.CTkButton(queue_top, text="➖ Sondakini Sil", width=120, fg_color="#555555",
                      hover_color="#444444", command=self.remove_last_from_queue).pack(side="left", padx=3)
        ctk.CTkButton(queue_top, text="🧹 Temizle", width=90, fg_color="#555555",
                      hover_color="#444444", command=self.clear_queue).pack(side="left", padx=3)

        self.txt_queue = ctk.CTkTextbox(frame_queue, height=56, font=("Consolas", 11),
                                        fg_color="#1A1A1A", corner_radius=8)
        self.txt_queue.pack(fill="x", padx=10, pady=(0, 10))
        self.txt_queue.configure(state="disabled")

        # 3. BAŞLAT BUTONU
        self.btn_start = ctk.CTkButton(
            self, text="🚀 SEÇİLİ SEKMEYE GÖRE DÖNÜŞTÜR",
            font=("Arial", 16, "bold"), height=50, corner_radius=25,
            command=self.start_thread
        )
        self.btn_start.grid(row=1, column=0, sticky="ew", padx=15, pady=10)

        self.on_tab_change()

        # 4. LOG VE İLERLEME EKRANI
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

        self.txt_log = ctk.CTkTextbox(frame_log, font=("Consolas", 11), text_color="#00FF00", fg_color="#000000", corner_radius=10)
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
    AUDIO_VALUES = ["Kopyala (yeniden kodlama yok)", "64k", "96k", "128k", "192k", "256k", "320k"]
    PRESET_VALUES = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
    SCALE_VALUES = ["Orijinal", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K"]
    VP9_AUDIO_VALUES = ["Kopyala (yeniden kodlama yok)", "64k", "96k", "128k", "192k"]

    # Kayitli ayarlar yuklenirken dogrulama icin: combobox'lar salt-okunur
    # oldugundan gecersiz bir deger kutuda takili kalir ve ffmpeg'e gider.
    ALLOWED_VALUES = {
        "container": ["mkv", "mp4", "webm"],
        "audio_bitrate": AUDIO_VALUES,
        "preset": PRESET_VALUES,
        "scale": SCALE_VALUES,
        "interp_algo": ["Otomatik", "bilinear", "bicubic", "lanczos"],
        "selected_codec": ["AV1 (av1_nvenc)", "H.265 (hevc_nvenc)", "H.264 (h264_nvenc)"],
        "vp9_quality": ["good (Önerilen)", "best (Aşırı Yavaş)", "realtime"],
        "vp9_speed": ["0 (Maksimum Kalite)", "1 (VOD Önerisi)", "2 (Standart)", "3 (Hızlı)", "4", "5 (En Hızlı)"],
        "vp9_tiles": ["0 (Tek Sütun)", "1 (Düşük Çöz. için)", "2 (1080p için)", "3 (4K/1440p için)", "4 (8K)"],
        "vp9_threads": ["Auto", "2", "4", "8", "16", "32"],
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

    def _create_toggles_card(self, parent, tab_vars, title, bwdif_text):
        card = self.create_card(parent, title)
        card.pack(fill="x", pady=10)
        ctk.CTkCheckBox(card, text=bwdif_text, variable=tab_vars["bwdif"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card, text="Zamansal AQ (temporal-aq)", variable=tab_vars["temporal_aq"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card, text="Çift Geçiş (-multipass 2)", variable=tab_vars["multipass"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card, text="Uzun GOP (-g 300)", variable=tab_vars["long_gop"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card, text="Kaynaktan büyütme yapma", variable=tab_vars["no_upscale"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card, text="10-bit kodla (main10)", variable=tab_vars["ten_bit"]).pack(anchor="w", padx=15, pady=(5, 15))
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

    def _tab_meta(self, is_pure_cuda, is_vp9, accent, supports_subs=True):
        """Sekme davranisini isim icinde metin aramak yerine veri olarak tasir."""
        return {
            "is_pure_cuda": is_pure_cuda,
            "is_vp9": is_vp9,
            "accent": accent,             # (renk, hover, yazi rengi) - baslat butonu
            "supports_subs": supports_subs,
        }

    def _nvenc_tab_vars(self, container_default, cq_default):
        """Her iki NVENC sekmesinin paylastigi degisken seti."""
        return {
            "container": ctk.StringVar(value=container_default),
            "audio_bitrate": ctk.StringVar(value="128k"),
            "preset": ctk.StringVar(value="p7"),
            "cq": ctk.IntVar(value=cq_default),
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
            self.lbl_sub.grid()
            self.entry_sub.grid()
            self.btn_sub.grid()
        else:
            self.lbl_sub.grid_remove()
            self.entry_sub.grid_remove()
            self.btn_sub.grid_remove()

        self.btn_start.configure(fg_color=color, hover_color=hover, text_color=text_color)
        self.tabview.configure(segmented_button_selected_color=color, segmented_button_selected_hover_color=hover)

    # =======================================================
    # ORTAK CQ SLIDER GÜNCELLEME
    # =======================================================
    def _update_cq_display(self, codec, tab_vars, lbl_cq_title, lbl_cq_status, slider_cq, label_prefix="CQ (Kalite)"):
        v = int(float(tab_vars["cq"].get()))
        lbl_cq_title.configure(text=f"{label_prefix}: {v}")
        current_scale = tab_vars["scale"].get()

        min_cq, max_cq = get_cq_range(codec, current_scale)

        if min_cq <= v <= max_cq:
            lbl_cq_status.configure(text=f"✨ Önerilen Aralık ({min_cq}-{max_cq})", text_color="#00FF00")
            slider_cq.configure(progress_color="#00FF00")
        elif v < min_cq:
            lbl_cq_status.configure(text=f"⚠️ Gereksiz Büyük Dosya (< {min_cq})", text_color="#FFA500")
            slider_cq.configure(progress_color="#FFA500")
        else:
            lbl_cq_status.configure(text=f"❌ Çamurlaşma Riski (> {max_cq})", text_color="#FF4444")
            slider_cq.configure(progress_color="#FF4444")

    def _auto_set_cq(self, codec, scale, tab_vars, slider_cq, lbl_cq_title, lbl_cq_status, label_prefix="CQ (Kalite)"):
        val = get_cq_default(codec, scale)
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
            "audio_bitrate": ctk.StringVar(value="128k"),
            "cq": ctk.IntVar(value=31),
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
        ReadOnlyComboBox(card_format, variable=tab_vars["audio_bitrate"], values=["Kopyala (yeniden kodlama yok)", "64k", "96k", "128k", "192k"]).pack(fill="x", padx=15, pady=(5, 15))

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
        ctk.CTkCheckBox(card_res, text="Kaynaktan büyütme yapma", variable=tab_vars["no_upscale"]).pack(anchor="w", padx=15, pady=(0, 15))

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
        self._create_toggles_card(col_right, tab_vars, "🛠️ Kontrol Şalterleri",
                                  "Taraklanmayı Gider (bwdif)")

    # =======================================================
    # SAF CUDA SEKMESİ
    # =======================================================
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

        self._create_toggles_card(col_right, tab_vars, "🛠️ CUDA Kontrol Şalterleri",
                                  "Donanımsal Tarak Giderici (yadif_cuda)")

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
            self.log(f"Altyazı Eklendi: {os.path.basename(path)}")

    # =======================================================
    # KUYRUK
    # =======================================================
    def _refresh_queue_view(self):
        self.txt_queue.configure(state="normal")
        self.txt_queue.delete("1.0", tk.END)
        for i, job in enumerate(self.job_queue, 1):
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

    def select_output_dir(self):
        yol = filedialog.askdirectory(title="Çıkış Klasörünü Seçin",
                                      initialdir=self.output_dir.get() or self.last_video_dir or None)
        if yol:
            self.output_dir.set(yol)
            self.log(f"📂 Çıkış klasörü: {yol}")

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
            "aktif_sekme": self.tabview.get(),
            "son_video_klasoru": self.last_video_dir,
            "son_altyazi_klasoru": self.last_sub_dir,
            "cikis_klasoru": self.output_dir.get(),
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
        cikis = data.get("cikis_klasoru") or ""
        if cikis and os.path.isdir(cikis):
            self.output_dir.set(cikis)
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

        aktif = data.get("aktif_sekme")
        if aktif in self.tabs:
            try:
                self.tabview.set(aktif)
            except Exception:
                pass
        self.on_tab_change()
        self._refresh_all_cq_displays()

    def collect_config(self):
        """
        Tum Tk degiskenlerini ANA THREAD'de okuyup duz bir sozluge kopyalar.
        Tkinter thread-safe degildir; worker thread'in StringVar/widget okumasi
        en iyi ihtimalle bayat deger, en kotusunde kilitlenme demektir.
        Worker (run_ffmpeg) bundan sonra yalnizca bu sozlugu gorur.
        """
        tab_name = self.tabview.get()
        tab_vars = self.tabs[tab_name]
        is_pure_cuda = tab_vars["is_pure_cuda"]
        is_vp9 = tab_vars["is_vp9"]

        if is_pure_cuda:
            codec_v = tab_vars["selected_codec"].get().split("(")[1].split(")")[0]
        else:
            codec_v = tab_vars["codec"]

        cfg = {
            "tab_name": tab_name,
            "is_pure_cuda": is_pure_cuda,
            "is_vp9": is_vp9,
            "codec_v": codec_v,
            "input_file": self.video_path.get(),
            "sub_file": self.sub_path.get(),
            "container": tab_vars["container"].get(),
            "a_bitrate": tab_vars["audio_bitrate"].get(),
            "cq_val": str(tab_vars["cq"].get()),
            "scale": tab_vars["scale"].get(),
            "preset": tab_vars["preset"].get() if "preset" in tab_vars else "",
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

        cfg["output_file"] = self._build_output_path(cfg)
        return cfg

    def _prepare_job(self):
        """
        Mevcut arayuz durumundan bir is tanimi uretir; dogrulama ve kullanici
        onaylari ANA THREAD'de burada alinir. Uygun degilse None doner.
        """
        if not self.video_path.get():
            messagebox.showerror("Hata", "Önce dönüştürülecek videoyu seçin!")
            return None

        cfg = self.collect_config()

        if not os.path.isfile(cfg["input_file"]):
            messagebox.showerror("Hata", f"Seçilen video dosyası bulunamadı:\n{cfg['input_file']}")
            return None
        if cfg["output_dir"] and not os.path.isdir(cfg["output_dir"]):
            messagebox.showerror("Hata", f"Çıkış klasörü bulunamadı:\n{cfg['output_dir']}")
            return None
        for anahtar, etiket in (("trim_start", "Başlangıç"), ("trim_end", "Bitiş")):
            ham = (cfg.get(anahtar) or "").strip()
            if ham and parse_time(ham) is None:
                messagebox.showerror("Hata", f"Kırpma {etiket} değeri anlaşılamadı: '{ham}'\n\n"
                                             "Beklenen biçim: 90  |  01:30  |  00:01:30.5")
                return None
        bas, son = parse_time(cfg.get("trim_start")), parse_time(cfg.get("trim_end"))
        if bas and son and son <= bas:
            messagebox.showerror("Hata", "Kırpma bitişi başlangıçtan sonra olmalı.")
            return None

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
            kaynak_pix = self.get_video_pix_fmt(input_file)
            cuda_frames = self.can_use_cuda_frames(input_file) if cfg["is_pure_cuda"] else False

            # 12-bit + renk filtresi: NVDEC kareyi cozebiliyor ama RAM'e
            # indirilemiyor. Isi patlatmak yerine filtreleri CPU'ya aliyoruz.
            if cuda_frames and color_filter_of(cfg) and not cuda_color_roundtrip_ok(kaynak_pix):
                cuda_frames = False
                self._thread_safe_log(
                    f"⚠️ {kaynak_pix} kaynakta renk filtresi GPU belleğine indirilemiyor; "
                    "filtreler CPU'da çalışacak (kodlama yine NVENC)."
                )

            probes = {
                "cuda_frames": cuda_frames,
                "pix_fmt": kaynak_pix,
                "sub_codecs": (self.get_subtitle_codecs(input_file)
                               if container == "mkv" and not cfg["sub_file"] else []),
                "audio_copy_ok": (self.can_copy_audio(input_file, container)
                                  if cfg["copy_audio"] else False),
            }

            cmd, notes = build_command(cfg, probes)
            for note in notes:
                self._thread_safe_log(note)

            self._thread_safe_log("=" * 60)
            self._thread_safe_log(f"🎬 İŞLEM BAŞLIYOR: {active_tab_name} Sekmesi")
            self._thread_safe_log(f"⚙️ ÇALIŞTIRILAN FFmpeg KOMUTU:\n{' '.join(cmd)}")
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
                self.after(0, messagebox.showerror, "Hata", "FFmpeg bir hata döndürdü. Detaylar için siyah log ekranına bakın.")

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