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
        # collect_config bunu donanima gore doldurur; NVENC sekmelerinin
        # urettigi deger "cuda". Testlerde de gercek deger kullanilmali,
        # yoksa komutlar uygulamanin hic uretmedigi bir sekli dogrular.
        "hwaccel": "cuda",
        "output_file": r"C:\video\cikti.mkv",
    }
    base.update(kw)
    return base


def amd_cfg(**kw):
    """AMD (AMF) sekmelerinin urettigi is tanimi."""
    base = cfg(codec_v="hevc_amf", hwaccel="d3d11va", cq_val="24",
               preset="", amf_quality="quality", container="mkv")
    base.update(kw)
    return base


def probes(**kw):
    base = {"cuda_frames": False, "pix_fmt": "yuv420p",
            "sub_codecs": [], "audio_copy_ok": False,
            "sub_charenc": "", "sub_needs_transcode": False}
    base.update(kw)
    return base


def remux_cfg(**kw):
    """Sadece-altyazi modu icin is tanimi (kodlayici ayarlari anlamsizdir)."""
    base = cfg(
        tab_name="💬 SADECE ALTYAZI",
        is_remux=True,
        codec_v="copy",
        container="mkv",
        sub_file=r"C:\alt\film.srt",
        cq_val="-",
        preset="",
        sub_lang="tur",
        sub_lang_label="Türkçe",
        sub_default=True,
        keep_embedded_subs=True,
        output_file=r"C:\video\cikti.mkv",
    )
    base.update(kw)
    return base


def vf_of(cmd):
    """Komuttaki -vf degerini dondurur (yoksa None)."""
    return cmd[cmd.index("-vf") + 1] if "-vf" in cmd else None


def val_of(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def sub_codecs_of(cmd):
    """Komuttaki -c:s:N bayraklarini {indeks: codec} olarak dondurur."""
    return {int(a.split(":")[2]): cmd[i + 1]
            for i, a in enumerate(cmd) if a.startswith("-c:s:")}


def maps_of(cmd):
    """Komuttaki tum -map degerlerini SIRAYLA dondurur."""
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]


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


# ---------------------------------------------------------------- level tavani
def test_hevc_level_tavani_kaldirilmis():
    """
    Olculdu: "-level:v auto" 16149 kbps'lik SERT bir tavan koyuyordu; CQ12,
    CQ16 ve CQ18 BAYT BAYT ayni dosyayi uretiyordu. 6.2 ile tavan kalkiyor.
    """
    cmd, _ = nv.build_command(cfg(codec_v="hevc_nvenc"), probes())
    assert val_of(cmd, "-level:v") == "6.2"
    assert val_of(cmd, "-level:v") != "auto"


def test_h264_level_tavani_kaldirilmis():
    """Olculdu: auto (Level 4.2) 41237 kbps'te tavan yapiyordu; 5.1 kaldiriyor."""
    cmd, _ = nv.build_command(cfg(codec_v="h264_nvenc"), probes())
    assert val_of(cmd, "-level:v") == "5.1"


def test_av1_level_ALMAZ():
    """
    AV1'de tavan YOK (olculdu: 19933 -> 117709 kbps temiz olcekleniyor).
    Level EKLEMEK zarar verir: 5.1 denendiginde 40194 kbps'te tavan olusuyordu.
    Bu test, ileride "tutarlilik olsun" diye AV1'e level eklenmesini engeller.
    """
    cmd, _ = nv.build_command(cfg(codec_v="av1_nvenc"), probes())
    assert "-level:v" not in cmd


def test_level_kullaniciya_bildirilir():
    """Level CQ'dan bagimsiz bitstream'e girer; uyumluluk sorununda sebebi gorunsun."""
    for codec, seviye in (("hevc_nvenc", "6.2"), ("h264_nvenc", "5.1")):
        _, notes = nv.build_command(cfg(codec_v=codec), probes())
        assert any(seviye in n and "level" in n.lower() for n in notes), codec
    _, notes = nv.build_command(cfg(codec_v="av1_nvenc"), probes())
    assert not any("level" in n.lower() for n in notes)


def test_h264_highbitdepth_kullanmaz():
    cmd, _ = nv.build_command(cfg(codec_v="h264_nvenc"), probes())
    assert "-highbitdepth" not in cmd
    assert val_of(cmd, "-tune:v") == "hq"   # h264_nvenc'te uhq YOK


# ================================================================
# AMD (AMF) VE DONANIM SECIMI
# ================================================================
def test_amd_cqp_ve_qp_kullanir_cq_kullanmaz():
    """
    AMF'nin kalite modeli NVENC'ten farkli: "-cq:v" YOK, "-rc cqp" + qp_i/qp_p.
    """
    cmd, _ = nv.build_command(amd_cfg(cq_val="24"), probes())
    assert val_of(cmd, "-rc") == "cqp"
    assert val_of(cmd, "-qp_i") == "24" and val_of(cmd, "-qp_p") == "24"
    assert "-cq:v" not in cmd
    assert "-preset:v" not in cmd          # AMF p1..p7 tanimaz


def test_amd_quality_onayari_komuta_girer():
    cmd, _ = nv.build_command(amd_cfg(amf_quality="balanced"), probes())
    assert val_of(cmd, "-quality") == "balanced"


def test_amd_b_kare_qp_si_yalnizca_destekleyen_kodeklere():
    """
    h264_amf ve av1_amf'te -qp_b VAR, hevc_amf'te YOK. Olmayanina vermek
    ffmpeg'in "not used for any stream" uyarisini uretir.
    """
    for codec in ("h264_amf", "av1_amf"):
        cmd, _ = nv.build_command(amd_cfg(codec_v=codec, cq_val="30"), probes())
        assert val_of(cmd, "-qp_b") == "30", codec
    cmd, _ = nv.build_command(amd_cfg(codec_v="hevc_amf"), probes())
    assert "-qp_b" not in cmd


# --------------------------------------------------- AMD QP olcekleri/tablolari
def test_av1_amf_qp_olcegi_255():
    """
    OLCULDU: av1_amf'in QP olcegi 0-255, digerleri 0-51. Kaydiriciyi 51'de
    tutunca AV1 kullanilamaz hale geliyordu: qp16 ile qp51 arasinda VMAF
    99.99 -> 99.98, bitrate 373 -> 157 Mbps. Yani kadran hicbir sey yapmiyordu.
    """
    assert nv.amf_qp_tavani("av1_amf") == 255
    assert nv.amf_qp_tavani("hevc_amf") == 51
    assert nv.amf_qp_tavani("h264_amf") == 51


@pytest.mark.parametrize("codec", ["hevc_amf", "h264_amf", "av1_amf"])
@pytest.mark.parametrize("scale", ["240p", "360p", "480p", "720p", "1080p", "1440p", "4K"])
def test_amd_varsayilan_qp_araligin_UST_SINIRI(codec, scale):
    """Sekme, onerilen bandin en tutumlu ucunda acilir (bkz. get_cq_default)."""
    lo, hi = nv.get_cq_range(codec, scale)
    assert nv.get_cq_default(codec, scale) == hi


@pytest.mark.parametrize("codec", ["hevc_amf", "h264_amf", "av1_amf"])
def test_amd_qp_araliklari_kendi_olceginin_icinde(codec):
    tavan = nv.amf_qp_tavani(codec)
    for scale in ("240p", "480p", "1080p", "4K", "Orijinal"):
        lo, hi = nv.get_cq_range(codec, scale)
        assert 0 < lo < hi <= tavan, (codec, scale, lo, hi)


def test_amd_tablolari_nvenc_tablosundan_KOPYA_DEGIL():
    """
    Olculdu: ayni QP iki markada ayni kaliteyi vermiyor. HEVC 1080p'de
    NVENC (28,34) iken AMF (31,35). Biri digerine kopyalanirsa bu test duser.
    """
    assert nv.get_cq_range("hevc_amf", "1080p") != nv.get_cq_range("hevc_nvenc", "1080p")
    assert nv.get_cq_range("h264_amf", "1080p") != nv.get_cq_range("h264_nvenc", "1080p")
    # AV1 zaten farkli olcekte
    assert nv.get_cq_range("av1_amf", "1080p")[0] > 100


def test_amf_minimum_kare_uygulama_secenekleriyle_uyumlu():
    """
    Uygulamanin EN KUCUK olcekleme secenegi (240p = 426x240) her AMD kodeginin
    sinirinin ustunde olmali, yoksa kullanici listeden secebildigi bir
    cozunurlukte "Init() failed error 5" alir.
    """
    en_kucuk = min(nv.SCALE_MAP.values())          # 240p -> 426
    for kodek, (min_w, min_h) in nv.AMF_MIN_KARE.items():
        assert en_kucuk >= min_w, kodek
        # 240p'nin 16:9 kisa kenari da sinirin ustunde mi?
        assert round(en_kucuk * 9 / 16) >= min_h, kodek


def test_amf_minimum_kare_kodege_gore_AYRI():
    """
    Olculdu (RX 9070 XT, ffmpeg 9.0.1, 2 piksellik adimlarla tarandi):
    h264 96x32, av1 320x128, hevc 384x128. Uc kodege tek bir "en kotu durum"
    degeri uygulanirsa h264/av1'in SORUNSUZ kodladigi dosyalar engellenir --
    kusur tam olarak buydu: 320x240 bir kaynakta uc AMD sekmesi de "cok kucuk"
    diyordu, oysa yalnizca H.265 cokuyor.
    """
    assert nv.AMF_MIN_KARE["h264_amf"] == (96, 32)
    assert nv.AMF_MIN_KARE["av1_amf"] == (320, 128)
    assert nv.AMF_MIN_KARE["hevc_amf"] == (384, 128)
    # Tablo AMF_CODECS ile ayni kumeyi kapsamali; eksik anahtar KeyError verir.
    assert set(nv.AMF_MIN_KARE) == set(nv.AMF_CODECS) == set(nv.AMF_SEKME_ADI)


def test_amf_kabul_eden_sekmeler_olculen_sinirlara_uyuyor():
    """Kullanicinin gercek dosyasi (320x240) H.264 ve AV1'de kodlanabiliyor."""
    assert nv.amf_kabul_eden_sekmeler(320, 240) == ["AV1 (AMD)", "H.264 (AMD)"]
    assert nv.amf_kabul_eden_sekmeler(384, 240) == ["AV1 (AMD)", "H.265 (AMD)",
                                                    "H.264 (AMD)"]
    # Dikey video: 240p'de genislik 240 kalir, yalnizca h264 kabul eder.
    assert nv.amf_kabul_eden_sekmeler(240, 426) == ["H.264 (AMD)"]
    # h264'un de altinda kalan kare: hicbir donanim sekmesi kodlayamaz.
    assert nv.amf_kabul_eden_sekmeler(64, 32) == []


def tamgpu_cfg(**kw):
    """TAM GPU sekmesinin urettigi is tanimi."""
    base = amd_cfg(tam_gpu=True, hwaccel="amf", tab_name=nv.TAMGPU_SEKME,
                   scale="Orijinal", cikti_boyutu=(1920, 1080), ten_bit=False,
                   amf_sr=False, amf_sr_algo="4", amf_frc=False)
    base.update(kw)
    return base


def test_tamgpu_hedef_boyut():
    assert nv.tamgpu_hedef_boyut(tamgpu_cfg(scale="Orijinal")) is None
    # AMF filtreleri ifade kabul etmiyor: iki boyut da acikca hesaplanmali
    assert nv.tamgpu_hedef_boyut(tamgpu_cfg(scale="720p")) == (1280, 720)
    # Dikey kaynak: uzun kenar yukseklige gider
    assert nv.tamgpu_hedef_boyut(
        tamgpu_cfg(scale="720p", cikti_boyutu=(1080, 1920))) == (720, 1280)
    # 4:3 kaynak
    assert nv.tamgpu_hedef_boyut(
        tamgpu_cfg(scale="720p", cikti_boyutu=(640, 480))) == (1280, 960)


def test_tamgpu_10bit_AYNI_vpp_filtresinde():
    """
    Olculdu: zincire ikinci bir AMF filtresi eklemek kararsizlastiriyor.
    10-bit bu yuzden olcekleme filtresinin ICINDE istenir; ayri bir
    vpp_amf=format eklenirse HQ buyutmeyle birlesince ffmpeg kilitleniyor.
    """
    vf, _ = nv.build_filters(tamgpu_cfg(scale="720p", ten_bit=True), probes())
    assert len(vf) == 1 and vf[0].startswith("vpp_amf=")
    assert "format=p010" in vf[0] and "w=1280:h=720" in vf[0]


def test_tamgpu_frc_ikinci_filtre_olarak_eklenir():
    vf, notes = nv.build_filters(
        tamgpu_cfg(scale="720p", ten_bit=True, amf_frc=True), probes())
    assert vf == ["vpp_amf=w=1280:h=720:scale_type=bicubic:format=p010", "frc_amf"]
    assert any("İKİ KATINA" in n for n in notes)


def test_tamgpu_HQ_buyutme_YALNIZ_calisir():
    """
    Olculdu (6'sar kosu): sr_amf tek basina 6/6 saglam; frc_amf ya da
    vpp_amf(format) ile birlesince 5/6; ucu bir arada ffmpeg KILITLENIYOR.
    Bu yuzden HQ acikken digerleri komuta GIRMEMELI.
    """
    vf, notes = nv.build_filters(
        tamgpu_cfg(scale="720p", amf_sr=True, ten_bit=True, amf_frc=True), probes())
    assert vf == ["sr_amf=w=1280:h=720:algorithm=4"]
    assert not any("vpp_amf" in f or "frc_amf" in f for f in vf)
    assert any("HQ büyütme" in n and "ATLANDI" in n for n in notes)


def test_tamgpu_renk_etiketi_yazilabiliyor():
    """setparams kareye dokunmaz (metadata), AMF yuzeyini bozmuyor - olculdu."""
    vf, _ = nv.build_filters(tamgpu_cfg(), probes(renk_etiketsiz=True))
    assert any(f.startswith("setparams=") for f in vf)


def test_tamgpu_yapamadiklarini_SOYLUYOR():
    vf, notes = nv.build_filters(tamgpu_cfg(sub_file=r"C:\a.srt", use_bwdif=True),
                                 probes())
    assert not any("subtitles" in f or "bwdif" in f for f in vf)
    assert any("altyazı gömme" in n for n in notes)


def test_tamgpu_kendi_sekmesinde_cozucu_listesinde_DEGIL():
    """
    Kusur: TAM GPU bir "kod cozucu" secenegiyken secildiginde altyazi/renk/
    taraklanma SESSIZCE atlaniyordu. Artik kendi sekmesinde ve o sekmede bu
    secenekler hic gosterilmiyor.
    """
    assert not any("TAM GPU" in ad for ad in nv.COZUCU_SECENEKLERI)
    assert nv.TAMGPU_SEKME in nv.DONANIM[nv.AMD]["sekmeler"]


def test_ses_varsayilani_KOPYALA():
    """
    Olculdu (1.mp4, 83 dk): 32 kbps AAC kaynak 128 kbps Opus'a kodlanınca ses
    19 MB -> 72 MB oldu ve cikti kaynaktan BUYUK cikti; video tarafi ise
    77.5 -> 70.2 MB ile kuculmustu. Varsayilan yeniden kodlama olmamali.
    """
    assert nv.FFmpegStudioPro.AUDIO_VALUES[0] == nv.SES_KOPYALA
    assert nv.SES_KOPYALA.startswith("Kopyala")   # collect_config bunu boyle anliyor


def test_ses_bitrate_kaynagi_asmiyor():
    """Hedef, kaynagin USTUNDEKI ilk adimi asamaz; bir kademe pay kalir."""
    # Kullanicinin gercek dosyasi: 32 kbps kaynak, 128k secili -> 64k
    deger, not_ = nv.ses_bitrate_sinirla("128k", 32)
    assert deger == "64k" and "32 kbps" in not_
    # Kaynak zaten yuksekse secime dokunulmaz
    assert nv.ses_bitrate_sinirla("128k", 128) == ("128k", None)
    assert nv.ses_bitrate_sinirla("128k", 190) == ("128k", None)
    # Kullanici zaten dusuk sectiyse YUKSELTILMEZ
    assert nv.ses_bitrate_sinirla("64k", 320) == ("64k", None)
    # Kaynak okunamadi (MKV'lerde yaygin): dokunma
    assert nv.ses_bitrate_sinirla("128k", None) == ("128k", None)
    # "Kopyala" gibi sayiya cevrilemeyen deger: dokunma
    assert nv.ses_bitrate_sinirla(nv.SES_KOPYALA, 32) == (nv.SES_KOPYALA, None)


def test_komutta_ses_bitrate_sinirlaniyor():
    cmd, notes = nv.build_command(amd_cfg(a_bitrate="128k", copy_audio=False),
                                  probes(audio_bitrate=32))
    assert cmd[cmd.index("-b:a") + 1] == "64k"
    assert any("kaybolmuş kaliteyi" in n.lower() or "kaybolmuş" in n for n in notes)
    # Kaynak bilinmiyorsa secim aynen gecer
    cmd, _ = nv.build_command(amd_cfg(a_bitrate="128k", copy_audio=False), probes())
    assert cmd[cmd.index("-b:a") + 1] == "128k"


def test_hata_logu_dosyaya_yazilir(tmp_path):
    """
    Hata dokumu YALNIZCA is coktugunde calisir, yani normal kullanimda hic
    denenmez ve sessizce bozulabilir. En kritik iki parca komut ile ffmpeg'in
    son ciktisi: ikisi de yoksa dosyanin varligi bir ise yaramaz.
    """
    app = nv.FFmpegStudioPro.__new__(nv.FFmpegStudioPro)   # arayuz kurulmaz
    app._ffmpeg_tail = ["[hevc_amf] encoder->Init() failed with error 5",
                        "Conversion failed!"]
    cikti = tmp_path / "deneme.mkv"
    c = amd_cfg(input_file=str(tmp_path / "kaynak.mkv"), output_file=str(cikti))
    yol = app._hata_logu_yaz(c, ["ffmpeg", "-i", "kaynak.mkv", "cikti.mkv"], 1,
                             str(cikti) + ".bozuk")

    assert yol == str(cikti) + ".hata.log"
    metin = open(yol, encoding="utf-8").read()
    assert "Cikis kodu   : 1" in metin
    assert "hevc_amf" in metin                     # is ayarlari
    assert "-i kaynak.mkv" in metin                # calistirilan komut
    assert "Init() failed with error 5" in metin   # ffmpeg'in son ciktisi
    assert "Conversion failed!" in metin


def test_hata_logu_yazilamayan_klasorde_TEMP_e_duser(tmp_path):
    """Cikti klasoru yazilamazsa hatayi kaybetmektense TEMP'e yazilmali."""
    app = nv.FFmpegStudioPro.__new__(nv.FFmpegStudioPro)
    app._ffmpeg_tail = ["bir hata"]
    olmayan = tmp_path / "yok" / "olmayan_klasor" / "cikti.mkv"
    yol = app._hata_logu_yaz(amd_cfg(output_file=str(olmayan)), ["ffmpeg"], 1)
    assert yol and os.path.isdir(os.path.dirname(yol))
    assert "bir hata" in open(yol, encoding="utf-8").read()


def _sorun(**kw):
    """_job_sorunu'yu arayuz olmadan cagirir (fonksiyon self kullanmiyor)."""
    c = amd_cfg(input_file=os.path.abspath(__file__), output_dir="",
                is_remux=False, trim_start="", trim_end="", **kw)
    return nv.FFmpegStudioPro._job_sorunu(None, c)


def test_kucuk_kare_calisan_sekmede_ENGELLENMEZ():
    """Ana kusur: 320x240 kaynak h264/av1'de calisirken de engelleniyordu."""
    assert _sorun(codec_v="h264_amf", cikti_boyutu=(320, 240)) is None
    assert _sorun(codec_v="av1_amf", cikti_boyutu=(320, 240)) is None
    # h264'un kendi sinirinin altinda ise yine engellenir.
    assert _sorun(codec_v="h264_amf", cikti_boyutu=(64, 240)) is not None


def test_kucuk_kare_uyarisi_CALISAN_SEKMEYI_onerir():
    """
    Uyari cikmak zorundaysa (H.265, 320x240) tavsiye ise yarar olmali:
    kullaniciyi VP9'a (CPU, kat kat yavas) yollamadan once kareyi oldugu gibi
    kabul eden donanim sekmelerini soylemeli.
    """
    baslik, metin = _sorun(codec_v="hevc_amf", cikti_boyutu=(320, 240))
    assert "H.265 (AMD)" in baslik
    assert "320x240" in metin and "384x128" in metin
    assert "AV1 (AMD)" in metin and "H.264 (AMD)" in metin
    assert "VP9" not in metin          # calisan donanim yolu varken gereksiz


def test_hicbir_amd_sekmesi_kodlayamiyorsa_VP9_onerilir():
    """h264'un de altindaki kare: tek cikis CPU (VP9) ya da buyutme."""
    _, metin = _sorun(codec_v="hevc_amf", cikti_boyutu=(64, 32))
    assert "VP9" in metin


def test_orijinal_secilince_band_KAYNAGIN_cozunurlugunden_gelir():
    """
    Kusur: "Orijinal" tabloda bir satir adi degil, o yuzden dogrudan "default"
    (1080p turevi) satira dusuluyordu. 4K bir kaynakta bu sessizce yanlis
    tavsiye uretiyordu -- av1_amf'te olculen 4K bandi 70-104 iken sekme
    144'te aciliyor ve 144, gercek 4K icerikte VMAF 90'in ALTINA denk geliyor.
    """
    assert nv.get_cq_range("av1_amf", "Orijinal") == (144, 160)          # kaynak bilinmiyor
    assert nv.get_cq_range("av1_amf", "Orijinal", (3840, 2160)) == (70, 104)
    assert nv.get_cq_default("av1_amf", "Orijinal", (3840, 2160)) == 104
    # Kucuk kaynak da dogru bandi almali (kullanicinin 320x240 dosyasi).
    assert nv.get_cq_range("av1_amf", "Orijinal", (320, 240)) == (115, 136)
    # Acikca bir olcek secildiyse kaynak boyutu KARISMAZ.
    assert nv.get_cq_range("av1_amf", "1080p", (3840, 2160)) == (144, 160)


def test_cozunurluk_bandi_en_yakin_satiri_secer():
    assert nv.cozunurluk_bandi(3840, 2160) == "4K"
    assert nv.cozunurluk_bandi(1920, 1080) == "1080p"
    assert nv.cozunurluk_bandi(2160, 3840) == "4K"        # dikey video
    assert nv.cozunurluk_bandi(320, 240) == "240p"        # en kucuk satirin altinda
    assert nv.cozunurluk_bandi(7680, 4320) == "4K"        # olcum yok: en yakin satir
    assert nv.cozunurluk_bandi(3500, 1970) == "4K"        # 1440p'den cok 4K'ya yakin
    assert nv.cozunurluk_bandi(0, 0) is None              # okunamadi
    # Tablodaki her satirin karsiligi CQ_RANGES'te GERCEKTEN olmali.
    for ad in nv.SCALE_MAP:
        for kodek in nv.CQ_RANGES:
            assert ad in nv.CQ_RANGES[kodek], (kodek, ad)


def test_amd_dusuk_cozunurlukte_qp_araligi_dusuyor():
    """
    480p -> 1080p arasinda olculen egilim: cozunurluk arttikca ayni kalite
    daha yuksek QP'de saglaniyor.

    DIKKAT: bu egilim 1080p'nin USTUNE UZATILAMAZ. Once oyle yapip 4K satirini
    turetmistim (av1 icin 156-172) ve gercek 4K icerik bunu curuttu: QP144
    bile VMAF 82.8 verdi. Egim, ayni kaynagin KUCULTULMUS hallerinden
    cikmisti; kucultunce detay yogunlasir, yukari dogru gecerli degil.
    """
    for codec in ("hevc_amf", "h264_amf", "av1_amf"):
        assert nv.get_cq_range(codec, "480p")[0] <= nv.get_cq_range(codec, "1080p")[0], codec


def test_av1_4k_satiri_TURETILMIS_DEGIL_olculmus():
    """
    4K satiri gercek 4K olcumunden gelir, 1080p'den uzatilarak DEGIL.
    Turetilmis deger (156, 172) idi ve kanitla celisti; bu test onun geri
    gelmesini engeller.
    """
    dort_k = nv.get_cq_range("av1_amf", "4K")
    assert dort_k == (70, 104), dort_k
    # Turetme "4K'da daha YUKSEK QP" diyordu; olcum tersini soyledi.
    assert dort_k[0] < nv.get_cq_range("av1_amf", "1080p")[0]


@pytest.mark.parametrize("ten_bit,beklenen", [(True, "p010le"), (False, "nv12")])
def test_amd_bit_derinligi(ten_bit, beklenen):
    cmd, _ = nv.build_command(amd_cfg(ten_bit=ten_bit), probes())
    assert val_of(cmd, "-pix_fmt") == beklenen


def test_amd_h264_10bit_ALMAZ():
    """
    Olculdu: h264_amf'e p010le verilince "10-bit input video is not supported
    by AMF H264 encoder" deyip is HIC baslamiyor. ffmpeg'in "Supported pixel
    formats" listesi p010le yazsa da yanlis; 10-bit sessizce 8-bit'e dusurulur
    ve kullaniciya soylenir.
    """
    cmd, notes = nv.build_command(
        amd_cfg(codec_v="h264_amf", ten_bit=True), probes())
    assert val_of(cmd, "-pix_fmt") == "nv12"
    assert any("10-bit" in n and "H.264" in n for n in notes)


def test_amd_hevc_ve_av1_10bit_alir():
    for codec in ("hevc_amf", "av1_amf"):
        cmd, notes = nv.build_command(amd_cfg(codec_v=codec, ten_bit=True), probes())
        assert val_of(cmd, "-pix_fmt") == "p010le", codec
        assert not any("10-bit" in n for n in notes), codec


def test_amd_level_ALMAZ():
    """
    Olculdu: AMF'de level bitrate'i kisitlamiyor (level 153 ile 186 bayt bayt
    ayni cikti). NVENC'teki tavan kusuru burada yok; level eklemek gereksiz
    ve bitstream'i bosuna yuksek sinifa isaretler.
    """
    for codec in nv.AMF_CODECS:
        cmd, _ = nv.build_command(amd_cfg(codec_v=codec), probes())
        assert "-level:v" not in cmd and "-level" not in cmd, codec


def test_amd_nvenc_bayraklarini_kullanmaz():
    """NVENC'e ozgu bayraklar AMF'de karsiliksiz; komuta sizmamali."""
    cmd, _ = nv.build_command(
        amd_cfg(use_temporal_aq=True, use_multipass=True), probes())
    for bayrak in ("-temporal-aq", "-spatial-aq", "-rc-lookahead", "-b_ref_mode",
                   "-tune:v", "-highbitdepth", "-multipass"):
        assert bayrak not in cmd, bayrak


def test_amd_kullanildigi_bildirilir():
    _, notes = nv.build_command(amd_cfg(), probes())
    assert any("AMD" in n for n in notes)


# ---------------------------------------------------------------- log metni
def test_loglanan_komut_bosluklu_yollari_tirnakliyor():
    """
    Komut kabuktan gecmedigi icin CALISMASI tirnak istemiyor; ama loga duz
    join ile yazilinca kullanici kopyalayip terminale yapistiramiyordu.
    """
    metin = nv.komut_metni(["ffmpeg", "-i", r"C:\Video Klasoru\a b.mkv", "-y", "out.mkv"])
    assert '"C:\\Video Klasoru\\a b.mkv"' in metin
    assert metin.startswith("ffmpeg -i ")
    assert '"out.mkv"' not in metin      # bosluksuzlar tirnaklanmaz


def test_loglanan_komut_gercek_bir_isten_uretilebiliyor():
    cmd, _ = nv.build_command(cfg(input_file=r"C:\a b\v.mkv"), probes())
    assert '"C:\\a b\\v.mkv"' in nv.komut_metni(cmd)


# ---------------------------------------------------------------- hwaccel
def test_hwaccel_markaya_gore_secilir():
    """
    Olculdu: AMD makinede "-hwaccel cuda" verilince ffmpeg "Cannot load
    nvcuda.dll / Device creation failed" deyip cikti dosyasini HIC olusturmuyor.
    Yanlis marka bayragi = calismayan uygulama.
    """
    nvidia, _ = nv.build_command(cfg(codec_v="hevc_nvenc"), probes())
    amd, _ = nv.build_command(amd_cfg(), probes())
    assert val_of(nvidia, "-hwaccel") == "cuda"
    assert val_of(amd, "-hwaccel") == "d3d11va"


def test_av1_kaynak_donanim_cozucu_istemeyenler_listesinde():
    """
    Olculdu (1080p, 3'er kosu, cikti bayt bayt ayni):
      AV1  kaynak: d3d11va 2090 ms | yazilim 1431 ms  -> yazilim %46 hizli
      H264 kaynak: d3d11va  950 ms | yazilim 1042 ms  -> donanim %10 hizli
    AMD'de GPU filtre zinciri kurulamadigi icin kareler zaten RAM'e donuyor;
    donanim cozucu fazladan bir kopya ekliyor ve kolay akislarda bu baskin.
    """
    assert "av1" in nv.D3D11VA_ISTEMEYEN_KODEKLER
    assert "h264" not in nv.D3D11VA_ISTEMEYEN_KODEKLER
    assert "hevc" not in nv.D3D11VA_ISTEMEYEN_KODEKLER


def test_hwaccel_bos_ise_bayrak_hic_eklenmez():
    """Donanim yoksa yazilim cozucusu; bos bir -hwaccel degeri gecmemeli."""
    cmd, _ = nv.build_command(cfg(hwaccel=""), probes())
    assert "-hwaccel" not in cmd


def test_onizleme_de_ayni_hwaccel_i_kullanir():
    """Onizleme NVIDIA'ya sabitlenirse AMD makinede kare uretemez."""
    cmd = nv.build_preview_command(amd_cfg(), probes(), "x.png")
    assert val_of(cmd, "-hwaccel") == "d3d11va"


def test_donanim_tanimlari_tutarli():
    """Her markanin sekmeleri ve deneme kodlayicisi tanimli olmali."""
    for marka, bilgi in nv.DONANIM.items():
        assert bilgi["deneme"] and bilgi["sekmeler"], marka
    # Marka sekmeleri ile donanimsiz sekmeler cakismamali
    marka_sekmeleri = {s for b in nv.DONANIM.values() for s in b["sekmeler"]}
    assert not (marka_sekmeleri & set(nv.DONANIMSIZ_SEKMELER))


def test_deneme_boyutu_amf_minimumunun_ustunde():
    """
    Olculdu: 256x256'da hevc_amf/av1_amf "encoder->Init() failed with error 5"
    veriyor. Kucuk bir deneme boyutu CALISAN bir karti "yok" gosterirdi.
    """
    g, y = (int(x) for x in nv.DENEME_BOYUTU.split("x"))
    assert g >= 640 and y >= 360


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
def test_varsayilan_cq_onerilen_araligin_UST_SINIRI(codec, scale):
    """
    Sekme, onerilen bandin UST ucunda acilir: olculen VMAF ~90 noktasi, yani
    "gorunur kayip baslamadan onceki en kucuk dosya". Alt uc (VMAF ~96) arsiv
    icin dogruydu ama dosyalari gereksiz buyutuyordu; band DISINA cikilmiyor,
    iki uc de olculmus degerler.
    """
    lo, hi = nv.get_cq_range(codec, scale)
    assert nv.get_cq_default(codec, scale) == hi
    assert lo < hi                       # aralik gercekten bir aralik olsun


def test_varsayilan_ayri_tabloda_TUTULMAZ():
    """
    Iki tablonun ayrismasi bu projede bir kez kusur uretmisti (av1_nvenc'te
    "1080p" anahtari eksikti, "default" devreye girip araligin tepesine
    dusuyordu). Varsayilan artik CQ_RANGES'ten turetiliyor.
    """
    assert not hasattr(nv, "CQ_DEFAULTS")


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


# ---------------------------------------------------------------- kirpma
@pytest.mark.parametrize("metin,beklenen", [
    ("90", 90.0), ("01:30", 90.0), ("00:01:30.5", 90.5), ("2:00:00", 7200.0),
    ("", None), ("   ", None), (None, None),
    ("abc", None), ("-5", None), ("1:2:3:4", None), ("1:-2", None),
])
def test_parse_time(metin, beklenen):
    assert nv.parse_time(metin) == beklenen


def test_trim_args_bas_ve_bitis():
    """-ss girdiden once geldigi icin bitis, sure farki (-t) olarak verilir."""
    assert nv.trim_args({"trim_start": "00:10", "trim_end": "00:25"}) == ["-ss", "10.000", "-t", "15.000"]


def test_trim_args_sadece_bas():
    assert nv.trim_args({"trim_start": "5"}) == ["-ss", "5.000"]


def test_trim_args_sadece_bitis():
    assert nv.trim_args({"trim_end": "12"}) == ["-t", "12.000"]


def test_trim_args_bos():
    assert nv.trim_args({}) == []
    assert nv.trim_args({"trim_start": "", "trim_end": ""}) == []


def test_trim_args_gecersiz_aralik_yok_sayilir():
    """Bitis baslangictan kucukse -t uretilmez (negatif sure olusmasin)."""
    assert nv.trim_args({"trim_start": "30", "trim_end": "10"}) == ["-ss", "30.000"]


def test_kirpma_komutta_girdiden_once():
    cmd, _ = nv.build_command(cfg(trim_start="10", trim_end="20"), probes())
    assert cmd.index("-ss") < cmd.index("-i")


# ---------------------------------------------------------------- onizleme
def test_onizleme_kodlamayla_ayni_filtreleri_kullanir():
    c = cfg(scale="720p", color_preset="Karanlık Video Kurtarma")
    p = probes()
    kodlama, _ = nv.build_command(c, p)
    onizleme = nv.build_preview_command(c, p, "x.png")
    assert vf_of(kodlama) == vf_of(onizleme)


def test_onizleme_cuda_zincirini_ram_e_indirir():
    c = cfg(is_pure_cuda=True, scale="720p")
    cmd = nv.build_preview_command(c, probes(cuda_frames=True), "x.png")
    assert vf_of(cmd).endswith("hwdownload,format=nv12")


def test_onizleme_renk_filtresinden_sonra_cift_indirme_yapmaz():
    """hwupload_cuda ile biten zincire ikinci hwdownload eklemek ffmpeg'i durduruyordu."""
    c = cfg(is_pure_cuda=True, color_preset="Karanlık Video Kurtarma")
    cmd = nv.build_preview_command(c, probes(cuda_frames=True), "x.png")
    vf = vf_of(cmd)
    assert "hwupload_cuda" not in vf
    assert vf.count("hwdownload") == 1


def test_onizleme_tek_kare_ve_png():
    cmd = nv.build_preview_command(cfg(), probes(), "cikti.png", 12.5)
    assert val_of(cmd, "-frames:v") == "1"
    assert cmd[-1] == "cikti.png"
    assert val_of(cmd, "-ss") == "12.500"


# ---------------------------------------------------------------- 12-bit sinir
def test_12bit_renk_gidis_donusu_desteklenmiyor():
    """ffmpeg 9.0'da 12-bit CUDA karesi RAM'e indirilemiyor."""
    assert nv.cuda_color_roundtrip_ok("yuv420p") is True
    assert nv.cuda_color_roundtrip_ok("yuv420p10le") is True
    assert nv.cuda_color_roundtrip_ok("yuv420p12le") is False


def test_color_filter_of():
    assert nv.color_filter_of(cfg()) == ""
    assert nv.color_filter_of(cfg(color_preset="Özel Ayarlar")) == ""
    assert "gamma=1.40" in nv.color_filter_of(cfg(color_preset="Özel Ayarlar", gamma=1.4))
    assert nv.color_filter_of(cfg(color_preset="Karanlık Video Kurtarma")).startswith("eq=")


def test_12bit_cpu_yolunda_renk_filtresi_sarmalanmaz():
    """cuda_frames=False geldiginde zincir hwdownload icermemeli."""
    cmd, _ = nv.build_command(
        cfg(is_pure_cuda=True, color_preset="Karanlık Video Kurtarma"),
        probes(cuda_frames=False, pix_fmt="yuv420p12le"))
    assert "hwdownload" not in vf_of(cmd)
    assert "eq=" in vf_of(cmd)


# ================================================================
# SADECE ALTYAZI EKLE (KODEK KORUNUR)
# ================================================================
# Buradaki beklentiler ffmpeg 9.0 uzerinde gercek dosyalarla olculdu;
# ilgili olcumun ozeti her testin docstring'inde.

def test_remux_video_ve_sesi_yeniden_kodlamaz():
    """Modun tek varlik sebebi: hicbir kodlayici devreye girmemeli."""
    cmd, _ = nv.build_command(remux_cfg(), probes())
    assert val_of(cmd, "-c:v") == "copy"
    assert val_of(cmd, "-c:a") == "copy"
    for kodlayici_bayragi in ("-cq:v", "-crf", "-preset:v", "-b:a", "-vf",
                              "-hwaccel", "-pix_fmt", "-profile:v", "-multipass"):
        assert kodlayici_bayragi not in cmd, kodlayici_bayragi


def test_remux_iki_girdi_alir_altyazi_ikincidir():
    cmd, _ = nv.build_command(
        remux_cfg(input_file=r"C:\v\a.mkv", sub_file=r"C:\s\b.srt"), probes())
    girdiler = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
    assert girdiler == [r"C:\v\a.mkv", r"C:\s\b.srt"]


def test_remux_altyazi_yolu_argv_olarak_gecer_kacis_yok():
    """Filtre grafigine girmedigi icin escape_filter_path UYGULANMAMALI."""
    yol = r"C:\alt\[Grup] Dizi, 01 'ozel'.srt"
    cmd, _ = nv.build_command(remux_cfg(sub_file=yol), probes())
    assert yol in cmd
    assert vf_of(cmd) is None


def test_remux_utf8_altyazi_kopyalanir():
    """Olculdu: UTF-8 srt matroska'ya bayt bayt kopyalanabiliyor."""
    cmd, notes = nv.build_command(remux_cfg(), probes(sub_needs_transcode=False))
    assert sub_codecs_of(cmd) == {0: "copy"}
    assert "-sub_charenc" not in cmd
    assert any("UTF-8" in n and "kopyalan" in n for n in notes)


def test_remux_utf8_olmayan_altyazi_charenc_ile_cevrilir():
    """
    Olculdu: CP1254 bir srt "copy" ile gecirilirse matroska'ya UTF-8 olmayan
    bayt girer (oynaticida bozuk karakter); charenc verilmeden "-c:s srt" ile
    cevrilmeye kalkilirsa ffmpeg is'i 69 koduyla birakir.
    """
    cmd, notes = nv.build_command(
        remux_cfg(), probes(sub_charenc="CP1254", sub_needs_transcode=True))
    assert val_of(cmd, "-sub_charenc") == "CP1254"
    assert sub_codecs_of(cmd) == {0: "srt"}
    assert any("CP1254" in n for n in notes)


def test_remux_charenc_altyazi_girdisinden_once_gelir():
    """-sub_charenc girdi basina bir secenektir; -i'den sonra gelirse etkisiz."""
    cmd, _ = nv.build_command(
        remux_cfg(), probes(sub_charenc="CP1254", sub_needs_transcode=True))
    girdi_indeksleri = [i for i, a in enumerate(cmd) if a == "-i"]
    assert girdi_indeksleri[0] < cmd.index("-sub_charenc") < girdi_indeksleri[1]


@pytest.mark.parametrize("uzanti,beklenen", [
    (".srt", "srt"), (".vtt", "srt"), (".ass", "ass"), (".ssa", "ass"),
])
def test_remux_cevrim_gerekirse_stilli_altyazi_ass_kalir(uzanti, beklenen):
    """Stilli altyaziyi srt'ye dusurmek renk/italik bilgisini siler."""
    cmd, _ = nv.build_command(
        remux_cfg(sub_file=r"C:\alt\film" + uzanti),
        probes(sub_charenc="CP1254", sub_needs_transcode=True))
    assert sub_codecs_of(cmd)[0] == beklenen


def test_remux_mkv_gomulu_izleri_korur_ve_harici_sona_eklenir():
    cmd, notes = nv.build_command(
        remux_cfg(container="mkv"), probes(sub_codecs=["subrip", "ass"]))
    assert maps_of(cmd) == ["0:V:0", "0:a?", "0:s:0", "0:s:1", "1:0", "0:t?"]
    assert sub_codecs_of(cmd) == {0: "copy", 1: "copy", 2: "copy"}
    assert any("2 altyazı izi de korunuyor" in n for n in notes)


def test_remux_mkv_gomulu_mov_text_srt_ye_cevrilir():
    """
    Olculdu: mov_text matroska'ya kopyalanamaz -> "Could not write header
    (incorrect codec parameters ?)". Iz iz codec vermek sart.
    """
    cmd, _ = nv.build_command(
        remux_cfg(container="mkv"), probes(sub_codecs=["mov_text"]))
    assert sub_codecs_of(cmd) == {0: "srt", 1: "copy"}


def test_remux_mkv_resim_tabanli_izleri_kopyalar():
    """MKV, PGS/VobSub izlerini sorunsuz tasir; atmaya gerek yok."""
    cmd, notes = nv.build_command(
        remux_cfg(container="mkv"), probes(sub_codecs=["hdmv_pgs_subtitle"]))
    assert sub_codecs_of(cmd) == {0: "copy", 1: "copy"}
    assert not any("ATLANDI" in n for n in notes)


def test_remux_gomulu_izler_kapatilabilir():
    cmd, _ = nv.build_command(
        remux_cfg(keep_embedded_subs=False), probes(sub_codecs=["subrip", "ass"]))
    assert maps_of(cmd) == ["0:V:0", "0:a?", "1:0", "0:t?"]
    assert sub_codecs_of(cmd) == {0: "copy"}


def test_remux_mp4_mov_text_kullanir_ve_faststart_ekler():
    """Olculdu: MP4'e srt'yi "copy" ile yazmak 127 ile basarisiz oluyor."""
    cmd, notes = nv.build_command(remux_cfg(container="mp4"), probes())
    assert sub_codecs_of(cmd) == {0: "mov_text"}
    assert val_of(cmd, "-movflags") == "+faststart"
    assert any("mov_text" in n for n in notes)


def test_remux_mp4_resim_tabanli_izleri_atlar_ve_uyarir():
    """Resim altyazi metne cevrilemez; MP4 ciktida tasinamaz."""
    cmd, notes = nv.build_command(
        remux_cfg(container="mp4"),
        probes(sub_codecs=["hdmv_pgs_subtitle", "subrip"]))
    assert maps_of(cmd) == ["0:V:0", "0:a?", "0:s:1", "1:0"]
    assert sub_codecs_of(cmd) == {0: "mov_text", 1: "mov_text"}
    assert any("ATLANDI" in n and "MKV" in n for n in notes)


def test_remux_mp4_gomulu_mov_text_bosuna_cevrilmez():
    cmd, _ = nv.build_command(
        remux_cfg(container="mp4"), probes(sub_codecs=["mov_text"]))
    assert sub_codecs_of(cmd) == {0: "copy", 1: "mov_text"}


def test_remux_ekler_yalnizca_mkvye_tasinir():
    """ASS fontlari konteyner ekidir; MP4 ek tasiyamaz."""
    mkv, _ = nv.build_command(remux_cfg(container="mkv"), probes())
    mp4, _ = nv.build_command(remux_cfg(container="mp4"), probes())
    assert "0:t?" in maps_of(mkv)
    assert "0:t?" not in maps_of(mp4)


def test_remux_bolumler_ilk_girdiden_alinir():
    """Cok girdili komutta ffmpeg bolum kaynagini kendi seciyor."""
    cmd, _ = nv.build_command(remux_cfg(), probes())
    assert val_of(cmd, "-map_chapters") == "0"


def test_remux_dil_ve_baslik_harici_izin_indeksine_yazilir():
    cmd, _ = nv.build_command(
        remux_cfg(sub_lang="tur", sub_lang_label="Türkçe"),
        probes(sub_codecs=["subrip", "ass"]))
    # gomulu 2 iz -> harici iz altyazi indeksi 2
    assert "-metadata:s:s:2" in cmd
    degerler = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-metadata:s:s:2"]
    assert "language=tur" in degerler and "title=Türkçe" in degerler


def test_remux_dil_belirtilmezse_etiket_yazilmaz():
    cmd, _ = nv.build_command(remux_cfg(sub_lang="", sub_lang_label=""), probes())
    assert not any(a.startswith("-metadata:s:s:") for a in cmd)


def test_remux_varsayilan_isareti_eskisini_dusurur():
    """
    Iki iz birden 'default' kalirsa oynatici eskisini secer.

    Eski izler "-default" ile dusurulur, duz "0" ile DEGIL: olculdu, "0" tum
    bayrak maskesini siliyor ve forced isaretli bir iz forced'ini kaybediyor.
    """
    cmd, _ = nv.build_command(
        remux_cfg(sub_default=True), probes(sub_codecs=["subrip", "ass"]))
    assert val_of(cmd, "-disposition:s:2") == "default"
    assert val_of(cmd, "-disposition:s:0") == "-default"
    assert val_of(cmd, "-disposition:s:1") == "-default"


def test_remux_varsayilan_kapaliysa_disposition_yok():
    cmd, _ = nv.build_command(
        remux_cfg(sub_default=False), probes(sub_codecs=["subrip"]))
    assert not any(a.startswith("-disposition") for a in cmd)


def test_remux_metadata_alanlari_calisir():
    """Kopyalama modunda da konteyner metadata'si yazilabilir."""
    cmd, _ = nv.build_command(remux_cfg(meta_title="Film"), probes())
    assert "title=Film" in cmd


def test_remux_ciktiyla_biter():
    cmd, _ = nv.build_command(remux_cfg(output_file=r"C:\v\x.mkv"), probes())
    assert cmd[0] == "ffmpeg"
    assert cmd[-2:] == ["-y", r"C:\v\x.mkv"]


def test_remux_altyazi_gomulmez():
    """Altyazi iz olarak eklenir; hardsub filtresi girmemeli."""
    cmd, _ = nv.build_command(remux_cfg(), probes())
    assert "-vf" not in cmd
    vf, _ = nv.build_filters(remux_cfg(), probes())
    assert not any("subtitles=" in f for f in vf)


def test_remux_onizlemede_de_altyazi_yakilmaz():
    """Onizleme ciktiyi temsil etmeli: remux'ta altyazi yanmaz."""
    cmd = nv.build_preview_command(remux_cfg(), probes(), "x.png")
    assert vf_of(cmd) is None or "subtitles=" not in vf_of(cmd)


def test_remux_hicbir_filtre_calismaz():
    """
    Kare dokunulmadan kopyalanir. Onizleme de bunu gostermeli: renk filtresi
    onizlemeye sizarsa kullanici ciktida OLMAYAN bir duzeltme gorur.
    """
    vf, notlar = nv.build_filters(
        remux_cfg(color_preset="Karanlık Video Kurtarma", scale="720p",
                  use_bwdif=True),
        probes(cuda_frames=True))
    assert vf == [] and notlar == []
    cmd = nv.build_preview_command(
        remux_cfg(color_preset="Karanlık Video Kurtarma"), probes(), "x.png")
    assert vf_of(cmd) is None


def test_remux_uygulanmayan_ayarlar_icin_uyarir():
    """Olcekleme/renk sessizce yutulmamali; kullaniciya soylenmeli."""
    _, notes = nv.build_command(
        remux_cfg(scale="720p", color_preset="Karanlık Video Kurtarma"), probes())
    assert any("UYGULANMADI" in n for n in notes)


def test_remux_ayar_yoksa_gereksiz_uyari_verilmez():
    _, notes = nv.build_command(remux_cfg(), probes())
    assert not any("UYGULANMADI" in n for n in notes)


def test_remux_kodlama_yapilmadigi_bildirilir():
    _, notes = nv.build_command(remux_cfg(), probes())
    assert any("yeniden" in n and "kodlanmıyor" in n for n in notes)


# ---------------------------------------------------------------- kodlama olcumu
@pytest.mark.parametrize("icerik,kodlama,beklenen", [
    ("Merhaba dünya", "utf-8", ("", False)),          # temiz UTF-8 -> kopyala
    ("Merhaba dünya", "utf-8-sig", ("", False)),      # BOM'u cozucu kendi atar
    ("Merhaba dünya", "cp1254", ("CP1254", True)),    # 8-bit -> cevir
    ("Merhaba dünya", "utf-16", ("", True)),          # BOM'u ffmpeg cevirir
    ("Plain ascii", "ascii", ("", False)),            # ASCII gecerli UTF-8'dir
])
def test_detect_sub_charenc(tmp_path, icerik, kodlama, beklenen):
    yol = tmp_path / "a.srt"
    yol.write_text(icerik, encoding=kodlama)
    assert nv.detect_sub_charenc(str(yol)) == beklenen


def test_detect_sub_charenc_zorlama_olcumu_ezer():
    """Kullanici elle sectiyse dosya UTF-8 olsa bile cevrim yapilir."""
    assert nv.detect_sub_charenc(r"C:\yok.srt", "ISO-8859-9") == ("ISO-8859-9", True)


def test_detect_sub_charenc_okunamayan_dosyada_varsayim_uretmez():
    """Sessizce yanlis kodlama zorlamak yerine ffmpeg kendi hatasini versin."""
    assert nv.detect_sub_charenc(r"C:\olmayan\dosya.srt") == ("", False)


def test_detect_sub_charenc_utf16_de_charenc_vermez(tmp_path):
    """
    Olculdu: "-sub_charenc UTF-16" cift cevrime yol acip "Unable to recode
    subtitle event" veriyor (cozucu BOM'u zaten kendi ceviriyor); "copy" ise
    UTF-16 baytlarini oldugu gibi gecirip okunamaz bir iz birakiyor.
    Dogru davranis: charenc VERMEDEN cevirmek.

    NOT: BOM'SUZ UTF-16 bilerek kapsam disi. Olculdu: ffmpeg boyle bir dosyayi
    hangi -sub_charenc verilirse verilsin ACAMIYOR ("Error opening input:
    Invalid data found"), yani tespit etsek de sonuc degismezdi.
    """
    yol = tmp_path / "bomlu.srt"
    yol.write_text("Merhaba dünya", encoding="utf-16")     # BOM yazar
    assert nv.detect_sub_charenc(str(yol)) == ("", True)


# ------------------------------------------------- elle secilen kodlama denetimi
def test_kodlama_zorlanmadiysa_denetim_yapilmaz(tmp_path):
    """'Otomatik' secildiginde karar detect_sub_charenc'in; burasi susar."""
    yol = tmp_path / "a.srt"
    yol.write_text("Merhaba dünya", encoding="cp1254")
    assert nv.sub_kodlama_uyusmazligi(str(yol), "") == (None, None)


def test_cozemeyen_kodlama_HATA_verir(tmp_path):
    """
    Olculdu: CP1254 bir dosyayi UTF-8 sanip cevirmeye kalkinca ffmpeg
    "Invalid UTF-8 in decoded subtitles text" deyip 69 ile cikiyor.
    Kuyruga almadan once yakalanmali.
    """
    yol = tmp_path / "a.srt"
    yol.write_text("Merhaba dünya", encoding="cp1254")
    hata, uyari = nv.sub_kodlama_uyusmazligi(str(yol), "UTF-8")
    assert hata and "çözemiyor" in hata
    assert uyari is None


def test_utf8_dosyada_8bit_kod_sayfasi_UYARI_verir(tmp_path):
    """
    Hata cikmaz (her kod sayfasi her bayti "cozer") ama harfler bozulur:
    "Türkçe" -> "TÃ¼rkÃ§e". Sessiz kalmak yanlis olurdu.
    """
    yol = tmp_path / "a.srt"
    yol.write_text("Merhaba dünya", encoding="utf-8")
    hata, uyari = nv.sub_kodlama_uyusmazligi(str(yol), "CP1254")
    assert hata is None
    assert uyari and "bozuk" in uyari


def test_ascii_dosyada_uyari_verilmez(tmp_path):
    """Iki yorum ayni sonucu veriyorsa uyari gurultu olur."""
    yol = tmp_path / "a.srt"
    yol.write_text("Plain ascii only", encoding="utf-8")
    assert nv.sub_kodlama_uyusmazligi(str(yol), "CP1254") == (None, None)


def test_dogru_kodlama_sessiz_gecer(tmp_path):
    yol = tmp_path / "a.srt"
    yol.write_text("Merhaba dünya", encoding="cp1254")
    assert nv.sub_kodlama_uyusmazligi(str(yol), "CP1254") == (None, None)


def test_okunamayan_dosyada_uydurma_yapilmaz():
    assert nv.sub_kodlama_uyusmazligi(r"C:\olmayan\dosya.srt", "UTF-8") == (None, None)


def test_tanimsiz_kodlama_adi_cokertmez(tmp_path):
    """Bozuk bir ayar dosyasindan gelen sacma deger programi durdurmamali."""
    yol = tmp_path / "a.srt"
    yol.write_text("Merhaba", encoding="utf-8")
    hata, _ = nv.sub_kodlama_uyusmazligi(str(yol), "Klingonca")
    assert hata and "çözemiyor" in hata


# ---------------------------------------------------------------- cikti adi
def test_remux_cikti_adi_kodek_etiketi_tasimaz():
    """Hicbir sey degismedigi icin CODEC/CQ/olcekleme etiketi anlamsiz."""
    yol = nv.FFmpegStudioPro._build_output_path(
        None, remux_cfg(input_file=r"C:\video\Film (2020).mkv", container="mkv"))
    assert yol == r"C:\video\Film (2020)_Altyazili.mkv"


def test_remux_cikti_adi_konteyneri_izler():
    yol = nv.FFmpegStudioPro._build_output_path(
        None, remux_cfg(input_file=r"C:\video\a.mkv", container="mp4"))
    assert yol.endswith("a_Altyazili.mp4")


# ---------------------------------------------------------------- altyazi plani
def test_remux_sub_plan_indeksleri_esleme_sirasiyla_tutar():
    izler, atlanan, harici = nv.remux_sub_plan(
        remux_cfg(container="mkv"), probes(sub_codecs=["mov_text", "ass"]))
    assert izler == [("0:s:0", "srt"), ("0:s:1", "copy"), ("1:0", "copy")]
    assert atlanan == []
    assert harici == 2


def test_remux_sub_plan_atlanan_iz_indeksi_kaydirir():
    """Atlanan iz esleme disinda kaldigi icin sonraki -c:s:N kayar."""
    izler, atlanan, harici = nv.remux_sub_plan(
        remux_cfg(container="mp4"),
        probes(sub_codecs=["hdmv_pgs_subtitle", "subrip"]))
    assert izler == [("0:s:1", "mov_text"), ("1:0", "mov_text")]
    assert atlanan == ["hdmv_pgs_subtitle"]
    assert harici == 1


@pytest.mark.parametrize("codec", sorted(nv.BITMAP_SUB_CODECS))
def test_resim_tabanli_izler_mp4de_atlanir_mkvde_kopyalanir(codec):
    assert nv.gomulu_sub_codec(codec, "mp4") is None
    assert nv.gomulu_sub_codec(codec, "mkv") == "copy"
