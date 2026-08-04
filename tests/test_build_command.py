"""
build_command() ve saf yardimcilar icin birim testleri.

Bu testler GPU, ffmpeg ve arayuz OLMADAN calisir: build_command saf bir
fonksiyon oldugu ve olcum sonuclarini `probes` sozlugunden aldigi icin
tum komut matrisi masa basinda dogrulanabiliyor.

    pytest -q
"""
import importlib.util
import os
import sys

import pytest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "NvidiaConvertor.py")


def _load():
    """Uygulamayi modul olarak yukler (GUI baslatmaz: __main__ korumasi var)."""
    spec = importlib.util.spec_from_file_location("nvconv", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nv = _load()


# ---------------------------------------------------------------- yardimcilar
def cfg(**kw):
    """Makul varsayilanlarla bir is tanimi uretir; testler yalnizca farki yazar."""
    base = {
        "tab_name": "H.265 (Standart)",
        "is_pure_cuda": False,
        "is_vp9": False,
        "codec_v": "hevc_nvenc",
        "input_file": r"C:\video\kaynak.mkv",
        "sub_file": "",
        "container": "mkv",
        "a_bitrate": "128k",
        "cq_val": "31",
        "scale": "Orijinal",
        "preset": "p7",
        "meta_title": "", "meta_artist": "", "meta_album": "", "meta_grouping": "",
        "use_bwdif": False, "use_temporal_aq": True,
        "use_multipass": False, "use_long_gop": False,
        "no_upscale": True, "ten_bit": True, "interp_algo": "Otomatik",
        "color_preset": "Varsayılan (Devre Dışı)",
        "brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0,
        "codec_a": "libopus", "copy_audio": False,
        "upscale_blocked": False,
        "output_file": r"C:\video\cikti.mkv",
    }
    base.update(kw)
    return base


def probes(**kw):
    base = {"cuda_frames": False, "pix_fmt": "yuv420p",
            "sub_codecs": [], "audio_copy_ok": False}
    base.update(kw)
    return base


def vf_of(cmd):
    """Komuttaki -vf degerini dondurur (yoksa None)."""
    return cmd[cmd.index("-vf") + 1] if "-vf" in cmd else None


def val_of(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# ---------------------------------------------------------------- temel yapi
def test_komut_ffmpeg_ile_baslar_ve_ciktiyla_biter():
    cmd, _ = nv.build_command(cfg(), probes())
    assert cmd[0] == "ffmpeg"
    assert cmd[-2:] == ["-y", r"C:\video\cikti.mkv"]


def test_girdi_dosyasi_argv_olarak_gecer_kacis_yok():
    """Girdi yolu kabuktan gecmedigi icin ozel karakter kacisi GEREKMEZ."""
    yol = r"C:\Filmler\[Grup] Dizi, 01 'ozel'.mkv"
    cmd, _ = nv.build_command(cfg(input_file=yol), probes())
    assert cmd[cmd.index("-i") + 1] == yol


def test_akis_esleme_her_zaman_var():
    """Coklu ses izlerinin sessizce dusmesini engelleyen esleme."""
    cmd, _ = nv.build_command(cfg(), probes())
    assert "-map" in cmd
    assert "0:V:0" in cmd and "0:a?" in cmd


# ---------------------------------------------------------------- altyazi
@pytest.mark.parametrize("yol,beklenen_parca", [
    (r"C:\alt\normal.srt", r"C\\:/alt/normal.srt"),
    (r"C:\alt\bora's.srt", r"bora\\\'s.srt"),
    (r"C:\alt\[Grup] x.srt", r"\[Grup\] x.srt"),
    (r"C:\alt\a,b;c.srt", r"a\,b\;c.srt"),
])
def test_altyazi_yolu_iki_seviyeli_kaciriliyor(yol, beklenen_parca):
    cmd, _ = nv.build_command(cfg(sub_file=yol), probes())
    assert beklenen_parca in vf_of(cmd)


def test_hardsub_secildiyse_gomulu_altyazi_izi_eklenmez():
    cmd, _ = nv.build_command(cfg(sub_file=r"C:\a.srt", container="mkv"),
                              probes(sub_codecs=["subrip"]))
    assert "0:s?" not in cmd


def test_mkv_gomulu_altyazi_kopyalanir():
    cmd, notes = nv.build_command(cfg(container="mkv"), probes(sub_codecs=["subrip", "ass"]))
    assert "0:s?" in cmd and val_of(cmd, "-c:s") == "copy"
    assert any("altyazı izi korunuyor" in n for n in notes)


def test_mov_text_matroskaya_kopyalanamaz_srt_ye_cevrilir():
    cmd, _ = nv.build_command(cfg(container="mkv"), probes(sub_codecs=["mov_text"]))
    assert val_of(cmd, "-c:s") == "srt"


def test_mp4_ciktisinda_altyazi_izi_eslenmez():
    cmd, _ = nv.build_command(cfg(container="mp4"), probes(sub_codecs=["subrip"]))
    assert "0:s?" not in cmd


def test_saf_cuda_altyaziyi_atlar_ve_uyarir():
    cmd, notes = nv.build_command(
        cfg(is_pure_cuda=True, sub_file=r"C:\a.srt"), probes(cuda_frames=True))
    assert vf_of(cmd) is None or "subtitles" not in vf_of(cmd)
    assert any("Altyazı ATLANDI" in n for n in notes)


# ---------------------------------------------------------------- CUDA / NVDEC
def test_nvdec_varsa_gpu_filtreleri_kullanilir():
    cmd, _ = nv.build_command(
        cfg(is_pure_cuda=True, scale="720p", use_bwdif=True), probes(cuda_frames=True))
    assert "-hwaccel_output_format" in cmd
    assert "scale_cuda" in vf_of(cmd) and "yadif_cuda" in vf_of(cmd)


def test_nvdec_yoksa_cpu_filtrelerine_dusulur():
    cmd, notes = nv.build_command(
        cfg(is_pure_cuda=True, scale="720p", use_bwdif=True), probes(cuda_frames=False))
    assert "-hwaccel_output_format" not in cmd
    assert "flags=lanczos" in vf_of(cmd) and "bwdif" in vf_of(cmd)
    assert "scale_cuda" not in vf_of(cmd)
    assert any("NVDEC" in n for n in notes)


def test_nvdec_yoksa_pix_fmt_eklenir_varsa_eklenmez():
    """CUDA karelerinde -pix_fmt olmamali; sistem bellegi karelerinde olmali."""
    with_cuda, _ = nv.build_command(cfg(is_pure_cuda=True), probes(cuda_frames=True))
    without, _ = nv.build_command(cfg(is_pure_cuda=True), probes(cuda_frames=False))
    assert "-pix_fmt" not in with_cuda
    assert "-pix_fmt" in without


@pytest.mark.parametrize("pix_fmt,beklenen", [
    ("yuv420p", "nv12"),
    ("nv12", "nv12"),
    ("yuv420p10le", "p010le"),
    ("p010le", "p010le"),
    ("yuv420p12le", "p016le"),
    ("p016le", "p016le"),
])
def test_renk_filtresi_indirme_formati_bit_derinligine_gore(pix_fmt, beklenen):
    """Sabit nv12, 10/12-bit kaynaklarda ffmpeg'i komple durduruyordu."""
    cmd, _ = nv.build_command(
        cfg(is_pure_cuda=True, color_preset="Karanlık Video Kurtarma"),
        probes(cuda_frames=True, pix_fmt=pix_fmt))
    assert f"format={beklenen}" in vf_of(cmd)
    assert "hwdownload" in vf_of(cmd) and "hwupload_cuda" in vf_of(cmd)


def test_cpu_yolunda_renk_filtresi_sarmalanmaz():
    cmd, _ = nv.build_command(
        cfg(color_preset="Karanlık Video Kurtarma"), probes(cuda_frames=False))
    assert "hwdownload" not in vf_of(cmd)
    assert "eq=" in vf_of(cmd)


def test_ozel_renk_ayarlari_varsayilanken_filtre_eklenmez():
    cmd, _ = nv.build_command(cfg(color_preset="Özel Ayarlar"), probes())
    assert vf_of(cmd) is None


def test_ozel_renk_ayarlari_degistiyse_filtre_eklenir():
    cmd, _ = nv.build_command(cfg(color_preset="Özel Ayarlar", gamma=1.4), probes())
    assert "gamma=1.40" in vf_of(cmd)


# ---------------------------------------------------------------- olcekleme
def test_olcekleme_en_boy_oranini_korur():
    cmd, _ = nv.build_command(cfg(scale="720p"), probes())
    assert "if(gt(a,1),1280,-2)" in vf_of(cmd)


def test_interp_algo_varsayilanda_komuta_girmez():
    cmd, _ = nv.build_command(
        cfg(is_pure_cuda=True, scale="720p", interp_algo="Otomatik"), probes(cuda_frames=True))
    assert "interp_algo" not in vf_of(cmd)


def test_interp_algo_secilirse_komuta_girer():
    cmd, _ = nv.build_command(
        cfg(is_pure_cuda=True, scale="720p", interp_algo="lanczos"), probes(cuda_frames=True))
    assert "interp_algo=lanczos" in vf_of(cmd)


def test_buyutme_engellendiginde_olcekleme_filtresi_yok():
    """collect_config scale'i Orijinal'e cevirir; komutta olcekleme kalmamali."""
    cmd, notes = nv.build_command(
        cfg(scale="Orijinal", upscale_blocked=True, source_resolution="1920x1080"), probes())
    assert vf_of(cmd) is None
    assert any("ölçekleme atlandı" in n for n in notes)


def test_bilinmeyen_cozunurluk_uyarir_ve_olceklemez():
    cmd, notes = nv.build_command(cfg(scale="8K"), probes())
    assert vf_of(cmd) is None
    assert any("Bilinmeyen çözünürlük" in n for n in notes)


# ---------------------------------------------------------------- bit derinligi
def test_hevc_10bit_acikken_main10():
    cmd, _ = nv.build_command(cfg(ten_bit=True), probes())
    assert val_of(cmd, "-profile:v") == "main10"
    assert val_of(cmd, "-pix_fmt") == "p010le"
    assert "-highbitdepth" in cmd


def test_hevc_10bit_kapaliyken_main_ve_8bit():
    cmd, _ = nv.build_command(cfg(ten_bit=False), probes())
    assert val_of(cmd, "-profile:v") == "main"
    assert val_of(cmd, "-pix_fmt") == "yuv420p"
    assert "-highbitdepth" not in cmd


def test_cuda_karelerinde_8bit_icin_gpu_format_donusumu_gerekir():
    """-profile:v main tek basina yok sayilir; scale_cuda=format=nv12 sart."""
    cmd, _ = nv.build_command(
        cfg(is_pure_cuda=True, ten_bit=False), probes(cuda_frames=True))
    assert "scale_cuda=format=nv12" in vf_of(cmd)


def test_h264_highbitdepth_kullanmaz():
    cmd, _ = nv.build_command(cfg(codec_v="h264_nvenc"), probes())
    assert "-highbitdepth" not in cmd
    assert val_of(cmd, "-tune:v") == "hq"   # h264_nvenc'te uhq YOK


# ---------------------------------------------------------------- ses
def test_ses_varsayilan_olarak_kodlanir():
    cmd, _ = nv.build_command(cfg(a_bitrate="192k"), probes())
    assert val_of(cmd, "-c:a") == "libopus" and val_of(cmd, "-b:a") == "192k"


def test_ses_kopyalanabiliyorsa_kopyalanir():
    cmd, notes = nv.build_command(cfg(copy_audio=True), probes(audio_copy_ok=True))
    assert val_of(cmd, "-c:a") == "copy"
    assert "-b:a" not in cmd
    assert any("kopyalanıyor" in n for n in notes)


def test_ses_kopyalanamiyorsa_yeniden_kodlanir_ve_uyarilir():
    cmd, notes = nv.build_command(
        cfg(copy_audio=True, container="webm", codec_a="libopus"),
        probes(audio_copy_ok=False))
    assert val_of(cmd, "-c:a") == "libopus" and val_of(cmd, "-b:a") == "192k"
    assert any("kopyalanamıyor" in n for n in notes)


# ---------------------------------------------------------------- konteyner
def test_mp4_faststart_ve_hvc1_etiketi():
    cmd, _ = nv.build_command(cfg(container="mp4"), probes())
    assert val_of(cmd, "-movflags") == "+faststart"
    assert val_of(cmd, "-tag:v") == "hvc1"


def test_mkv_faststart_kullanmaz():
    cmd, _ = nv.build_command(cfg(container="mkv"), probes())
    assert "-movflags" not in cmd


# ---------------------------------------------------------------- vp9
def test_vp9_crf_kullanir_ve_cpu_uyarisi_verir():
    c = cfg(is_vp9=True, codec_v="libvpx-vp9", container="webm", cq_val="31",
            vp9_quality="good", vp9_speed="1", vp9_tiles="2", vp9_threads="Auto")
    cmd, notes = nv.build_command(c, probes())
    assert val_of(cmd, "-crf") == "31"
    assert "-cq:v" not in cmd
    assert "-max_muxing_queue_size" not in cmd
    assert any("İŞLEMCİ" in n for n in notes)


def test_vp9_threads_auto_ise_bayrak_eklenmez():
    c = cfg(is_vp9=True, codec_v="libvpx-vp9", container="webm",
            vp9_quality="good", vp9_speed="1", vp9_tiles="2", vp9_threads="Auto")
    cmd, _ = nv.build_command(c, probes())
    assert "-threads" not in cmd
    c["vp9_threads"] = "8"
    cmd, _ = nv.build_command(c, probes())
    assert val_of(cmd, "-threads") == "8"


# ---------------------------------------------------------------- metadata
def test_bos_metadata_komuta_girmez():
    cmd, _ = nv.build_command(cfg(), probes())
    assert "-metadata" not in cmd


def test_dolu_metadata_komuta_girer():
    cmd, _ = nv.build_command(cfg(meta_title="Ad", meta_artist="Sanatci"), probes())
    assert "title=Ad" in cmd and "artist=Sanatci" in cmd


def test_sadece_bosluk_iceren_metadata_yok_sayilir():
    cmd, _ = nv.build_command(cfg(meta_title="   "), probes())
    assert "-metadata" not in cmd


# ---------------------------------------------------------------- salterler
def test_multipass_ve_long_gop():
    cmd, _ = nv.build_command(cfg(use_multipass=True, use_long_gop=True), probes())
    assert val_of(cmd, "-multipass") == "2"
    assert val_of(cmd, "-g") == "300"


def test_temporal_aq_kapatilabilir():
    cmd, _ = nv.build_command(cfg(use_temporal_aq=False), probes())
    assert val_of(cmd, "-temporal-aq") == "0"


# ---------------------------------------------------------------- CQ tablolari
@pytest.mark.parametrize("codec", ["av1_nvenc", "hevc_nvenc", "h264_nvenc", "libvpx-vp9"])
@pytest.mark.parametrize("scale", ["240p", "360p", "480p", "720p", "1080p", "1440p", "4K"])
def test_varsayilan_cq_onerilen_araligin_ortasinda(codec, scale):
    lo, hi = nv.get_cq_range(codec, scale)
    varsayilan = nv.get_cq_default(codec, scale)
    assert lo <= varsayilan <= hi
    assert abs(varsayilan - (lo + hi) / 2) <= 0.5


def test_bilinmeyen_codec_hevc_tablosuna_duser():
    assert nv.get_cq_range("bilinmeyen", "1080p") == nv.get_cq_range("hevc_nvenc", "1080p")


# ---------------------------------------------------------------- saf yardimcilar
@pytest.mark.parametrize("pix_fmt,beklenen", [
    ("", "nv12"), ("yuv420p", "nv12"), ("yuv444p", "nv12"),
    ("yuv420p10le", "p010le"), ("p010le", "p010le"),
    ("yuv422p12le", "p016le"), ("p016le", "p016le"),
])
def test_cuda_download_format(pix_fmt, beklenen):
    assert nv.cuda_download_format(pix_fmt) == beklenen


def test_escape_filter_path_ters_bolu_ceviriyor():
    assert "/" in nv.escape_filter_path(r"C:\a\b.srt")
    assert "\\\\" not in nv.escape_filter_path(r"C:\a\b.srt").replace("\\\\:", "")


def test_scale_map_tum_secenekleri_kapsiyor():
    """Arayuzdeki her cozunurluk secenegi SCALE_MAP'te bulunmali."""
    secenekler = set(nv.FFmpegStudioPro.SCALE_VALUES) - {"Orijinal"}
    assert secenekler <= set(nv.SCALE_MAP)
