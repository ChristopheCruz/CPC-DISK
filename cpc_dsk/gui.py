"""Interface graphique (tkinter) de cpc_dsk — habillage « écran CPC » pixel art.

Deux onglets (F1 / F2) :

- **Disquette (.dsk)** : ouvrir / créer / sauvegarder une image, lister les
  fichiers (couches Filer et AMSDOS), ajouter un fichier local, extraire un
  fichier vers le disque local, supprimer un fichier, inspection
  hexadécimale d'un fichier ou d'un secteur, carte des secteurs cliquable.
- **Gotek (clé USB)** : préparer le répertoire à copier sur la clé USB du
  Gotek (patron de noms, sous-dossier, index de départ), le vérifier, et
  créer une image FAT16 complète (rédacteur intégré, aucune dépendance).

Habillage :
- palette du firmware CPC (bleu / jaune vif / cyan) ou moniteur vert GT65
  (bouton « Moniteur » ou F3) ;
- polices pixel « Press Start 2P » et « VT323 » (licence OFL) chargées depuis
  le dossier ``fonts/`` voisin de ce fichier (repli automatique sur une
  police à chasse fixe si elles sont absentes).

Raccourcis : F1/F2 onglets, F3 moniteur, F4 vue fichiers/secteurs, Ctrl+O ouvrir, Ctrl+N nouveau,
Ctrl+S sauver.

Lancement:
    python -m cpc_dsk.gui
"""

from __future__ import annotations

import os
import sys
import tempfile
import unicodedata
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence, Set, Tuple

from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.core.cpcfs import CpcError, CpcFile, CpcFilesystem, FT_BASIC, FT_BINARY
from cpc_dsk.core.cpm import CpmFilesystem, is_cpm_disk, new_cpm_system_disk
from cpc_dsk.core.gotek import (
    DEFAULT_NAME_PATTERN,
    FatFile,
    GotekConfig,
    GotekError,
    create_fat_image,
    list_fat_image,
    prepare_usb_directory,
    verify_usb_directory,
)
from cpc_dsk.i18n import LANGUAGES, detect_language, set_language as _set_lang
from cpc_dsk.i18n import t as L


# ====================================================================== #
# Thèmes (palette du firmware CPC / moniteur vert GT65)
# ====================================================================== #
THEMES: Dict[str, Dict[str, str]] = {
    "couleur": dict(
        frame="#0000FF", paper="#000080", panel="#000040", ink="#FFFF00",
        acc="#00FFFF", hi="#FFFFFF", warm="#FF8000", dim="#2828A8",
        btn="#00FFFF", btn_ink="#000080", pri="#FFFF00", pri_ink="#000080",
        danger="#FF0000", danger_ink="#000000",
        r="#FF0000", g="#00FF00", b="#00A0FF"),
    "vert": dict(
        frame="#0B3D16", paper="#021A07", panel="#010D04", ink="#33FF66",
        acc="#9CFFB4", hi="#E0FFE8", warm="#1FA344", dim="#0F4A1E",
        btn="#9CFFB4", btn_ink="#021A07", pri="#33FF66", pri_ink="#021A07",
        danger="#E0FFE8", danger_ink="#021A07",
        r="#33FF66", g="#9CFFB4", b="#E0FFE8"),
}

# Icônes 8×8 (X = pixel allumé), dessinées à l'échelle 2.
ICONS: Dict[str, Sequence[str]] = {
    "open": ("........", "XXX.....", "XXXXXXXX", "XXXXXXXX",
             "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "........"),
    "new": ("...XX...", "...XX...", "...XX...", "XXXXXXXX",
            "XXXXXXXX", "...XX...", "...XX...", "...XX..."),
    "save": ("XXXXXXX.", "XX...XXX", "XX...XXX", "XXXXXXXX",
             "XXXXXXXX", "XX....XX", "XX....XX", "XXXXXXXX"),
    "eye": ("........", "..XXXX..", ".XX..XX.", "XX.XX.XX",
            "XX.XX.XX", ".XX..XX.", "..XXXX..", "........"),
    "extract": ("...XX...", "...XX...", "...XX...", ".XXXXXX.",
                "..XXXX..", "...XX...", "X......X", "XXXXXXXX"),
    "trash": ("..XXXX..", "XXXXXXXX", "........", ".XXXXXX.",
              ".X.XX.X.", ".X.XX.X.", ".X.XX.X.", ".XXXXXX."),
    "up": ("........", "...XX...", "..XXXX..", ".XXXXXX.",
           "XXXXXXXX", "...XX...", "...XX...", "........"),
    "down": ("........", "...XX...", "...XX...", "XXXXXXXX",
             ".XXXXXX.", "..XXXX..", "...XX...", "........"),
}

# Disquette 3" en pixel art (grille 24×28) : (x, y, w, h, couleur du thème).
FLOPPY = (
    (1, 0, 22, 28, "dim"), (0, 1, 24, 26, "dim"),
    (7, 0, 10, 9, "hi"), (9, 2, 3, 5, "panel"),
    (3, 13, 18, 13, "ink"),
    (5, 16, 14, 1, "paper"), (5, 19, 10, 1, "paper"), (5, 22, 12, 1, "paper"),
    (1, 2, 1, 2, "acc"), (22, 2, 1, 2, "acc"),
)

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
PIXEL_TITLE = "Press Start 2P"
PIXEL_BODY = "VT323"


def _apply_window_icon(root) -> None:
    """Icône de la fenêtre : disquette CPC (ico sous Windows, png ailleurs).

    Sous PyInstaller one-file, les fichiers sont décompressés dans le
    dossier temporaire du paquetage : FONT_DIR les trouve au même endroit.
    """
    global _icon_ref
    try:
        if sys.platform == "win32":
            ico = os.path.join(FONT_DIR, "..", "icon.ico")
            if os.path.exists(ico):
                root.iconbitmap(ico)
        png = os.path.join(FONT_DIR, "..", "icon.png")
        if os.path.exists(png):
            _icon_ref = tk.PhotoImage(file=png)
            root.iconphoto(True, _icon_ref)
    except (tk.TclError, OSError):
        pass


# ====================================================================== #
# Utilitaires
# ====================================================================== #
def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} {L('sz_mb')}"
    if n >= 1024:
        return f"{n / 1024:.1f} {L('sz_kb')}"
    return f"{n} {L('sz_b')}"


def _suggest_83(path: str) -> str:
    """Nom 8.3 suggéré à partir d'un nom de fichier local.

    L'extension est **conservée** (3 caractères), en notation CPC (espace) :
    ``monprog.bas`` -> ``MONPROG BAS``, ``data.bin`` -> ``DATA BIN``.
    Le champ Filer est ``base(8) + ext(3)`` sans séparateur (l'espace n'est
    que du padding) : la notation ``BASE EXT`` peut donc faire 12 caractères
    (``programme.bas`` -> ``PROGRAMM BAS``, base 8 + ext 3 intacts).
    """
    base = os.path.basename(path)
    stem, dot, ext = base.partition(".")
    stem = stem.upper()[:8]
    if not dot:
        return stem
    ext = ext.upper()[:3]
    return " ".join(p for p in (stem, ext) if p)


def _mix(c1: str, c2: str, a: float) -> str:
    """Mélange deux couleurs #RRGGBB (a = part de c2)."""
    x = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    y = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(p + (q - p) * a):02X}" for p, q in zip(x, y))


def _hex_rows(data: bytes):
    """Lignes (offset, octets, ascii) d'un dump hexadécimal 16 octets/ligne."""
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        yield (f"{i:08X}",
               " ".join(f"{b:02X}" for b in chunk).ljust(47),
               "".join(chr(b) if 32 <= b < 127 else "." for b in chunk))


def _probe_geometry(disk) -> Tuple[int, int]:
    """(pistes, secteurs par piste) en sondant ``get_sector``."""
    def ok(t: int, s: int) -> bool:
        try:
            return bool(disk.get_sector(t, s))
        except Exception:  # noqa: BLE001 — hors géométrie
            return False

    tracks = 0
    while tracks < 200 and ok(tracks, 0):
        tracks += 1
    sectors = 0
    while tracks and sectors < 64 and ok(0, sectors):
        sectors += 1
    return tracks, sectors


def _load_private_fonts() -> None:
    """Rend les .ttf du dossier ``fonts/`` visibles par Tk (Windows).

    Doit être appelé AVANT la création de la fenêtre Tk.
    """
    if sys.platform != "win32" or not os.path.isdir(FONT_DIR):
        return
    try:
        import ctypes
        gdi32 = ctypes.windll.gdi32
        gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint,
                                             ctypes.c_void_p]
        FR_PRIVATE = 0x10
        for name in os.listdir(FONT_DIR):
            if name.lower().endswith((".ttf", ".otf")):
                gdi32.AddFontResourceExW(os.path.join(FONT_DIR, name),
                                         FR_PRIVATE, None)
    except Exception:  # noqa: BLE001 — confort visuel, pas critique
        pass


# --- Glisser-déposer depuis l'explorateur Windows ------------------------- #
def _register_drag_drop(root: "tk.Tk", on_drop) -> bool:
    """Active le glisser-déposer de fichiers (explorateur Windows) sur la
    fenêtre racine, sans dépendance externe.

    Méthode : ``DragAcceptFiles`` sur la fenêtre Tk puis sous-classement de
    sa procédure de fenêtre (``SetWindowLongPtrW``) pour intercepter
    ``WM_DROPFILES``. Les messages non traités repartent vers Tk via
    ``CallWindowProcW``.

    ``on_drop(liste_de_chemins)`` est appelé dans la boucle tkinter.
    Retourne ``False`` si l'OS ne le supporte pas (Linux/macOS).
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        WM_DROPFILES = 0x0233
        GWLP_WNDPROC = -4
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        if ctypes.sizeof(ctypes.c_void_p) == 8:
            set_wl = user32.SetWindowLongPtrW
        else:
            set_wl = user32.SetWindowLongW
        set_wl.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_wl.restype = ctypes.c_void_p
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                           wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                           wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [ctypes.c_void_p]

        root.update_idletasks()
        hwnd = root.winfo_id()

        # Processus élevé (admin) : laisser passer les dépôts de l'explorateur.
        try:
            user32.ChangeWindowMessageFilterEx.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p]
            for msg in (WM_DROPFILES, 0x004A, 0x0049):
                user32.ChangeWindowMessageFilterEx(hwnd, msg, 1, None)
        except Exception:  # noqa: BLE001
            pass

        old_proc = [None]

        def _wndproc(h, msg, wp, lp):
            if msg == WM_DROPFILES:
                count = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                buf = ctypes.create_unicode_buffer(32768)
                paths = []
                for i in range(count):
                    if shell32.DragQueryFileW(wp, i, buf, 32768):
                        paths.append(buf.value)
                shell32.DragFinish(wp)
                if paths:
                    root.after(0, lambda p=paths: on_drop(p))
                return 0
            return user32.CallWindowProcW(old_proc[0], h, msg, wp, lp)

        callback = WNDPROC(_wndproc)
        # Le callback doit rester référencé (sinon collecté -> plantage).
        globals()["_drag_drop_callback"] = callback
        old_proc[0] = set_wl(hwnd, GWLP_WNDPROC,
                             ctypes.cast(callback, ctypes.c_void_p))
        if not old_proc[0]:
            return False
        shell32.DragAcceptFiles(hwnd, True)
        return True
    except Exception:  # noqa: BLE001 — le DnD est un confort, pas critique
        return False


# ====================================================================== #
# Widgets pixel art
# ====================================================================== #
class PixelButton(tk.Canvas):
    """Bouton à relief 4 px, coins crantés, icône 8×8 optionnelle."""

    KINDS = {"normal": ("btn", "btn_ink"), "primary": ("pri", "pri_ink"),
             "danger": ("danger", "danger_ink")}

    def __init__(self, master, app: "DskEditorApp", text: str = "",
                 command=None, kind: str = "normal", icon: Optional[str] = None,
                 padx: int = 16):
        t = app.t
        bg_key, fg_key = self.KINDS[kind]
        self._bg, self._fg = getattr(t, bg_key), getattr(t, fg_key)
        self._text = app.caps(text)
        self._icon = icon
        self._cmd = command
        self._font = app.f_btn
        tw = self._font.measure(self._text) if self._text else 0
        iw = 16 if icon else 0
        gap = 10 if (icon and self._text) else 0
        self._content_w = tw + iw + gap
        self._bw = self._content_w + 2 * padx + 8
        self._bh = max(42, self._font.metrics("linespace") + 24)
        super().__init__(master, width=self._bw, height=self._bh,
                         bg=master.cget("bg"), highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self._hover = self._press = self._focus = False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, press=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(press=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda e: self._set(focus=True))
        self.bind("<FocusOut>", lambda e: self._set(focus=False))
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<Return>", lambda e: self.invoke())
        self._draw()

    def invoke(self) -> None:
        if self._cmd:
            self._cmd()

    def _release(self, event) -> None:
        inside = 0 <= event.x < self._bw and 0 <= event.y < self._bh
        was = self._press
        self._set(press=False)
        if was and inside:
            self.invoke()

    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, "_" + k, v)
        self._draw()

    def _draw(self) -> None:
        w, h, n = self._bw, self._bh, 4
        self.delete("all")
        body = _mix(self._bg, "#FFFFFF", 0.15) if self._hover else self._bg
        light, dark = _mix(body, "#FFFFFF", 0.55), _mix(body, "#000000", 0.35)
        tl, br = (dark, _mix(body, "#FFFFFF", 0.35)) if self._press else (light, dark)
        self.create_polygon(0, n, n, n, n, 0, w - n, 0, w - n, n, w, n,
                            w, h - n, w - n, h - n, w - n, h, n, h, n, h - n,
                            0, h - n, fill=body, outline="")
        self.create_rectangle(n, 0, w - n, n, fill=tl, outline="")
        self.create_rectangle(0, n, n, h - n, fill=tl, outline="")
        self.create_rectangle(n, h - n, w - n, h, fill=br, outline="")
        self.create_rectangle(w - n, n, w, h - n, fill=br, outline="")
        off = 2 if self._press else 0
        x = (w - self._content_w) / 2 + off
        cy = h / 2 + off
        if self._icon:
            for r, line in enumerate(ICONS[self._icon]):
                for c, ch in enumerate(line):
                    if ch == "X":
                        px, py = x + c * 2, cy - 8 + r * 2
                        self.create_rectangle(px, py, px + 2, py + 2,
                                              fill=self._fg, outline="")
            x += 16 + (10 if self._text else 0)
        if self._text:
            self.create_text(x, cy + 1, text=self._text, anchor="w",
                             font=self._font, fill=self._fg)
        if self._focus:
            self.create_rectangle(7, 7, w - 7, h - 7, outline=self._fg,
                                  dash=(2, 2))


class Panel(tk.Frame):
    """Cadre bordé 4 px avec bandeau de titre en vidéo inverse."""

    def __init__(self, master, app: "DskEditorApp", title: str,
                 accent: Optional[str] = None):
        t = app.t
        accent = accent or t.acc
        super().__init__(master, bg=accent, padx=4, pady=4)
        self.head = tk.Label(self, text=app.caps(title), bg=accent, fg=t.paper,
                             font=app.f_head, anchor="w", padx=8, pady=6)
        self.head.pack(fill="x")
        self.body = tk.Frame(self, bg=t.panel)
        self.body.pack(fill="both", expand=True)


class Segmented(tk.Frame):
    """Choix exclusif en boutons pixel (remplace un Combobox)."""

    def __init__(self, master, app: "DskEditorApp", var: tk.StringVar,
                 options: Sequence[Tuple[str, str]]):
        super().__init__(master, bg=master.cget("bg"))
        self.app, self.var = app, var
        self._labels: List[Tuple[str, tk.Label]] = []
        for value, label in options:
            lbl = tk.Label(self, text=app.caps(label), font=app.f_head, padx=12,
                           pady=10, cursor="hand2", highlightthickness=3,
                           takefocus=1)
            lbl.pack(side="left", padx=(0, 6))
            lbl.bind("<Button-1>", lambda e, v=value: var.set(v))
            lbl.bind("<space>", lambda e, v=value: var.set(v))
            self._labels.append((value, lbl))
        self._trace = var.trace_add("write", lambda *a: self._paint())
        self.bind("<Destroy>", self._untrace, add="+")
        self._paint()

    def _untrace(self, _e=None) -> None:
        try:
            self.var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass

    def _paint(self) -> None:
        t = self.app.t
        for value, lbl in self._labels:
            on = value == self.var.get()
            try:
                lbl.config(bg=t.ink if on else t.panel,
                           fg=t.paper if on else t.acc,
                           highlightbackground=t.ink if on else t.acc,
                           highlightcolor=t.hi)
            except tk.TclError:
                pass


# ====================================================================== #
# Boîtes de dialogue
# ====================================================================== #
class PixelDialog:
    """Boîte modale (info / erreur / question) dans le style CPC."""

    def __init__(self, app: "DskEditorApp", title: str, message: str,
                 kind: str = "info",
                 buttons: Sequence[Tuple[str, object, str]] = (("OK", True, "primary"),)):
        t = app.t
        self.result = None
        accent = {"info": t.acc, "error": t.danger, "ask": t.ink,
                  "danger": t.danger}.get(kind, t.acc)
        head_fg = t.danger_ink if kind in ("error", "danger") else t.paper
        self.win = win = tk.Toplevel(app.root)
        win.title(title)
        win.configure(bg=accent)
        win.transient(app.root)
        win.resizable(False, False)
        head = tk.Label(win, text=app.caps(title), bg=accent, fg=head_fg,
                        font=app.f_head, anchor="w", padx=12, pady=10)
        head.pack(fill="x", padx=4, pady=(4, 0))
        body = tk.Frame(win, bg=t.panel, padx=18, pady=16)
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        tk.Label(body, text=message, bg=t.panel, fg=t.hi, font=app.f_body,
                 justify="left", wraplength=480, anchor="w").pack(
            fill="x", pady=(0, 16))
        row = tk.Frame(body, bg=t.panel)
        row.pack(anchor="e")
        first = None
        for label, value, bkind in buttons:
            b = PixelButton(row, app, label, kind=bkind,
                            command=lambda v=value: self._close(v))
            b.pack(side="left", padx=(8, 0))
            first = first or b
        win.bind("<Escape>", lambda e: self._close(None))
        win.protocol("WM_DELETE_WINDOW", lambda: self._close(None))
        _center(win, app.root)
        win.grab_set()
        if first is not None:
            first.focus_set()
        app.root.wait_window(win)

    def _close(self, value) -> None:
        self.result = value
        self.win.destroy()


def _center(win: tk.Toplevel, root: tk.Misc) -> None:
    win.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - win.winfo_reqheight()) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


class AddFileDialog:
    """Fenêtre modale : nom 8.3, type, adresse de chargement, couche."""

    def __init__(self, app: "DskEditorApp", default_name: str,
                 cpm: bool = False):
        t = app.t
        self.app = app
        self.cpm = cpm
        self.result: Optional[dict] = None
        self.win = win = tk.Toplevel(app.root)
        win.title(L("dlg_addwin_title"))
        win.configure(bg=t.acc)
        win.transient(app.root)
        win.resizable(False, False)

        tk.Label(win, text=L("dlg_addwin_head"), bg=t.acc, fg=t.paper,
                 font=app.f_head, anchor="w", padx=12, pady=10).pack(
            fill="x", padx=4, pady=(4, 0))
        frm = tk.Frame(win, bg=t.panel, padx=18, pady=16)
        frm.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self.name = tk.StringVar(value=default_name)
        self.ftype = tk.StringVar(value="binary")
        self.load = tk.StringVar(value="0x4000")
        # Filer d'abord (DOS d'origine, lu par le Gotek sur matériel réel) ;
        # « both » pour un disque lisible aussi par les émulateurs AMSDOS.
        # Disque CP/M : répertoire CP/M (lu par le vrai BDOS) ou objet AMSDOS.
        self.fs = tk.StringVar(value="cpm" if cpm else "filer")

        def label(text, row):
            tk.Label(frm, text=text, bg=t.panel, fg=t.acc, font=app.f_body,
                     anchor="w").grid(row=row, column=0, sticky="w",
                                      pady=6, padx=(0, 14))

        label(L("add_name"), 0)
        name_entry = app.entry(frm, self.name, width=14)
        name_entry.grid(row=0, column=1, sticky="w", pady=6)
        label(L("add_type"), 1)
        Segmented(frm, app, self.ftype,
                  [("basic", L("type_basic")),
                   ("binary", L("type_binary"))]).grid(
            row=1, column=1, sticky="w", pady=6)
        label(L("add_load"), 2)
        app.entry(frm, self.load, width=10).grid(row=2, column=1, sticky="w",
                                                 pady=6)
        label(L("add_layer"), 3)
        if cpm:
            layers = [("cpm", L("layer_cpm")),
                      ("amsdos", L("layer_amsdos"))]
        else:
            layers = [("filer", L("layer_filer")),
                      ("both", L("layer_both")),
                      ("amsdos", L("layer_amsdos"))]
        Segmented(frm, app, self.fs, layers).grid(
            row=3, column=1, sticky="w", pady=6)

        btns = tk.Frame(frm, bg=t.panel)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(16, 0))
        PixelButton(btns, app, L("btn_cancel"), command=win.destroy).pack(
            side="left", padx=(0, 8))
        PixelButton(btns, app, "OK", kind="primary", command=self._ok).pack(
            side="left")
        win.bind("<Return>", lambda e: self._ok())
        win.bind("<Escape>", lambda e: win.destroy())
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        _center(win, app.root)
        win.grab_set()
        name_entry.focus_set()
        name_entry.select_range(0, "end")

    def _ok(self) -> None:
        try:
            load = int(self.load.get(), 0)
        except ValueError:
            self.app.error(L("err_addr"), L("err_addr_msg"))
            return
        self.result = {
            "name": self.name.get(),
            "file_type": FT_BASIC if self.ftype.get() == "basic" else FT_BINARY,
            "load_addr": load,
            "mode": self.fs.get(),
        }
        self.win.destroy()


# ====================================================================== #
# Application
# ====================================================================== #
class DskEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        # Langue d'interface : locale système (en / fr / es), changeable
        # dans l'en-tête (reconstruit l'interface).
        self._lang = detect_language()
        _set_lang(self._lang)
        self.root.title(L("win_title"))
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)  # 1.25 à 125 %
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = min(round(1440 * self.scale), sw - 60)
        h = min(round(960 * self.scale), sh - 90)
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        self.root.minsize(min(round(1120 * self.scale), sw - 40),
                          min(round(740 * self.scale), sh - 60))

        # --- état (survit aux changements de thème) ---
        self.disk: Optional[ADFDisk] = None
        self.path: Optional[str] = None
        self._files: List[CpcFile] = []
        self._gotek_sources: List[str] = []
        self._gotek_img: Optional[str] = None
        self._gotek_img_files: List[FatFile] = []
        self._geom: Tuple[int, int] = (0, 0)
        self._sec_data: List[List[bytes]] = []
        self._sec_used: List[List[bool]] = []
        self._file_secs: Set[Tuple[int, int]] = set()
        self._cursor: Optional[Tuple[int, int]] = None
        self._last_hex: Optional[Tuple[bytes, str]] = None
        self._gtk_last: List[Tuple[str, str]] = []
        self._gtk_progress = 0.0
        self._status_text = L("st_ready")
        self._tab = 0
        self._theme_name = "couleur"
        self._blink_id: Optional[str] = None

        self.sector_var = tk.StringVar(value="0 0")
        self.left_view = tk.StringVar(value="files")  # "files" | "map"
        self.left_view.trace_add("write", lambda *a: self._show_left_view())
        self.lang_var = tk.StringVar(value=self._lang)
        self.lang_var.trace_add(
            "write", lambda *a: self.set_language(self.lang_var.get()))
        self.gtk_pattern = tk.StringVar(value=DEFAULT_NAME_PATTERN)
        self.gtk_subfolder = tk.StringVar(value="")
        self.gtk_index = tk.StringVar(value="1")
        self.gtk_outdir = tk.StringVar(value="")
        for v in (self.gtk_pattern, self.gtk_subfolder, self.gtk_index):
            v.trace_add("write", lambda *a: self._gotek_names_changed())

        self._setup_fonts()
        self._apply_theme()
        self._build_ui()

        root.bind_all("<F1>", lambda e: self._show_tab(0))
        root.bind_all("<F2>", lambda e: self._show_tab(1))
        root.bind_all("<F3>", lambda e: self.toggle_monitor())
        root.bind_all("<F4>", lambda e: self.toggle_left_view())
        root.bind_all("<Control-o>", lambda e: self.open_disk())
        root.bind_all("<Control-n>", lambda e: self.new_disk())
        root.bind_all("<Control-s>", lambda e: self.save_disk())

        # Glisser-déposer depuis l'explorateur Windows.
        if _register_drag_drop(root, self._on_drop):
            self._set_status(L("st_dnd_on"))
        elif sys.platform == "win32":
            self._set_status(L("st_dnd_off"))

    # ------------------------------------------------------------------ #
    # Thème, polices, styles ttk
    # ------------------------------------------------------------------ #
    def _setup_fonts(self) -> None:
        families = set(tkfont.families(self.root))
        mono = next((f for f in ("Consolas", "Lucida Console", "Menlo",
                                 "DejaVu Sans Mono", "Courier New", "Courier")
                     if f in families), "TkFixedFont")
        has_title = PIXEL_TITLE in families
        has_body = PIXEL_BODY in families
        self.pixel_fonts = has_title and has_body
        self.has_title_font = has_title
        def px8(base: float) -> int:
            # Press Start 2P : toujours un multiple de 8 px (8, 16, 24, 32…)
            return -8 * max(1, round(base * self.scale / 8))

        def px(base: float) -> int:
            return -round(base * self.scale)

        if has_title:
            self.f_title = tkfont.Font(family=PIXEL_TITLE, size=px8(22))
            self.f_head = tkfont.Font(family=PIXEL_TITLE, size=px8(13))
            self.f_btn = tkfont.Font(family=PIXEL_TITLE, size=px8(13))
        else:
            self.f_title = tkfont.Font(family=mono, size=px(26), weight="bold")
            self.f_head = tkfont.Font(family=mono, size=px(14), weight="bold")
            self.f_btn = tkfont.Font(family=mono, size=px(14), weight="bold")
        if has_body:
            self.f_body = tkfont.Font(family=PIXEL_BODY, size=px(22))
            self.f_mono = tkfont.Font(family=PIXEL_BODY, size=px(21))
            self.f_small = tkfont.Font(family=PIXEL_BODY, size=px(16))
        else:
            self.f_body = tkfont.Font(family=mono, size=px(16))
            self.f_mono = tkfont.Font(family=mono, size=px(15))
            self.f_small = tkfont.Font(family=mono, size=px(12))

    def caps(self, text: str) -> str:
        """Majuscules ; sans accents avec Press Start 2P, qui n'a pas de
        capitales accentuées (comme sur le CPC)."""
        text = text.upper()
        if getattr(self, "has_title_font", False):
            text = "".join(c for c in unicodedata.normalize("NFD", text)
                           if unicodedata.category(c) != "Mn")
        return text

    def _apply_theme(self) -> None:
        self.t = SimpleNamespace(**THEMES[self._theme_name])
        t = self.t
        self.root.configure(bg=t.frame)
        st = ttk.Style(self.root)
        st.theme_use("clam")
        row_h = self.f_body.metrics("linespace") + 8
        st.configure("Pixel.Treeview", background=t.panel,
                     fieldbackground=t.panel, foreground=t.ink,
                     font=self.f_body, rowheight=row_h, borderwidth=0,
                     relief="flat")
        st.map("Pixel.Treeview",
               background=[("selected", t.ink)],
               foreground=[("selected", t.paper)])
        st.configure("Pixel.Treeview.Heading", background=t.panel,
                     foreground=t.acc, font=self.f_body, relief="flat",
                     borderwidth=0, padding=(6, 4))
        st.map("Pixel.Treeview.Heading", background=[("active", t.dim)],
               foreground=[("active", t.hi)])
        st.layout("Pixel.Treeview",
                  [("Pixel.Treeview.treearea", {"sticky": "nswe"})])
        for orient in ("Vertical", "Horizontal"):
            name = f"Pixel.{orient}.TScrollbar"
            st.configure(name, background=t.acc, troughcolor=t.panel,
                         bordercolor=t.panel, arrowcolor=t.paper,
                         lightcolor=t.acc, darkcolor=t.acc, gripcount=0,
                         relief="flat", arrowsize=16)
            st.map(name, background=[("active", t.hi), ("pressed", t.ink)])

    def toggle_monitor(self) -> None:
        """Bascule couleur (CTM644) <-> moniteur vert (GT65)."""
        self._theme_name = "vert" if self._theme_name == "couleur" else "couleur"
        if self._blink_id:
            self.root.after_cancel(self._blink_id)
            self._blink_id = None
        self.shell.destroy()
        self._apply_theme()
        self._build_ui()
        self._refresh(rescan=False)
        if self._last_hex:
            self._show_hex(*self._last_hex)
        self._gotek_refresh_tree()
        self._gotek_result_render()

    def set_language(self, lang: str) -> None:
        """Change la langue d'interface (en / fr / es) et reconstruit
        l'interface ; l'état (disque ouvert, sources, thème, onglet) survit."""
        if lang not in LANGUAGES or lang == self._lang:
            return
        self._lang = lang
        _set_lang(lang)
        if self._blink_id:
            self.root.after_cancel(self._blink_id)
            self._blink_id = None
        self.root.title(L("win_title"))
        self._status_text = L("st_ready")
        self.shell.destroy()
        self._build_ui()
        self._refresh(rescan=False)
        if self._last_hex:
            self._show_hex(*self._last_hex)
        self._gotek_refresh_tree()
        self._gotek_result_render()

    # ------------------------------------------------------------------ #
    # Construction de l'interface
    # ------------------------------------------------------------------ #
    def entry(self, master, var, width=10, **kw) -> tk.Entry:
        t = self.t
        return tk.Entry(master, textvariable=var, width=width, font=self.f_body,
                        bg=t.paper, fg=t.ink, insertbackground=t.ink,
                        insertwidth=10, relief="flat", bd=3,
                        highlightthickness=3, highlightbackground=t.acc,
                        highlightcolor=t.hi, selectbackground=t.ink,
                        selectforeground=t.paper, disabledbackground=t.panel,
                        readonlybackground=t.paper, **kw)

    def _label(self, master, text="", fg=None, bg=None, font=None, **kw) -> tk.Label:
        return tk.Label(master, text=text, fg=fg or self.t.ink,
                        bg=bg or master.cget("bg"), font=font or self.f_body,
                        **kw)

    def _build_ui(self) -> None:
        t = self.t
        self.shell = tk.Frame(self.root, bg=t.frame, padx=22, pady=22)
        self.shell.pack(fill="both", expand=True)
        screen = tk.Frame(self.shell, bg=t.paper, padx=22, pady=16)
        screen.pack(fill="both", expand=True)

        # --- en-tête ---
        head = tk.Frame(screen, bg=t.paper)
        head.pack(fill="x")
        left = tk.Frame(head, bg=t.paper)
        left.pack(side="left")
        self._label(left, "CPC DISK EDITOR", font=self.f_title).pack(anchor="w")
        self._label(left, L("hdr_sub"), fg=t.acc).pack(anchor="w", pady=(8, 0))
        right = tk.Frame(head, bg=t.paper)
        right.pack(side="right", anchor="s")
        PixelButton(right, self,
                    L("btn_monitor",
                      v=L("mon_vert" if self._theme_name == "vert"
                          else "mon_couleur")),
                    command=self.toggle_monitor).pack(side="right")
        Segmented(right, self, self.lang_var,
                  [("en", "EN"), ("fr", "FR"), ("es", "ES")]).pack(
            side="right", padx=(0, 18))
        stripes = tk.Frame(right, bg=t.paper)
        stripes.pack(side="right", padx=(0, 18))
        for c in (t.r, t.g, t.b):
            tk.Frame(stripes, bg=c, width=170, height=8).pack(pady=2)

        # --- onglets ---
        tabs = tk.Frame(screen, bg=t.paper)
        tabs.pack(fill="x", pady=(14, 0))
        self._tab_labels: List[tk.Label] = []
        for i, text in enumerate((L("tab_disk"), L("tab_gotek"))):
            lbl = tk.Label(tabs, text=text, font=self.f_head, padx=18,
                           pady=12, cursor="hand2")
            lbl.pack(side="left", padx=(0, 8))
            lbl.bind("<Button-1>", lambda e, i=i: self._show_tab(i))
            self._tab_labels.append(lbl)
        tk.Frame(screen, bg=t.ink, height=4).pack(fill="x")

        # --- pied de page (avant le contenu pour rester visible) ---
        foot = tk.Frame(screen, bg=t.paper)
        foot.pack(side="bottom", fill="x")
        tk.Frame(foot, bg=t.ink, height=4).pack(fill="x", pady=(10, 8))
        self.status = self._label(foot, self._status_text, fg=t.hi,
                                  anchor="w", justify="left", width=1)
        self.status.pack(side="left", fill="x", expand=True)
        self.ready = self._label(foot, "Ready █")
        self.ready.pack(side="right")
        self._blink(True)

        # --- contenu ---
        self.content = tk.Frame(screen, bg=t.paper)
        self.content.pack(fill="both", expand=True, pady=(14, 0))
        self.tab_disk = tk.Frame(self.content, bg=t.paper)
        self.tab_gotek = tk.Frame(self.content, bg=t.paper)
        self._build_disk_tab()
        self._build_gotek_tab()
        self._show_tab(self._tab)

    def _show_left_view(self) -> None:
        """Colonne gauche de l'onglet Disquette : catalogue OU carte."""
        try:
            files, mp = self.files_panel, self.map_panel
            if self.left_view.get() == "map":
                files.pack_forget()
                mp.pack(side="top", fill="both", expand=True)
                self.root.after_idle(self._draw_map)
            else:
                mp.pack_forget()
                files.pack(side="top", fill="both", expand=True)
        except (AttributeError, tk.TclError):
            pass

    def toggle_left_view(self) -> None:
        self.left_view.set("map" if self.left_view.get() == "files" else "files")

    def _show_tab(self, i: int) -> None:
        t = self.t
        self._tab = i
        for j, lbl in enumerate(self._tab_labels):
            on = j == i
            lbl.config(bg=t.ink if on else t.panel, fg=t.paper if on else t.acc)
        (self.tab_gotek if i == 0 else self.tab_disk).pack_forget()
        (self.tab_disk if i == 0 else self.tab_gotek).pack(fill="both",
                                                           expand=True)

    def _blink(self, on: bool) -> None:
        try:
            self.ready.config(text="Ready █" if on else "Ready  ")
        except tk.TclError:
            return
        self._blink_id = self.root.after(530, lambda: self._blink(not on))

    # ================================================================== #
    # Onglet Disquette
    # ================================================================== #
    def _build_disk_tab(self) -> None:
        t = self.t
        tab = self.tab_disk

        bar = tk.Frame(tab, bg=t.paper)
        bar.pack(side="top", fill="x")
        for text, icon, cmd in ((L("btn_open"), "open", self.open_disk),
                                (L("btn_new"), "new", self.new_disk),
                                (L("btn_newcpm"), "new", self.new_cpm_disk),
                                (L("btn_save"), "save", self.save_disk),
                                (L("btn_saveas"), None, self.save_disk_as)):
            PixelButton(bar, self, text, command=cmd, icon=icon).pack(
                side="left", padx=(0, 10))
        tk.Frame(bar, bg=t.dim, width=4, height=36).pack(side="left",
                                                         padx=(4, 14))
        self._label(bar, L("lbl_track_sect"), fg=t.acc,
                    font=self.f_head).pack(side="left", padx=(0, 10))
        sect = self.entry(bar, self.sector_var, width=6)
        sect.pack(side="left", padx=(0, 10))
        sect.bind("<Return>", lambda e: self.show_sector())
        PixelButton(bar, self, L("btn_show"), kind="primary", icon="eye",
                    command=self.show_sector).pack(side="left")

        info = tk.Frame(tab, bg=t.panel, padx=12, pady=6)
        info.pack(side="top", fill="x", pady=(12, 12))
        self.file_label = self._label(info, L("lbl_no_disk"), fg=t.hi,
                                      anchor="w")
        self.file_label.pack(side="left")
        self.info = self._label(info, L("lbl_geometry"), fg=t.acc, anchor="w")
        self.info.pack(side="left", padx=(24, 0), fill="x", expand=True)

        pane = tk.PanedWindow(tab, orient="horizontal", bg=t.paper,
                              sashwidth=14, bd=0, sashrelief="flat",
                              opaqueresize=True)
        pane.pack(fill="both", expand=True)

        # --- colonne gauche : catalogue + carte ---
        leftcol = tk.Frame(pane, bg=t.paper)
        vbar = tk.Frame(leftcol, bg=t.paper)
        vbar.pack(side="top", fill="x", pady=(0, 10))
        self._label(vbar, L("lbl_view"), fg=t.acc, font=self.f_head).pack(
            side="left", padx=(0, 10))
        Segmented(vbar, self, self.left_view,
                  [("files", L("view_files")),
                   ("map", L("view_map"))]).pack(side="left")
        self._label(vbar, "F4", fg=t.acc, font=self.f_small).pack(
            side="left", padx=(4, 0))
        mp = Panel(leftcol, self, L("panel_map"))
        files = Panel(leftcol, self, L("panel_cat0"))
        self.files_panel, self.map_panel = files, mp
        actions = tk.Frame(files.body, bg=t.panel, padx=10, pady=10)
        actions.pack(side="bottom", fill="x")
        tk.Frame(files.body, bg=t.dim, height=2).pack(side="bottom", fill="x")
        tv_frame = tk.Frame(files.body, bg=t.panel)
        tv_frame.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("name", "source", "type", "length", "offset")
        self.tree = ttk.Treeview(tv_frame, columns=cols, show="headings",
                                 selectmode="browse", style="Pixel.Treeview",
                                 height=5)
        for col, text, w, anchor in (("name", L("col_name"), 130, "w"),
                                     ("source", L("col_layer"), 80, "w"),
                                     ("type", L("col_type"), 60, "w"),
                                     ("length", L("col_len"), 70, "e"),
                                     ("offset", "@", 80, "e")):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=w, anchor=anchor, stretch=True)
        tvb = ttk.Scrollbar(tv_frame, orient="vertical",
                            command=self.tree.yview,
                            style="Pixel.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=tvb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tvb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_file_select)
        self.tree.bind("<Delete>", lambda e: self.delete_file())

        PixelButton(actions, self, L("btn_add"), icon="new", padx=12,
                    command=self.add_file).pack(side="left")
        PixelButton(actions, self, L("btn_extract"), icon="extract",
                    padx=12, command=self.extract_file).pack(side="left",
                                                             padx=8)
        PixelButton(actions, self, L("btn_delete"), kind="danger",
                    icon="trash", padx=12,
                    command=self.delete_file).pack(side="right")

        self.map_title = mp.head
        self.map_canvas = tk.Canvas(mp.body, bg=t.panel, height=170,
                                    highlightthickness=0, bd=0,
                                    cursor="crosshair")
        self.map_canvas.pack(fill="x", padx=10, pady=(10, 0))
        self.map_canvas.bind("<Configure>", lambda e: self._draw_map())
        self.map_canvas.bind("<Button-1>", self._on_map_click)
        self.map_canvas.bind("<Motion>", self._on_map_motion)
        legend = tk.Frame(mp.body, bg=t.panel, padx=10, pady=8)
        legend.pack(fill="x")
        for color, text in ((t.warm, L("map_used")),
                            (t.ink, L("map_file")),
                            (t.dim, L("map_free")),
                            (t.hi, L("map_cursor"))):
            tk.Frame(legend, bg=color, width=14, height=14).pack(side="left")
            self._label(legend, text, fg=t.hi, font=self.f_small).pack(
                side="left", padx=(6, 16))
        pane.add(leftcol, minsize=600, width=620, stretch="always")
        self._show_left_view()

        # --- colonne droite : hexadécimal ---
        hexp = Panel(pane, self, L("panel_hex"), accent=t.ink)
        self.hex_title = self._label(hexp.body, "# —", fg=t.hi, anchor="w",
                                     justify="left", padx=14, pady=8)
        self.hex_title.pack(fill="x")
        hexp.body.bind("<Configure>", lambda e: self.hex_title.config(
            wraplength=max(200, e.width - 30)))
        tk.Frame(hexp.body, bg=t.dim, height=2).pack(fill="x")
        hx = tk.Frame(hexp.body, bg=t.panel)
        hx.pack(fill="both", expand=True)
        self.hex_text = tk.Text(hx, font=self.f_mono, wrap="none",
                                bg=t.panel, fg=t.ink, relief="flat", bd=0,
                                padx=14, pady=10, insertwidth=0,
                                selectbackground=t.ink,
                                selectforeground=t.paper,
                                highlightthickness=0, cursor="arrow",
                                spacing1=1, spacing3=1)
        self.hex_text.tag_configure("off", foreground=t.acc)
        self.hex_text.tag_configure("hex", foreground=t.ink)
        self.hex_text.tag_configure("asc", foreground=t.hi)
        self.hex_text.tag_configure("muted", foreground=t.acc)
        hvsb = ttk.Scrollbar(hx, orient="vertical", command=self.hex_text.yview,
                             style="Pixel.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(hx, orient="horizontal",
                            command=self.hex_text.xview,
                            style="Pixel.Horizontal.TScrollbar")
        self.hex_text.configure(xscrollcommand=hsb.set, yscrollcommand=hvsb.set)
        hsb.pack(side="bottom", fill="x")
        hvsb.pack(side="right", fill="y")
        self.hex_text.pack(side="left", fill="both", expand=True)
        self.hex_text.config(state="disabled")
        pane.add(hexp, minsize=520, stretch="always")

    # ------------------------------------------------------------------ #
    # Catalogue, géométrie, carte des secteurs
    # ------------------------------------------------------------------ #
    def _scan_disk(self) -> None:
        self._sec_data, self._sec_used = [], []
        self._geom = (0, 0)
        if self.disk is None:
            return
        tracks, sectors = _probe_geometry(self.disk)
        self._geom = (tracks, sectors)
        for tr in range(tracks):
            drow, urow = [], []
            for se in range(sectors):
                try:
                    d = bytes(self.disk.get_sector(tr, se))
                except Exception:  # noqa: BLE001
                    d = b""
                drow.append(d)
                empty = not d or (d[0] in (0xE5, 0x00) and d.count(d[0]) == len(d))
                urow.append(not empty)
            self._sec_data.append(drow)
            self._sec_used.append(urow)

    def _find_file_sectors(self, data: bytes) -> Set[Tuple[int, int]]:
        """Secteurs dont le contenu figure dans ``data`` (détection par
        contenu : indépendante du format de répertoire)."""
        found: Set[Tuple[int, int]] = set()
        if not data:
            return found
        for tr, row in enumerate(self._sec_data):
            for se, sec in enumerate(row):
                if not self._sec_used[tr][se]:
                    continue
                for a in (0, 128, 256):
                    probe = sec[a:a + 48]
                    if len(probe) == 48 and len(set(probe)) > 2 and probe in data:
                        found.add((tr, se))
                        break
        return found

    def _map_layout(self) -> Optional[Tuple[int, int, int, int, int]]:
        tracks, sectors = self._geom
        if not tracks or not sectors:
            return None
        width = max(200, self.map_canvas.winfo_width())
        lab, gap = 30, 2
        cell = int((width - lab - gap * (tracks - 1)) / tracks)
        cell = max(4, min(cell, 22))
        return lab, cell, gap, tracks, sectors

    def _draw_map(self) -> None:
        t = self.t
        c = self.map_canvas
        c.delete("all")
        lay = self._map_layout()
        if lay is None:
            c.config(height=90)
            c.create_text(max(200, c.winfo_width()) / 2, 45,
                          text=L("no_disk_map"), font=self.f_head, fill=t.acc)
            self.map_title.config(text=L("map_title"))
            return
        lab, cell, gap, tracks, sectors = lay
        self.map_title.config(text=L("map_title_n", t=tracks, s=sectors))
        height = sectors * (cell + gap) + 26
        if int(float(c.cget("height"))) != height:
            c.config(height=height)
        for se in range(sectors):
            if sectors <= 12 or se % 2 == 0:
                c.create_text(lab - 8, se * (cell + gap) + cell / 2,
                              text=str(se), anchor="e", font=self.f_small,
                              fill=t.acc)
        for tr in range(tracks):
            x = lab + tr * (cell + gap)
            for se in range(sectors):
                y = se * (cell + gap)
                if (tr, se) in self._file_secs:
                    col = t.ink
                elif self._sec_used[tr][se]:
                    col = t.warm
                else:
                    col = t.dim
                c.create_rectangle(x, y, x + cell, y + cell, fill=col,
                                   outline="")
            if tr % 10 == 0 or tr == tracks - 1:
                anchor = "ne" if tr == tracks - 1 else "nw"
                xx = x + cell if tr == tracks - 1 else x
                c.create_text(xx, sectors * (cell + gap) + 4,
                              text=f"P{tr:02d}", anchor=anchor,
                              font=self.f_small, fill=t.acc)
        if self._cursor and self._cursor[0] < tracks and self._cursor[1] < sectors:
            tr, se = self._cursor
            x, y = lab + tr * (cell + gap), se * (cell + gap)
            c.create_rectangle(x, y, x + cell, y + cell, fill=t.hi, outline="")
            c.create_rectangle(x - 3, y - 3, x + cell + 3, y + cell + 3,
                               outline=t.hi, width=2)

    def _map_hit(self, event) -> Optional[Tuple[int, int]]:
        lay = self._map_layout()
        if lay is None:
            return None
        lab, cell, gap, tracks, sectors = lay
        tr = int((event.x - lab) // (cell + gap))
        se = int(event.y // (cell + gap))
        if 0 <= tr < tracks and 0 <= se < sectors and event.x >= lab:
            return tr, se
        return None

    def _on_map_click(self, event) -> None:
        hit = self._map_hit(event)
        if hit:
            self.sector_var.set(f"{hit[0]} {hit[1]}")
            self.show_sector()

    def _on_map_motion(self, event) -> None:
        hit = self._map_hit(event)
        if hit:
            tr, se = hit
            state = (L("map_file") if hit in self._file_secs else
                     L("map_used") if self._sec_used[tr][se]
                     else L("map_free"))
            self.status.config(text=L("st_sector_hover",
                                      t=tr, s=se, st=state))
        else:
            self.status.config(text=self._status_text)

    def _fs(self):
        """Système de fichiers du disque courant (CP/M auto-détecté)."""
        return (CpmFilesystem(self.disk) if is_cpm_disk(self.disk)
                else CpcFilesystem(self.disk))

    def _refresh_files(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._files = []
        if self.disk is not None:
            fs = self._fs()
            for f in fs.list_files():
                self._files.append(f)
                self.tree.insert(
                    "", "end", iid=str(len(self._files) - 1),
                    values=(f.name, f.source, f.type_name, f.length,
                            f"&{f.offset:05X}"))
        n = len(self._files)
        self.files_panel.head.config(
            text=L("panel_cat_n", n=n, s="S" if n > 1 else "")
            if self.disk is not None else L("panel_cat0"))

    def _selected_file(self) -> Optional[CpcFile]:
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx >= len(self._files):
            return None
        return self._files[idx]

    def _refresh(self, rescan: bool = True) -> None:
        if rescan:
            self._scan_disk()
            self._file_secs = set()
        if self.disk is None:
            self.info.config(text=L("lbl_geometry"))
            self.file_label.config(text=L("lbl_no_disk"))
        else:
            self.info.config(text=self.disk.summary())
            shown = self.path or L("lbl_new")
            if len(shown) > 60:
                shown = "…" + shown[-58:]
            self.file_label.config(text=f"A: {shown}")
        self._refresh_files()
        self._draw_map()

    # ------------------------------------------------------------------ #
    # Ouverture / création / sauvegarde
    # ------------------------------------------------------------------ #
    def open_disk(self) -> None:
        path = filedialog.askopenfilename(
            title=L("dlg_open_title"),
            filetypes=[(L("ft_dsk"), "*.dsk *.adf"), (L("ft_all"), "*.*")])
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            self.disk = ADFDisk.load(path)
        except (OSError, ADFError) as exc:
            self.error(L("err_open"), str(exc))
            return
        self.path = path
        self._cursor = None
        self._last_hex = None
        self._clear_hex()
        self._refresh()
        self._show_tab(0)
        self._set_status(L("st_opened", p=path))

    def new_disk(self) -> None:
        if self.disk is not None and not self.ask(
                L("dlg_new_title"), L("dlg_new_msg")):
            return
        self.disk = ADFDisk.new_blank()
        self.path = None
        self._cursor = None
        self._last_hex = None
        self._clear_hex()
        self._refresh()
        self._set_status(L("st_new_disk"))

    def new_cpm_disk(self) -> None:
        if self.disk is not None and not self.ask(
                L("dlg_new_title"), L("dlg_new_msg")):
            return
        self.disk = new_cpm_system_disk()
        self.path = None
        self._cursor = None
        self._last_hex = None
        self._clear_hex()
        self._refresh()
        self._set_status(L("st_new_cpm"))

    def _save_to(self, path: str) -> bool:
        try:
            self.disk.save(path)
        except OSError as exc:
            self.error(L("err_save"), str(exc))
            return False
        self.path = path
        self._refresh(rescan=False)
        return True

    def save_disk(self) -> None:
        if self.disk is None:
            self.info_box(L("dlg_save_title"), L("msg_no_disk"))
            return
        path = self.path or filedialog.asksaveasfilename(
            title=L("dlg_saveas_title"), defaultextension=".dsk",
            filetypes=[(L("ft_dsk"), "*.dsk")])
        if path and self._save_to(path):
            self._set_status(L("st_saved", p=path))

    def save_disk_as(self) -> None:
        """« Enregistrer sous » : sauvegarde la disquette sur un nouveau
        chemin (devient le chemin courant — les « Sauver » suivants
        écrivent sur ce nouveau fichier)."""
        if self.disk is None:
            self.info_box(L("btn_saveas"), L("msg_no_disk"))
            return
        path = filedialog.asksaveasfilename(
            title=L("dlg_saveas_title2"),
            defaultextension=".dsk",
            initialfile=os.path.basename(self.path) if self.path else None,
            filetypes=[(L("ft_dsk"), "*.dsk")])
        if path and self._save_to(path):
            self._set_status(L("st_savedas", p=path))

    def _persist(self) -> None:
        """Sauvegarde sur le chemin courant (ou propose un chemin)."""
        if self.path is not None:
            if self._save_to(self.path):
                self._set_status(L("st_saved", p=self.path))
            return
        self.save_disk()

    # ------------------------------------------------------------------ #
    # Inspection hex
    # ------------------------------------------------------------------ #
    def _clear_hex(self) -> None:
        self.hex_title.config(text="# —")
        self.hex_text.config(state="normal")
        self.hex_text.delete("1.0", "end")
        self.hex_text.config(state="disabled")

    def _show_hex(self, data: bytes, title: str) -> None:
        self._last_hex = (data, title)
        self.hex_title.config(text=f"# {title}")
        tx = self.hex_text
        tx.config(state="normal")
        tx.delete("1.0", "end")
        if not data:
            tx.insert("end", L("hex_empty"), "muted")
        else:
            tx.insert("end", "OFFSET    ", "muted")
            tx.insert("end", " ".join(f"{i:02X}" for i in range(16)), "muted")
            tx.insert("end", "  ASCII\n", "muted")
            for off, hx, asc in _hex_rows(data):
                tx.insert("end", off + "  ", "off")
                tx.insert("end", hx + "  ", "hex")
                tx.insert("end", asc + "\n", "asc")
        tx.config(state="disabled")
        tx.yview_moveto(0)

    def _on_file_select(self, _event) -> None:
        f = self._selected_file()
        if f is None or self.disk is None:
            return
        try:
            data = self._fs().read_file(f.name, source=f.source)
        except (CpcError, ADFError) as exc:
            self._show_hex(b"", f"{L('err_read')} : {exc}")
            return
        self._show_hex(
            data,
            f"{f.name}  [{f.source} {f.type_name} {f.length} {L('sz_b')}]  "
            f"load=&{f.load_addr:04X}  @&{f.offset:05X}")
        self._file_secs = self._find_file_sectors(data)
        self._draw_map()
        self._set_status(L("st_file", n=f.name, s=f.source,
                           k=len(self._file_secs)))

    def show_sector(self) -> None:
        if self.disk is None:
            self.info_box(L("dlg_sector_title"), L("msg_open_first"))
            return
        try:
            track_s, sec_s = self.sector_var.get().split()
            track, sector = int(track_s), int(sec_s)
            data = self.disk.get_sector(track, sector)
        except (ValueError, ADFError) as exc:
            self.error(L("err_sector"),
                       L("err_sector_fmt", v=self.sector_var.get(), e=exc))
            return
        self._cursor = (track, sector)
        self._draw_map()
        self._show_hex(
            bytes(data),
            L("hex_sector", t=track, s=sector, n=len(data), u=L("sz_b")))
        self._set_status(L("st_sector", t=track, s=sector))

    # ------------------------------------------------------------------ #
    # Actions fichiers
    # ------------------------------------------------------------------ #
    def add_file(self) -> None:
        if self.disk is None:
            self.info_box(L("dlg_add_title"), L("msg_create_first"))
            return
        local = filedialog.askopenfilename(
            title=L("dlg_add_file_title"))
        if not local:
            return
        self._do_add_file(local)

    def _do_add_file(self, local: str) -> None:
        dlg = AddFileDialog(self, _suggest_83(local),
                            cpm=is_cpm_disk(self.disk))
        self.root.wait_window(dlg.win)
        if dlg.result is None:
            return
        try:
            with open(local, "rb") as fh:
                data = fh.read()
            self._fs().write_file(
                dlg.result["name"], data,
                file_type=dlg.result["file_type"],
                load_addr=dlg.result["load_addr"],
                exec_addr=dlg.result["load_addr"],
                mode=dlg.result["mode"])
        except (CpcError, ADFError, OSError) as exc:
            self.error(L("err_write"), str(exc))
            return
        self._scan_disk()
        self._file_secs = set()
        self._persist()
        self._set_status(L("st_written",
                           n=repr(dlg.result["name"]),
                           sz=_fmt_size(len(data)),
                           m=dlg.result["mode"]))

    def extract_file(self) -> None:
        f = self._selected_file()
        if f is None or self.disk is None:
            self.info_box(L("dlg_extract_title"), L("msg_select_file"))
            return
        # Nom de fichier proposé avec l'extension CPC conservée :
        # « MONPROG BAS » -> « monprog.bas », sinon « nom.bin ».
        name = f.name.strip()
        if " " in name:
            base, _, ext = name.rpartition(" ")
            if ext in ("BAS", "BIN", "COM", "DOC", "SYS", "LIB", "B", "HEX",
                       "MD", "TXT"):
                base = base.strip()
                if base:
                    name = f"{base.lower()}.{ext.lower()}"
        out = filedialog.asksaveasfilename(
            title=L("dlg_extract_title2", n=f.name, s=f.source),
            initialfile=name)
        if not out:
            return
        try:
            data = self._fs().read_file(f.name, source=f.source)
            with open(out, "wb") as fh:
                fh.write(data)
        except (CpcError, ADFError, OSError) as exc:
            self.error(L("err_extract"), str(exc))
            return
        self._set_status(L("st_extracted", n=f.name, s=f.source, p=out,
                           sz=_fmt_size(len(data))))

    def delete_file(self) -> None:
        f = self._selected_file()
        if f is None or self.disk is None:
            self.info_box(L("dlg_delete_title"), L("msg_select_delete"))
            return
        if not self.ask(
                L("dlg_delete_q"),
                L("dlg_delete_msg", n=f.name, s=f.source, ty=f.type_name,
                  len=f.length, u=L("sz_b")),
                danger=True):
            return
        try:
            self._fs().delete_file(f.name)
        except (CpcError, ADFError) as exc:
            self.error(L("err_delete"), str(exc))
            return
        self._scan_disk()
        self._file_secs = set()
        self._last_hex = None
        self._clear_hex()
        self._persist()
        self._set_status(L("st_deleted", n=repr(f.name)))

    # ================================================================== #
    # Onglet Gotek
    # ================================================================== #
    def _build_gotek_tab(self) -> None:
        t = self.t
        tab = self.tab_gotek
        tab.columnconfigure(0, weight=4, uniform="g")
        tab.columnconfigure(1, weight=5, uniform="g")
        tab.rowconfigure(0, weight=1)

        # --- sources ---
        src = Panel(tab, self, L("panel_sources"))
        src.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.gtk_src_panel = src
        self._gotek_src_buttons = tk.Frame(src.body, bg=t.panel, padx=10,
                                           pady=10)
        self._gotek_src_buttons.pack(side="bottom", fill="x")
        tk.Frame(src.body, bg=t.dim, height=2).pack(side="bottom", fill="x")
        holder = tk.Frame(src.body, bg=t.panel)
        holder.pack(fill="both", expand=True, padx=6, pady=6)
        self.gtk_tree = ttk.Treeview(
            holder, columns=("num", "file", "size", "dest"), show="headings",
            selectmode="extended", style="Pixel.Treeview")
        for col, text, w, anchor in (("num", L("gcol_num"), 44, "w"),
                                     ("file", L("gcol_src"), 230, "w"),
                                     ("size", L("gcol_size"), 90, "e"),
                                     ("dest", L("gcol_dest"), 150, "w")):
            self.gtk_tree.heading(col, text=text, anchor=anchor)
            self.gtk_tree.column(col, width=w, anchor=anchor,
                                 stretch=col in ("file", "dest"))
        gsb = ttk.Scrollbar(holder, orient="vertical",
                            command=self.gtk_tree.yview,
                            style="Pixel.Vertical.TScrollbar")
        self.gtk_tree.configure(yscrollcommand=gsb.set)
        self.gtk_tree.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.gtk_tree.bind("<Delete>", lambda e: self.gotek_remove())

        # état vide : disquette 3" pixel art
        self.gtk_empty = tk.Frame(holder, bg=t.panel)
        cv = tk.Canvas(self.gtk_empty, width=24 * 5, height=28 * 5,
                       bg=t.panel, highlightthickness=0)
        cv.pack(pady=(0, 18))
        for x, y, w, h, key in FLOPPY:
            cv.create_rectangle(x * 5, y * 5, (x + w) * 5, (y + h) * 5,
                                fill=getattr(t, key), outline="")
        self._label(self.gtk_empty, L("no_disk_map"), font=self.f_head).pack()
        self._label(self.gtk_empty, L("g_empty_msg"),
                    fg=t.hi, justify="center").pack(pady=(14, 0))

        gs = self._gotek_src_buttons
        PixelButton(gs, self, L("btn_add"), kind="primary", icon="new",
                    padx=12, command=self.gotek_add).pack(side="left")
        PixelButton(gs, self, "", icon="up", padx=10,
                    command=lambda: self.gotek_move(-1)).pack(side="left",
                                                              padx=(8, 0))
        PixelButton(gs, self, "", icon="down", padx=10,
                    command=lambda: self.gotek_move(1)).pack(side="left",
                                                             padx=(6, 0))
        PixelButton(gs, self, L("btn_remove"), padx=12,
                    command=self.gotek_remove).pack(side="left", padx=8)
        PixelButton(gs, self, L("btn_clear"), kind="danger", padx=12,
                    command=self.gotek_clear).pack(side="left")

        # --- colonne droite ---
        right = tk.Frame(tab, bg=t.paper)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        res = Panel(right, self, L("panel_result"), accent=t.ink)
        res.pack(side="bottom", fill="both", expand=True, pady=(16, 0))
        self.gtk_bar = tk.Canvas(res.body, height=26, bg=t.panel,
                                 highlightthickness=0)
        self.gtk_bar.pack(fill="x", padx=14, pady=(12, 6))
        self.gtk_bar.bind("<Configure>", lambda e: self._draw_progress())
        self.gtk_result = tk.Text(res.body, font=self.f_mono, wrap="none",
                                  bg=t.panel, fg=t.ink, relief="flat", bd=0,
                                  padx=14, pady=6, height=4, insertwidth=0,
                                  highlightthickness=0, cursor="arrow",
                                  selectbackground=t.ink,
                                  selectforeground=t.paper)
        for tag, col in (("arrow", t.acc), ("name", t.hi), ("ok", t.ink),
                         ("err", t.danger), ("muted", t.acc)):
            self.gtk_result.tag_configure(tag, foreground=col)
        self.gtk_result.pack(fill="both", expand=True)
        self.gtk_result.config(state="disabled")


        opts = Panel(right, self, L("panel_opts"))
        opts.pack(fill="x")
        g = tk.Frame(opts.body, bg=t.panel, padx=14, pady=8)
        g.pack(fill="x")

        def lab(text, row):
            self._label(g, text, fg=t.acc, anchor="w").grid(
                row=row, column=0, sticky="w", pady=3, padx=(0, 14))

        lab(L("opt_pattern"), 0)
        self.entry(g, self.gtk_pattern, width=18).grid(row=0, column=1,
                                                       sticky="w", pady=3)
        lab(L("opt_subdir"), 1)
        self.entry(g, self.gtk_subfolder, width=18).grid(row=1, column=1,
                                                         sticky="w", pady=3)
        lab(L("opt_index"), 2)
        irow = tk.Frame(g, bg=t.panel)
        irow.grid(row=2, column=1, sticky="w", pady=3)
        self.entry(irow, self.gtk_index, width=5).pack(side="left")
        PixelButton(irow, self, "", icon="down", padx=8,
                    command=lambda: self._gotek_step(-1)).pack(side="left",
                                                               padx=(8, 0))
        PixelButton(irow, self, "", icon="up", padx=8,
                    command=lambda: self._gotek_step(1)).pack(side="left",
                                                              padx=(6, 0))
        lab(L("opt_preview"), 3)
        self.gtk_preview = self._label(g, "", fg=t.hi, anchor="w")
        self.gtk_preview.grid(row=3, column=1, sticky="w", pady=3)

        out = Panel(right, self, L("panel_out"))
        out.pack(fill="x", pady=(16, 0))
        orow = tk.Frame(out.body, bg=t.panel, padx=14, pady=12)
        orow.pack(fill="x")
        self.entry(orow, self.gtk_outdir, width=30).pack(side="left", fill="x",
                                                         expand=True)
        PixelButton(orow, self, L("btn_choose"), icon="open",
                    command=self.gotek_choose_outdir).pack(side="left",
                                                           padx=(10, 0))
        acts = tk.Frame(out.body, bg=t.panel, padx=14)
        acts.pack(fill="x", pady=(0, 14))
        PixelButton(acts, self, L("btn_gen"), kind="primary", padx=12,
                    command=self.gotek_prepare).pack(side="left")
        PixelButton(acts, self, L("btn_verify"), padx=12,
                    command=self.gotek_verify).pack(side="left", padx=8)
        PixelButton(acts, self, L("btn_fatimg"), padx=12,
                    command=self.gotek_fat_image).pack(side="left")

        # Chargement d'une image existante (.img) : liste le contenu, puis
        # « → Sources » (disquettes vers la pile) ou « Extraire… » (dossier).
        acts2 = tk.Frame(out.body, bg=t.panel, padx=14)
        acts2.pack(fill="x", pady=(0, 14))
        PixelButton(acts2, self, L("btn_loadimg"), icon="open", padx=10,
                    command=self.gotek_load_image).pack(side="left")
        PixelButton(acts2, self, L("btn_tosrc"), icon="up", padx=10,
                    command=self.gotek_img_to_sources).pack(side="left",
                                                            padx=8)
        PixelButton(acts2, self, L("btn_extract2"), icon="extract", padx=10,
                    command=self.gotek_img_extract).pack(side="left")

        self._gotek_refresh_tree()
        self._gotek_result_render()

    # ------------------------------------------------------------------ #
    def _gotek_names(self, n: int) -> List[str]:
        """Aperçu des noms de sortie (patron de type « DISK%03d.adf »)."""
        pat = self.gtk_pattern.get() or DEFAULT_NAME_PATTERN
        try:
            start = int(self.gtk_index.get())
        except ValueError:
            start = 1
        sub = self.gtk_subfolder.get().strip("/")
        names = []
        for i in range(n):
            try:
                name = pat % (start + i)
            except (TypeError, ValueError):
                name = pat
            names.append(f"{sub}/{name}" if sub else name)
        return names

    def _gotek_names_changed(self) -> None:
        try:
            self._gotek_refresh_tree()
        except (tk.TclError, AttributeError):
            pass

    def _gotek_step(self, d: int) -> None:
        try:
            v = int(self.gtk_index.get())
        except ValueError:
            v = 1
        self.gtk_index.set(str(max(0, min(999, v + d))))

    def _gotek_refresh_tree(self) -> None:
        sel = [int(i) for i in self.gtk_tree.selection()]
        self.gtk_tree.delete(*self.gtk_tree.get_children())
        names = self._gotek_names(len(self._gotek_sources))
        for i, p in enumerate(self._gotek_sources):
            try:
                size = _fmt_size(os.path.getsize(p))
            except OSError:
                size = "?"
            self.gtk_tree.insert("", "end", iid=str(i),
                                 values=(f"{i + 1:02d}", os.path.basename(p),
                                         size, names[i]))
        keep = [str(i) for i in sel if i < len(self._gotek_sources)]
        if keep:
            self.gtk_tree.selection_set(keep)
        n = len(self._gotek_sources)
        self.gtk_src_panel.head.config(
            text=L("panel_sources_n", n=n, s="S" if n > 1 else "") if n
            else L("panel_sources0"))
        if n:
            self.gtk_empty.place_forget()
        else:
            self.gtk_empty.place(relx=0.5, rely=0.5, anchor="center")
        prev = self._gotek_names(3)
        self.gtk_preview.config(text=", ".join(prev) + "…")

    def _gotek_config(self) -> GotekConfig:
        try:
            return GotekConfig(
                name_pattern=self.gtk_pattern.get() or DEFAULT_NAME_PATTERN,
                subfolder=self.gtk_subfolder.get().strip("/"),
                start_index=int(self.gtk_index.get()),
            )
        except Exception as exc:  # noqa: BLE001 — limite d'entrée GUI
            raise GotekError(L("err_gopts", e=exc)) from exc

    def _gotek_check(self) -> bool:
        if not self._gotek_sources:
            self.info_box(L("dlg_gsrc_title"), L("dlg_gsrc_msg"))
            return False
        if not self.gtk_outdir.get().strip():
            self.info_box(L("dlg_gout_title"), L("dlg_gout_msg"))
            return False
        return True

    def gotek_add(self) -> None:
        paths = filedialog.askopenfilenames(
            title=L("dlg_gadd_title"),
            filetypes=[(L("ft_dsk"), "*.dsk *.adf"), (L("ft_all"), "*.*")])
        if paths:
            self.gotek_add_paths(list(paths))

    def gotek_add_paths(self, paths: List[str]) -> None:
        for p in paths:
            if p not in self._gotek_sources:
                self._gotek_sources.append(p)
        self._gotek_refresh_tree()
        self._set_status(L("st_gsrc", n=len(self._gotek_sources)))

    def gotek_remove(self) -> None:
        idx = sorted((int(i) for i in self.gtk_tree.selection()), reverse=True)
        for i in idx:
            del self._gotek_sources[i]
        self.gtk_tree.selection_set(())
        self._gotek_refresh_tree()

    def gotek_move(self, d: int) -> None:
        sel = self.gtk_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        j = i + d
        if not 0 <= j < len(self._gotek_sources):
            return
        s = self._gotek_sources
        s[i], s[j] = s[j], s[i]
        self.gtk_tree.selection_set(())
        self._gotek_refresh_tree()
        self.gtk_tree.selection_set(str(j))
        self.gtk_tree.see(str(j))

    def gotek_clear(self) -> None:
        if self._gotek_sources and not self.ask(
                L("dlg_gclear_title"), L("dlg_gclear_msg"), danger=True):
            return
        self._gotek_sources = []
        self._gotek_refresh_tree()

    def gotek_choose_outdir(self) -> None:
        d = filedialog.askdirectory(title=L("dlg_goutdir_title"))
        if d:
            self.gtk_outdir.set(d)

    def _draw_progress(self) -> None:
        t = self.t
        c = self.gtk_bar
        c.delete("all")
        w = max(100, c.winfo_width())
        n, gap = 28, 3
        cell = (w - gap * (n - 1)) / n
        lit = round(self._gtk_progress * n)
        for i in range(n):
            x = i * (cell + gap)
            c.create_rectangle(x, 2, x + cell, 24,
                               fill=t.ink if i < lit else t.dim, outline="")

    def _gotek_result_show(self, lines: List[str], tag: str = "OK",
                           progress: float = 1.0) -> None:
        self._gtk_last = [(os.path.basename(str(x)), tag) for x in lines]
        self._gtk_progress = progress
        self._gotek_result_render()

    def _gotek_result_render(self) -> None:
        tx = self.gtk_result
        tx.config(state="normal")
        tx.delete("1.0", "end")
        if not self._gtk_last:
            tx.insert("end", "> " + L("res_wait") + "\n", "muted")
        for name, tag in self._gtk_last:
            if tag == "ERR":
                tx.insert("end", f"! {name}\n", "err")
                continue
            tx.insert("end", "> ", "arrow")
            tx.insert("end", name + "  ", "name")
            tx.insert("end", tag + "\n", "ok")
        tx.insert("end", "\nReady\n", "ok")
        tx.config(state="disabled")
        self._draw_progress()

    def gotek_prepare(self) -> None:
        if not self._gotek_check():
            return
        try:
            config = self._gotek_config()
            created = prepare_usb_directory(
                self.gtk_outdir.get().strip(), self._gotek_sources, config)
        except (GotekError, ADFError, OSError) as exc:
            self._gotek_result_show([str(exc)], tag="ERR", progress=0)
            self.error(L("err_ggen"), str(exc))
            return
        self._gotek_result_show(created)
        self._set_status(L("st_ggen", n=len(created),
                           d=self.gtk_outdir.get().strip()))

    def gotek_verify(self) -> None:
        out = self.gtk_outdir.get().strip()
        if not out:
            self.info_box(L("dlg_gver_title"), L("dlg_gver_msg"))
            return
        try:
            valid = verify_usb_directory(out)
        except (GotekError, ADFError, OSError) as exc:
            self._gotek_result_show([str(exc)], tag="ERR", progress=0)
            self.error(L("dlg_gver_title"), str(exc))
            return
        self._gotek_result_show(valid, tag=L("tag_valid"))
        self._set_status(L("st_gver", n=len(valid), d=out))

    def gotek_fat_image(self) -> None:
        # Le répertoire « Sortie » n'est PAS requis ici (il ne sert qu'au
        # générer/vérifier) : le dialogue de sauvegarde donne le .img.
        if not self._gotek_sources:
            self.info_box(L("dlg_gsrc_title"), L("dlg_gsrc_msg"))
            return
        out_img = filedialog.asksaveasfilename(
            title=L("dlg_fatimg_dlg"),
            defaultextension=".img",
            filetypes=[(L("ft_img"), "*.img")])
        if not out_img:
            return
        try:
            config = self._gotek_config()
            create_fat_image(out_img, self._gotek_sources, config)
        except GotekError as exc:
            self.info_box(L("dlg_fatimg_title"), str(exc))
            return
        except (OSError, ADFError) as exc:
            self._gotek_result_show([str(exc)], tag="ERR", progress=0)
            self.error(L("err_fatimg"), str(exc))
            return
        self._gotek_result_show([out_img], tag=L("tag_fatok"))
        self._set_status(L("st_fatimg", p=out_img))

    # ------------------------------------------------------------------ #
    # Chargement d'une image FAT16 existante (.img de clé Gotek)
    # ------------------------------------------------------------------ #
    def gotek_load_image(self) -> None:
        """Charge une image ``.img`` et liste son contenu dans Résultat."""
        img = filedialog.askopenfilename(
            title=L("dlg_loadimg_dlg"),
            filetypes=[(L("ft_img"), "*.img *.bin *.raw"),
                       (L("ft_all"), "*.*")])
        if not img:
            return
        try:
            files = list_fat_image(img)
        except (GotekError, OSError) as exc:
            self._gotek_result_show([str(exc)], tag="ERR", progress=0)
            self.error(L("err_loadimg_title"), str(exc))
            return
        self._gotek_img = img
        self._gotek_img_files = files
        if not files:
            self._gotek_result_show([L("loadimg_empty")],
                                    tag=L("tag_video"), progress=0)
            self._set_status(L("st_loadimg_empty",
                               n=os.path.basename(img)))
            return
        lines = [f"{f.name}  {_fmt_size(f.size)}" for f in files]
        self._gotek_result_show(lines, tag=L("tag_inimg"))
        self._set_status(L("st_loadimg", n=len(files),
                           m=os.path.basename(img)))

    def gotek_img_to_sources(self) -> None:
        """Extrait les .dsk/.adf de l'image chargée dans un dossier temp et
        les ajoute à la pile des sources Gotek."""
        if not self._gotek_img_files:
            self.info_box(L("dlg_noinfo_title"), L("dlg_noinfo_msg"))
            return
        disks = [f for f in self._gotek_img_files
                 if f.name.lower().endswith((".adf", ".dsk"))]
        if not disks:
            self.info_box(L("dlg_nodisk_title"), L("dlg_nodisk_msg"))
            return
        tmp = tempfile.mkdtemp(prefix="cpc-gotek-")
        added: List[str] = []
        for f in disks:
            p = os.path.join(tmp, f.name)
            try:
                with open(p, "wb") as fh:
                    fh.write(f.data)
            except OSError as exc:
                self.error(L("err_tmp"), str(exc))
                return
            added.append(p)
        self.gotek_add_paths(added)
        self._set_status(L("st_gsrc_added", n=len(added), d=tmp))

    def gotek_img_extract(self) -> None:
        """Extrait tous les fichiers de l'image chargée dans un dossier choisi."""
        if not self._gotek_img_files:
            self.info_box(L("dlg_noinfo_title"), L("dlg_noinfo_msg"))
            return
        d = filedialog.askdirectory(title=L("dlg_extract_dlg"))
        if not d:
            return
        try:
            for f in self._gotek_img_files:
                with open(os.path.join(d, f.name), "wb") as fh:
                    fh.write(f.data)
        except OSError as exc:
            self.error(L("err_extract"), str(exc))
            return
        self._gotek_result_show([f.name for f in self._gotek_img_files],
                                tag=L("tag_extracted"))
        self._set_status(L("st_gextracted", n=len(self._gotek_img_files), d=d))

    # ================================================================== #
    # Glisser-déposer (explorateur Windows)
    # ================================================================== #
    def _on_drop(self, paths: List[str]) -> None:
        """Fichiers déposés sur la fenêtre.

        - ``.dsk``/``.adf`` : ouverts (onglet Disquette, rien d'ouvert) ou
          ajoutés aux sources Gotek (onglet Gotek actif, ou disquette déjà
          ouverte),
        - autres fichiers : ajoutés à la disquette ouverte (dialogue 8.3).
        """
        disks = [p for p in paths if p.lower().endswith((".dsk", ".adf"))]
        others = [p for p in paths if p not in disks]

        if disks:
            if self._tab == 1:
                self.gotek_add_paths(disks)
                return
            if self.disk is None:
                self._open_path(disks[0])
            else:
                self.gotek_add_paths(disks)
                self._show_tab(1)
                return

        for p in others:
            if self.disk is None:
                self.info_box(L("dlg_add_title"), L("msg_create_first"))
                return
            self._do_add_file(p)

    # ================================================================== #
    # Divers
    # ================================================================== #
    def _set_status(self, text: str) -> None:
        self._status_text = text
        try:
            self.status.config(text=text)
        except (tk.TclError, AttributeError):
            pass

    def info_box(self, title: str, message: str) -> None:
        PixelDialog(self, title, message, kind="info")

    def error(self, title: str, message: str) -> None:
        PixelDialog(self, title, message, kind="error")

    def ask(self, title: str, message: str, danger: bool = False) -> bool:
        yes = ((L("dlg_yes_danger"), True, "danger") if danger
               else (L("dlg_yes"), True, "primary"))
        dlg = PixelDialog(self, title, message,
                          kind="danger" if danger else "ask",
                          buttons=((L("dlg_no"), False, "normal"), yes))
        return bool(dlg.result)


def run() -> None:
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Windows 8.1+
        except Exception:  # noqa: BLE001
            try:
                ctypes.windll.user32.SetProcessDPIAware()   # Windows 7
            except Exception:  # noqa: BLE001
                pass
    _load_private_fonts()
    root = tk.Tk()
    _apply_window_icon(root)
    DskEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
