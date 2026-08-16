"""
Python 3.14 / Tcl 9 icin Tcl-Tk betik kutuphanelerini pakete hazirlar.

SORUN: Python 3.14, Tcl/Tk 9.0 ile geliyor ve Tcl'in betik kutuphanesi artik
diskte bir klasor degil, DLL'in icine gomulu bir "zipfs" sanal dosya sistemi:
    //zipfs:/lib/tcl/tcl_library
    //zipfs:/lib/tk/tk_library
PyInstaller 6.21 bu sanal yolu okuyamiyor ve derleme sirasinda su uyariyi verip
Tcl verisini TOPLAMIYOR:
    WARNING: TclTkInfo: Tcl library/data directory ... does not exist!
Sonuc: uretilen exe acilirken calisma zamani kancasi
    FileNotFoundError: Tcl data directory "..._internal\\_tcl_data" not found
ile cokuyor.

COZUM: Tcl'in kendi dosya komutlariyla bu klasorleri zipfs'ten diske cikarip
PyInstaller'a normal veri klasoru olarak veriyoruz (bkz. VidForge.spec).

Kullanim (spec bunu otomatik cagirir):
    python tools/collect_tcl9.py [hedef_klasor]
"""
import os
import sys
import tkinter


def zipfs_kullaniliyor_mu(kok):
    return str(kok).startswith("//zipfs:")


def cikar(hedef_kok):
    """
    (tcl_dizini, tk_dizini) dondurur. Tcl 8.x kullaniliyorsa (zipfs yok)
    (None, None) doner - o durumda PyInstaller zaten kendi toplar.
    """
    r = tkinter.Tk()
    r.withdraw()
    try:
        tcl_kok = r.tk.eval("set tcl_library")
        tk_kok = r.tk.eval("set tk_library")
        if not (zipfs_kullaniliyor_mu(tcl_kok) or zipfs_kullaniliyor_mu(tk_kok)):
            return None, None

        hedefler = {}
        for ad, kaynak in (("_tcl_data", tcl_kok), ("_tk_data", tk_kok)):
            hedef = os.path.join(hedef_kok, ad)
            # Tcl'in kendi "file copy"si zipfs'i okuyabilir; Python'un
            # shutil'i okuyamaz (sanal dosya sistemi isletim sistemine gorunmez).
            r.tk.eval(f'file delete -force {{{hedef}}}')
            r.tk.eval(f'file mkdir {{{hedef}}}')
            for girdi in r.tk.splitlist(r.tk.eval(f'glob -directory {{{kaynak}}} *')):
                r.tk.eval(f'file copy -force {{{girdi}}} {{{hedef}}}')
            hedefler[ad] = hedef
        return hedefler["_tcl_data"], hedefler["_tk_data"]
    finally:
        r.destroy()


if __name__ == "__main__":
    kok = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "build_tcl")
    os.makedirs(kok, exist_ok=True)
    tcl_dizin, tk_dizin = cikar(kok)
    if tcl_dizin is None:
        print("Tcl 8.x kullaniliyor; cikarma gerekmiyor.")
    else:
        for d in (tcl_dizin, tk_dizin):
            print("%-12s %s (%d dosya)" % (os.path.basename(d), d,
                                           sum(len(f) for _, _, f in os.walk(d))))
