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

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# --- MODERN ARAYÜZ AYARLARI ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# =======================================================
# CQ ARALIK TABLOLARİ (tek yerde tanımlı)
# =======================================================
CQ_RANGES = {
    "av1_nvenc": {
        "4K": (45, 50), "1080p": (38, 45), "720p": (33, 38), "480p": (28, 32),
        "default": (38, 45)
    },
    "hevc_nvenc": {
        "4K": (33, 38), "1080p": (28, 34), "720p": (24, 28), "480p": (20, 24),
        "default": (28, 34)
    },
    "h264_nvenc": {
        "4K": (27, 31), "1080p": (23, 28), "720p": (19, 23), "480p": (16, 19),
        "default": (23, 28)
    },
    "libvpx-vp9": {
        "4K": (12, 18), "1440p": (21, 27), "1080p": (28, 34), "720p": (29, 35),
        "480p": (30, 36), "360p": (33, 39), "240p": (34, 40),
        "default": (28, 34)
    }
}

CQ_DEFAULTS = {
    "av1_nvenc": {"4K": 47, "720p": 35, "480p": 30, "default": 45},
    "hevc_nvenc": {"4K": 35, "720p": 26, "480p": 22, "default": 31},
    "h264_nvenc": {"4K": 29, "720p": 21, "480p": 18, "default": 26},
    "libvpx-vp9": {"4K": 15, "1440p": 24, "1080p": 31, "720p": 32, "480p": 33, "360p": 36, "240p": 37, "default": 31}
}

SCALE_MAP = {
    "240p": 426, "360p": 640, "480p": 854, "720p": 1280,
    "1080p": 1920, "1440p": 2560, "4K": 3840
}


def get_cq_range(codec, scale):
    codec_ranges = CQ_RANGES.get(codec, CQ_RANGES["hevc_nvenc"])
    return codec_ranges.get(scale, codec_ranges["default"])


def get_cq_default(codec, scale):
    codec_defaults = CQ_DEFAULTS.get(codec, CQ_DEFAULTS["hevc_nvenc"])
    return codec_defaults.get(scale, codec_defaults["default"])


class FFmpegStudioPro(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Nvidia Cuda Video Convertor - Ultimate Edition")
        self.geometry("850x1050")
        self.resizable(False, False)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.current_process = None
        self.is_paused = False
        self.stop_requested = False
        self.delete_requested = False
        self.current_output_file = None
        self._encode_start_time = None

        # --- FFmpeg Kontrolü ---
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            messagebox.showerror(
                "FFmpeg Bulunamadı",
                "Bu program çalışmak için FFmpeg ve FFprobe'a ihtiyaç duyar.\n\n"
                "Lütfen FFmpeg'i indirip PATH'e ekleyin:\nhttps://ffmpeg.org/download.html"
            )

        try:
            ikon_yolu = self.resource_path("icon.ico")
            self.iconbitmap(ikon_yolu)
        except Exception:
            pass

        self.video_path = ctk.StringVar()
        self.sub_path = ctk.StringVar()

        # 1. DOSYA SEÇİM ALANI
        frame_files = self.create_card(self, "🎬 Medya Seçimi")
        frame_files.pack(fill="x", padx=15, pady=10)

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

        # --- Drag & Drop ---
        if HAS_DND:
            self._setup_drag_and_drop()

        # 2. SEKMELER
        self.tabview = ctk.CTkTabview(self, command=self.on_tab_change)
        self.tabview.pack(fill="x", padx=15, pady=5)

        self.tabs = {}

        self.create_tab("AV1 (Standart)", "av1_nvenc")
        self.create_tab("H.265 (Standart)", "hevc_nvenc")
        self.create_tab("H.264 (Standart)", "h264_nvenc")
        self.create_vp9_tab("VP9 (Google VOD)")
        self.create_cuda_tab("⚡ SAF CUDA")

        self.tabview.set("⚡ SAF CUDA")

        # 3. BAŞLAT BUTONU
        self.btn_start = ctk.CTkButton(
            self, text="🚀 SEÇİLİ SEKMEYE GÖRE DÖNÜŞTÜR",
            font=("Arial", 16, "bold"), height=50, corner_radius=25,
            command=self.start_thread
        )
        self.btn_start.pack(fill="x", padx=15, pady=15)

        self.on_tab_change()

        # 4. LOG VE İLERLEME EKRANI
        frame_log = self.create_card(self, "📟 FFmpeg Terminal ve Durum")
        frame_log.pack(fill="both", expand=True, padx=15, pady=(0, 15))

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

    # =======================================================
    # DRAG & DROP
    # =======================================================
    def _setup_drag_and_drop(self):
        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        path = event.data.strip('{}')
        video_exts = ('.mp4', '.mkv', '.avi', '.mov', '.ts', '.vob', '.y4m', '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg')
        sub_exts = ('.srt', '.ass', '.vtt')
        ext = os.path.splitext(path)[1].lower()
        if ext in video_exts:
            self.video_path.set(path)
            self.log(f"Video Sürüklendi: {os.path.basename(path)}")
        elif ext in sub_exts:
            self.sub_path.set(path)
            self.log(f"Altyazı Sürüklendi: {os.path.basename(path)}")

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

    def stop_process(self):
        if self.current_process:
            cevap = messagebox.askyesno("İptal Onayı", "Mevcut render işlemini iptal etmek istediğinize emin misiniz?")
            if cevap:
                self.stop_requested = True
                if self.is_paused and HAS_PSUTIL:
                    try:
                        psutil.Process(self.current_process.pid).resume()
                    except Exception:
                        pass
                self.current_process.kill()

    def delete_process(self):
        if self.current_process:
            cevap = messagebox.askyesno("Sil Onayı", "DİKKAT! İşlem durdurulacak ve şu ana kadar yaratılan yarım dosya DİSKTEN SİLİNECEK.\nEmin misiniz?")
            if cevap:
                self.stop_requested = True
                self.delete_requested = True
                if self.is_paused and HAS_PSUTIL:
                    try:
                        psutil.Process(self.current_process.pid).resume()
                    except Exception:
                        pass
                self.current_process.kill()

    def on_closing(self):
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
        tab = self.tabview.get()

        if "SAF CUDA" in tab:
            self.lbl_sub.grid_remove()
            self.entry_sub.grid_remove()
            self.btn_sub.grid_remove()
            color = "#76b900"
            hover = "#5a8d00"
            text_color = "black"
        else:
            self.lbl_sub.grid()
            self.entry_sub.grid()
            self.btn_sub.grid()

            if "AV1" in tab:
                color, hover, text_color = "#1f538d", "#14375e", "white"
            elif "H.265" in tab:
                color, hover, text_color = "#2fa572", "#1e6b4a", "white"
            elif "VP9" in tab:
                color, hover, text_color = "#8e44ad", "#732d91", "white"
            else:
                color, hover, text_color = "#c0392b", "#922b21", "white"

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
    # YENİ VP9 (GOOGLE VOD) SEKMESİ
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
            "metadata_title": ctk.StringVar(value=""),
            "metadata_artist": ctk.StringVar(value=""),
            "metadata_album": ctk.StringVar(value=""),
            "metadata_grouping": ctk.StringVar(value=""),
        }
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
        ctk.CTkComboBox(card_format, variable=tab_vars["container"], values=["webm", "mkv"]).pack(fill="x", padx=15, pady=(0, 5))
        ctk.CTkLabel(card_format, text="* VP9 için WebM standarttır (Audio: Opus)", font=("Arial", 10, "italic"), text_color="gray").pack(anchor="w", padx=15, pady=(0, 5))
        ctk.CTkComboBox(card_format, variable=tab_vars["audio_bitrate"], values=["64k", "96k", "128k", "192k"]).pack(fill="x", padx=15, pady=(5, 15))

        card_vp9 = self.create_card(col_left, "🧠 VP9 İşlemci Motoru (CPU)")
        card_vp9.pack(fill="x", pady=10)

        ctk.CTkLabel(card_vp9, text="-quality (Genel Kalite):").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_vp9, variable=tab_vars["vp9_quality"], values=["good (Önerilen)", "best (Aşırı Yavaş)", "realtime"]).pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(card_vp9, text="-speed (0 Yavaş - 5 Hızlı):").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_vp9, variable=tab_vars["vp9_speed"], values=["0 (Maksimum Kalite)", "1 (VOD Önerisi)", "2 (Standart)", "3 (Hızlı)", "4", "5 (En Hızlı)"]).pack(fill="x", padx=15, pady=(0, 10))

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

        cb_scale = ctk.CTkComboBox(card_res, variable=tab_vars["scale"], values=["Orijinal", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K"], command=on_vp9_scale_change)
        cb_scale.pack(fill="x", padx=15, pady=(10, 15))

        ctk.CTkLabel(card_res, text="-tile-columns (Bölme):").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_res, variable=tab_vars["vp9_tiles"], values=["0 (Tek Sütun)", "1 (Düşük Çöz. için)", "2 (1080p için)", "3 (4K/1440p için)", "4 (8K)"]).pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(card_res, text="-threads (CPU Çekirdek Kullanımı):").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_res, variable=tab_vars["vp9_threads"], values=["Auto", "2", "4", "8", "16", "32"]).pack(fill="x", padx=15, pady=(0, 15))

        on_cq_change_vp9()

        self._create_metadata_card(col_right, tab_vars)

    # =======================================================
    # STANDART SEKMELER
    # =======================================================
    def create_tab(self, tab_name, codec_name):
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        default_cont = "mkv" if "AV1" in tab_name else "mp4"
        if "AV1" in tab_name: default_cq = 45
        elif "H.265" in tab_name: default_cq = 31
        else: default_cq = 26

        tab_vars = {
            "codec": codec_name,
            "container": ctk.StringVar(value=default_cont),
            "audio_bitrate": ctk.StringVar(value="128k"),
            "preset": ctk.StringVar(value="p7"),
            "cq": ctk.IntVar(value=default_cq),
            "scale": ctk.StringVar(value="Orijinal"),
            "metadata_title": ctk.StringVar(value=""),
            "metadata_artist": ctk.StringVar(value=""),
            "metadata_album": ctk.StringVar(value=""),
            "metadata_grouping": ctk.StringVar(value=""),
            "bwdif": ctk.BooleanVar(value=False),
            "temporal_aq": ctk.BooleanVar(value=True),
            "multipass": ctk.BooleanVar(value=False),
            "long_gop": ctk.BooleanVar(value=False)
        }
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

        if "AV1" in tab_name:
            card_format = self.create_card(col_left, "📦 Format Konteyner")
            card_format.pack(fill="x", pady=(0, 10))
            ctk.CTkComboBox(card_format, variable=tab_vars["container"], values=["mkv", "mp4"]).pack(fill="x", padx=15, pady=(0, 5))
            ctk.CTkLabel(card_format, text="* MKV: libopus | MP4: aac", font=("Arial", 10, "italic"), text_color="gray").pack(anchor="w", padx=15, pady=(0, 10))

        pady_top = 0 if "AV1" in tab_name else 10
        card_audio = self.create_card(col_left, "🎵 Ses Kalitesi")
        card_audio.pack(fill="x", pady=(pady_top, 10))
        ctk.CTkComboBox(card_audio, variable=tab_vars["audio_bitrate"], values=["64k", "96k", "128k", "192k", "256k", "320k"]).pack(fill="x", padx=15, pady=(0, 15))

        card_nvenc = self.create_card(col_left, "⚙️ Nvenc Motoru")
        card_nvenc.pack(fill="x", pady=10)
        ctk.CTkLabel(card_nvenc, text="NVENC Preset:").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_nvenc, variable=tab_vars["preset"], values=["p1", "p2", "p3", "p4", "p5", "p6", "p7"]).pack(fill="x", padx=15, pady=(0, 15))

        lbl_cq_title = ctk.CTkLabel(card_nvenc, text=f"CQ (Kalite): {tab_vars['cq'].get()}", font=("Arial", 13, "bold"))
        lbl_cq_status = ctk.CTkLabel(card_nvenc, text="", font=("Arial", 11, "italic"))

        lbl_cq_title.pack(anchor="w", padx=15, pady=(5, 0))
        lbl_cq_status.pack(anchor="w", padx=15, pady=(0, 5))

        slider_cq = ctk.CTkSlider(card_nvenc, from_=0, to=51, number_of_steps=51, variable=tab_vars["cq"], command=on_cq_change)
        slider_cq.pack(fill="x", padx=15, pady=(0, 15))

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 Çözünürlük")
        card_res.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_res, text="Akıllı Ölçeklendirme (Lanczos):").pack(anchor="w", padx=15)

        cb_scale = ctk.CTkComboBox(card_res, variable=tab_vars["scale"], values=["Orijinal", "480p", "720p", "1080p", "4K"], command=on_scale_change)
        cb_scale.pack(fill="x", padx=15, pady=(0, 15))

        on_cq_change()

        self._create_metadata_card(col_right, tab_vars)

        card_toggles = self.create_card(col_right, "🛠️ Kontrol Şalterleri")
        card_toggles.pack(fill="x", pady=10)
        ctk.CTkCheckBox(card_toggles, text="Taraklanmayı Gider (bwdif)", variable=tab_vars["bwdif"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card_toggles, text="Zamansal AQ (temporal-aq)", variable=tab_vars["temporal_aq"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card_toggles, text="Çift Geçiş (-multipass 2)", variable=tab_vars["multipass"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card_toggles, text="Uzun GOP (-g 300)", variable=tab_vars["long_gop"]).pack(anchor="w", padx=15, pady=(5, 15))

    # =======================================================
    # SAF CUDA SEKMESİ
    # =======================================================
    def create_cuda_tab(self, tab_name):
        self.tabview.add(tab_name)
        frame = self.tabview.tab(tab_name)

        tab_vars = {
            "selected_codec": ctk.StringVar(value="AV1 (av1_nvenc)"),
            "container": ctk.StringVar(value="mkv"),
            "audio_bitrate": ctk.StringVar(value="128k"),
            "preset": ctk.StringVar(value="p7"),
            "cq": ctk.IntVar(value=45),
            "scale": ctk.StringVar(value="Orijinal"),
            "metadata_title": ctk.StringVar(value=""),
            "metadata_artist": ctk.StringVar(value=""),
            "metadata_album": ctk.StringVar(value=""),
            "metadata_grouping": ctk.StringVar(value=""),
            "bwdif": ctk.BooleanVar(value=False),
            "temporal_aq": ctk.BooleanVar(value=True),
            "multipass": ctk.BooleanVar(value=False),
            "long_gop": ctk.BooleanVar(value=False)
        }
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
            if "AV1" in choice: tab_vars["container"].set("mkv")
            else: tab_vars["container"].set("mp4")
            codec = choice.split("(")[1].split(")")[0]
            self._auto_set_cq(codec, tab_vars["scale"].get(), tab_vars, slider_cq, lbl_cq_title, lbl_cq_status)

        card_codec = self.create_card(col_left, "🚀 Donanım Motoru (VRAM)")
        card_codec.pack(fill="x", pady=(0, 10))
        cb_codec = ctk.CTkComboBox(card_codec, variable=tab_vars["selected_codec"], values=["AV1 (av1_nvenc)", "H.265 (hevc_nvenc)", "H.264 (h264_nvenc)"], command=on_cuda_codec_change)
        cb_codec.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(card_codec, text="Konteyner:").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_codec, variable=tab_vars["container"], values=["mp4", "mkv"]).pack(fill="x", padx=15, pady=(0, 15))

        card_audio = self.create_card(col_left, "🎵 Ses Kalitesi")
        card_audio.pack(fill="x", pady=10)
        ctk.CTkComboBox(card_audio, variable=tab_vars["audio_bitrate"], values=["64k", "96k", "128k", "192k", "256k", "320k"]).pack(fill="x", padx=15, pady=(0, 15))

        card_nvenc = self.create_card(col_left, "⚙️ Nvenc Ön Ayarları")
        card_nvenc.pack(fill="x", pady=10)
        ctk.CTkLabel(card_nvenc, text="NVENC Preset:").pack(anchor="w", padx=15)
        ctk.CTkComboBox(card_nvenc, variable=tab_vars["preset"], values=["p1", "p2", "p3", "p4", "p5", "p6", "p7"]).pack(fill="x", padx=15, pady=(0, 15))

        lbl_cq_title = ctk.CTkLabel(card_nvenc, text=f"CQ (Kalite): {tab_vars['cq'].get()}", font=("Arial", 13, "bold"))
        lbl_cq_status = ctk.CTkLabel(card_nvenc, text="", font=("Arial", 11, "italic"))

        lbl_cq_title.pack(anchor="w", padx=15, pady=(5, 0))
        lbl_cq_status.pack(anchor="w", padx=15, pady=(0, 5))

        slider_cq = ctk.CTkSlider(card_nvenc, from_=0, to=51, number_of_steps=51, variable=tab_vars["cq"], command=on_cq_change)
        slider_cq.pack(fill="x", padx=15, pady=(0, 15))

        col_right = ctk.CTkFrame(main_grid, fg_color="transparent")
        col_right.grid(row=0, column=1, sticky="nsew", padx=5)

        card_res = self.create_card(col_right, "📐 CUDA Çözünürlük (scale_cuda)")
        card_res.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(card_res, text="Donanımsal GPU Ölçekleme:").pack(anchor="w", padx=15)

        cb_scale = ctk.CTkComboBox(card_res, variable=tab_vars["scale"], values=["Orijinal", "480p", "720p", "1080p", "4K"], command=on_cuda_scale_change)
        cb_scale.pack(fill="x", padx=15, pady=(0, 15))

        on_cq_change()

        self._create_metadata_card(col_right, tab_vars)

        card_toggles = self.create_card(col_right, "🛠️ CUDA Kontrol Şalterleri")
        card_toggles.pack(fill="x", pady=10)
        ctk.CTkCheckBox(card_toggles, text="Donanımsal Tarak Giderici (yadif_cuda)", variable=tab_vars["bwdif"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card_toggles, text="Zamansal AQ (temporal-aq)", variable=tab_vars["temporal_aq"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card_toggles, text="Çift Geçiş (-multipass 2)", variable=tab_vars["multipass"]).pack(anchor="w", padx=15, pady=5)
        ctk.CTkCheckBox(card_toggles, text="Uzun GOP (-g 300)", variable=tab_vars["long_gop"]).pack(anchor="w", padx=15, pady=(5, 15))

    def select_video(self):
        path = filedialog.askopenfilename(
            title="Dönüştürülecek Videoyu Seçin",
            filetypes=[("Tüm Video Dosyaları", "*.mp4 *.mkv *.avi *.mov *.ts *.vob *.y4m *.webm *.flv *.wmv *.m4v *.mpg *.mpeg"), ("Tüm Dosyalar", "*.*")]
        )
        if path:
            self.video_path.set(path)
            self.log(f"Video Seçildi: {os.path.basename(path)}")

    def select_sub(self):
        path = filedialog.askopenfilename(filetypes=[("Altyazı Dosyası", "*.srt *.ass *.vtt")])
        if path:
            self.sub_path.set(path)
            self.log(f"Altyazı Eklendi: {os.path.basename(path)}")

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
        self.after(0, self.lbl_eta.configure, {"text": text})

    def get_video_duration(self, filepath):
        try:
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    def start_thread(self):
        if not self.video_path.get():
            messagebox.showerror("Hata", "Önce dönüştürülecek videoyu seçin!")
            return

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

        threading.Thread(target=self.run_ffmpeg, daemon=True).start()

    def run_ffmpeg(self):
        try:
            active_tab_name = self.tabview.get()
            tab_vars = self.tabs[active_tab_name]
            is_pure_cuda = "SAF CUDA" in active_tab_name
            is_vp9 = "VP9" in active_tab_name

            input_file = self.video_path.get()
            sub_file = self.sub_path.get()

            total_duration = self.get_video_duration(input_file)
            if total_duration > 0:
                self._thread_safe_log(f"⏱️ Video Toplam Süresi: {total_duration:.2f} saniye")

            if is_pure_cuda:
                codec_full = tab_vars["selected_codec"].get()
                codec_v = codec_full.split("(")[1].split(")")[0]
            else:
                codec_v = tab_vars["codec"]

            container = tab_vars["container"].get()
            a_bitrate = tab_vars["audio_bitrate"].get()
            cq_val = str(tab_vars["cq"].get())
            scale = tab_vars["scale"].get()

            meta_title = tab_vars["metadata_title"].get()
            meta_artist = tab_vars["metadata_artist"].get()
            meta_album = tab_vars["metadata_album"].get()
            meta_grouping = tab_vars["metadata_grouping"].get()

            use_bwdif = tab_vars["bwdif"].get() if "bwdif" in tab_vars else False
            use_temporal_aq = tab_vars["temporal_aq"].get() if "temporal_aq" in tab_vars else False
            use_multipass = tab_vars["multipass"].get() if "multipass" in tab_vars else False
            use_long_gop = tab_vars["long_gop"].get() if "long_gop" in tab_vars else False

            codec_a = "libopus" if container in ["mkv", "webm"] else "aac"

            klasor, dosya_adi = os.path.split(input_file)
            isim, _ = os.path.splitext(dosya_adi)

            # --- DİNAMİK DOSYA ADI MOTORU ---
            etiket_codec = "VP9" if is_vp9 else codec_v.split('_')[0].upper()
            etiket_scale = scale if scale != "Orijinal" else "Orijinal"
            etiket_bwdif = "_Deint" if use_bwdif else ""

            output_file = os.path.join(klasor, f"{isim}_{etiket_codec}_{etiket_scale}{etiket_bwdif}.{container}")

            # --- DOSYA ÜZERINE YAZMA KONTROLÜ ---
            if os.path.exists(output_file):
                cevap = messagebox.askyesno(
                    "Dosya Zaten Var",
                    f"'{os.path.basename(output_file)}' zaten mevcut.\n\nÜzerine yazmak istiyor musunuz?"
                )
                if not cevap:
                    self._thread_safe_log("⚠️ İşlem kullanıcı tarafından iptal edildi (dosya üzerine yazma reddedildi).")
                    return

            self.current_output_file = output_file

            cmd = ["ffmpeg", "-hwaccel", "cuda"]

            if is_pure_cuda:
                cmd.extend(["-hwaccel_output_format", "cuda"])
                if sub_file:
                    self._thread_safe_log("⚠️ UYARI: Saf CUDA modunda donanımsal altyazı desteği yoktur. Altyazı ATLANDI!")

            cmd.extend(["-i", input_file])

            vf_filters = []
            if use_bwdif:
                vf_filters.append("yadif_cuda" if is_pure_cuda else "bwdif")

            if scale != "Orijinal":
                w = SCALE_MAP.get(scale)
                if w is None:
                    self._thread_safe_log(f"⚠️ Bilinmeyen çözünürlük: {scale}, Orijinal kullanılıyor.")
                else:
                    if is_pure_cuda:
                        vf_filters.append(f"scale_cuda=w='if(gt(a,1),{w},-2)':h='if(gt(a,1),-2,{w})'")
                    else:
                        vf_filters.append(f"scale='if(gt(a,1),{w},-2)':'if(gt(a,1),-2,{w})':flags=lanczos")

            if not is_pure_cuda and sub_file:
                safe_sub_path = sub_file.replace('\\', '/').replace(':', '\\:')
                vf_filters.append(f"subtitles='{safe_sub_path}'")

            if vf_filters:
                cmd.extend(["-vf", ",".join(vf_filters)])

            cmd.extend(["-c:v", codec_v, "-b:v", "0"])

            if not is_vp9:
                cmd.extend(["-max_muxing_queue_size", "1024"])

            if container == "mp4":
                cmd.extend(["-movflags", "+faststart"])

            # --- VP9 (GOOGLE VOD) MOTORU ---
            if is_vp9:
                self._thread_safe_log("⚠️ DİKKAT: VP9 Kodlaması İŞLEMCİ (CPU) üzerinden %100 yükte yapılacaktır!")
                qual = tab_vars["vp9_quality"].get().split(" ")[0]
                spd = tab_vars["vp9_speed"].get().split(" ")[0]
                tiles = tab_vars["vp9_tiles"].get().split(" ")[0]
                thrd = tab_vars["vp9_threads"].get()

                cmd.extend([
                    "-crf", cq_val,
                    "-quality", qual,
                    "-speed", spd,
                    "-tile-columns", tiles,
                    "-row-mt", "1"
                ])
                if thrd != "Auto": cmd.extend(["-threads", thrd])
                cmd.extend(["-pix_fmt", "yuv420p"])

            # --- H.265 (HEVC) ---
            elif codec_v == "hevc_nvenc":
                preset = tab_vars["preset"].get()
                if container == "mp4":
                    cmd.extend(["-tag:v", "hvc1"])

                cmd.extend([
                    "-preset:v", preset,
                    "-rc:v", "vbr",
                    "-cq:v", cq_val,
                    "-tune:v", "uhq",
                    "-profile:v", "main10",
                    "-tier:v", "main",
                    "-level:v", "auto",
                    "-spatial-aq", "1",
                    "-rc-lookahead", "32",
                    "-bf", "4",
                    "-b_ref_mode", "middle",
                    "-highbitdepth", "true"
                ])
                if not is_pure_cuda: cmd.extend(["-pix_fmt", "p010le"])
                cmd.extend(["-temporal-aq", "1" if use_temporal_aq else "0"])

            # --- AV1 ---
            elif codec_v == "av1_nvenc":
                preset = tab_vars["preset"].get()
                cmd.extend([
                    "-preset:v", preset,
                    "-rc:v", "vbr",
                    "-cq:v", cq_val,
                    "-tune:v", "uhq",
                    "-rc-lookahead", "32",
                    "-spatial-aq", "1",
                    "-bf", "4",
                    "-b_ref_mode", "2",
                    "-highbitdepth", "true"
                ])
                if not is_pure_cuda: cmd.extend(["-pix_fmt", "p010le"])
                cmd.extend(["-temporal-aq", "1" if use_temporal_aq else "0"])

            # --- H.264 (AVC) ---
            elif codec_v == "h264_nvenc":
                preset = tab_vars["preset"].get()
                cmd.extend([
                    "-preset:v", preset,
                    "-rc:v", "vbr",
                    "-cq:v", cq_val,
                    "-tune:v", "hq",
                    "-rc-lookahead", "32",
                    "-spatial-aq", "1",
                    "-bf", "3",
                    "-b_ref_mode", "middle"
                ])
                if not is_pure_cuda: cmd.extend(["-pix_fmt", "yuv420p"])
                cmd.extend(["-temporal-aq", "1" if use_temporal_aq else "0"])

            # Ortak Ayarlar
            if use_multipass: cmd.extend(["-multipass", "2"])
            if use_long_gop: cmd.extend(["-g", "300"])

            cmd.extend(["-c:a", codec_a, "-b:a", a_bitrate])

            if meta_title.strip(): cmd.extend(["-metadata", f"title={meta_title}"])
            if meta_artist.strip(): cmd.extend(["-metadata", f"artist={meta_artist}"])
            if meta_album.strip(): cmd.extend(["-metadata", f"album={meta_album}"])
            if meta_grouping.strip(): cmd.extend(["-metadata", f"grouping={meta_grouping}"])

            cmd.extend(["-y", output_file])

            self._thread_safe_log("=" * 60)
            self._thread_safe_log(f"🎬 İŞLEM BAŞLIYOR: {active_tab_name} Sekmesi")
            self._thread_safe_log(f"⚙️ ÇALIŞTIRILAN FFmpeg KOMUTU:\n{' '.join(cmd)}")
            self._thread_safe_log("=" * 60)

            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            self._encode_start_time = time.time()

            for line in self.current_process.stdout:
                line = line.strip()

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
                self.after(0, self.progress_bar.set, 0)
                self.after(0, self.lbl_progress.configure, {"text": "% 0.0"})
                self.after(0, self.lbl_eta.configure, {"text": ""})

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
                self.after(0, self.lbl_progress.configure, {"text": "% 100.0"})
                self.after(0, self.lbl_eta.configure, {"text": "Tamamlandı!"})
                self._thread_safe_log("=" * 60)
                self._thread_safe_log(f"🎉 İŞLEM KUSURSUZ TAMAMLANDI!")

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
                self._thread_safe_log("❌ KRİTİK HATA OLUŞTU.")
                self.after(0, messagebox.showerror, "Hata", "FFmpeg bir hata döndürdü. Detaylar için siyah log ekranına bakın.")

        except Exception as e:
            self._thread_safe_log(f"❌ BEKLENMEYEN HATA: {str(e)}")
        finally:
            def _reset_buttons():
                self.btn_start.configure(state="normal", text="🚀 SEÇİLİ SEKMEYE GÖRE DÖNÜŞTÜR")
                self.btn_pause.configure(state="disabled", text="⏸️ Pause")
                self.btn_stop.configure(state="disabled")
                self.btn_delete.configure(state="disabled")
            self.after(0, _reset_buttons)
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
