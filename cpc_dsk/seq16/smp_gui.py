"""smp_gui.py : éditeur graphique de banques de samples .SMP pour SEQ-16.

Rôle
----
Un éditeur (tkinter, bibliothèque standard uniquement) pour fabriquer une
banque .SMP à partir de fichiers WAV, sans ligne de commande :
  - liste des samples de la banque (16 au plus) : ajouter des WAV, retirer,
    monter / descendre, ouvrir une banque .SMP existante ;
  - réglages de chaque sample (nom, fréquence, bits, décimation, courbe,
    drive, trim, clean, tramage, découpage en tranches) ;
  - forme d'onde : le WAV d'origine et le rendu simulé du CPC ;
  - écoute du son d'origine et du rendu CPC ;
  - jauge de mémoire (16 064 octets au plus) ;
  - sauvegarde du .SMP et ajout à une disquette .dsk.

Toute la conversion est faite par smp_model.py (sans interface), qui
s'appuie sur wav2smp.py et sur le catalogue AMSDOS de CPC DISK (dskio.py).

Deux façons de l'utiliser :
  - fenêtre autonome :  python -m cpc_dsk.seq16.smp_gui [fichiers]
    SmpApp(tk.Tk()) gère alors la fenêtre (titre, taille, DPI, zone de
    travail Windows, raccourcis, glisser-déposer, fermeture) ;
  - onglet « SAMPLES SEQ-16 » de CPC DISK : SmpApp(cadre, host=app) se
    construit dans un tk.Frame, reprend le thème de l'application (F3) et
    ne touche pas à la fenêtre ; les raccourcis Ctrl+W / Ctrl+O / Ctrl+S et
    le glisser-déposer lui sont transmis par CPC DISK quand l'onglet est
    affiché, et « Ajouter à la disquette » peut viser la disquette ouverte
    dans l'onglet Disquette.

Textes : table cpc_dsk/i18n.py (clés smp_*), langue de l'application.

Habillage repris de CPC DISK : palette du firmware CPC (bleu, jaune, cyan)
ou moniteur vert GT65 (F3), polices pixel « Press Start 2P » et « VT323 »
(licence OFL) du dossier cpc_dsk/fonts/.

Raccourcis (fenêtre autonome) : Ctrl+O ouvrir un .SMP, Ctrl+W ajouter des
WAV, Ctrl+S sauver, Suppr retirer le sample, F3 moniteur couleur / vert,
F1 aide.
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont
from types import SimpleNamespace

from . import wav2smp
from .smp_model import BankError, BankModel, RATE_PRESETS, dsk_name
from ..i18n import detect_language, set_language
from ..i18n import t as L

HERE = os.path.dirname(os.path.abspath(__file__))
# Dossier de départ des boîtes de fichiers (samples/ et build/ s'ils
# existent, comme dans le dépôt SEQ-16) : le dossier courant.
ROOT = os.getcwd()
# Polices : cpc_dsk/fonts/ (même endroit sous PyInstaller, voir build_exe.bat).
FONT_DIR = os.path.join(os.path.dirname(HERE), "fonts")
PIXEL_TITLE = "Press Start 2P"
PIXEL_BODY = "VT323"

# Noms des courbes (dans l'ordre de wav2smp.CURVES) ; l'interface affiche
# les clés smp_curve_0 à smp_curve_4 de la langue courante.
CURVE_LABELS = ["LINEAIRE", "LOG", "SATUREE", "REPLIEE", "INVERSEE"]

# ====================================================================== #
# Thèmes (palette du firmware CPC / moniteur vert GT65), comme CPC DISK
# ====================================================================== #
THEMES = {
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

# Icônes 8x8 (X = pixel allumé), dessinées à l'échelle 2.
ICONS = {
    "open": ("........", "XXX.....", "XXXXXXXX", "XXXXXXXX",
             "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "........"),
    "new": ("...XX...", "...XX...", "...XX...", "XXXXXXXX",
            "XXXXXXXX", "...XX...", "...XX...", "...XX..."),
    "save": ("XXXXXXX.", "XX...XXX", "XX...XXX", "XXXXXXXX",
             "XXXXXXXX", "XX....XX", "XX....XX", "XXXXXXXX"),
    "trash": ("..XXXX..", "XXXXXXXX", "........", ".XXXXXX.",
              ".X.XX.X.", ".X.XX.X.", ".X.XX.X.", ".XXXXXX."),
    "up": ("........", "...XX...", "..XXXX..", ".XXXXXX.",
           "XXXXXXXX", "...XX...", "...XX...", "........"),
    "down": ("........", "...XX...", "...XX...", "XXXXXXXX",
             ".XXXXXX.", "..XXXX..", "...XX...", "........"),
    "play": (".X......", ".XXX....", ".XXXXX..", ".XXXXXXX",
             ".XXXXXXX", ".XXXXX..", ".XXX....", ".X......"),
    "stop": ("........", ".XXXXXX.", ".XXXXXX.", ".XXXXXX.",
             ".XXXXXX.", ".XXXXXX.", ".XXXXXX.", "........"),
    "disk": ("XXXXXXXX", "X.XXXX.X", "X.XXXX.X", "XXXXXXXX",
             "X......X", "X.XXXX.X", "X......X", "XXXXXXXX"),
    "cut": ("X.....X.", ".X...X..", "..X.X...", "...X....",
            "..X.X...", "XX...XX.", "XX...XX.", "........"),
}


# ====================================================================== #
# Utilitaires
# ====================================================================== #
def _mix(c1, c2, a):
    """Mélange deux couleurs #RRGGBB (a = part de c2)."""
    x = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    y = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02X" % round(p + (q - p) * a) for p, q in zip(x, y))


def _num(n):
    """Entier avec séparateur de milliers de la langue : 16320 -> '16 320'
    (fr), '16,320' (en), '16.320' (es)."""
    return "{:,}".format(n).replace(",", L("smp_sep_thousands"))


def _sec(s):
    """Durée en secondes, virgule décimale de la langue : 0.52 -> '0,52 s'."""
    return ("%.2f s" % s).replace(".", L("smp_sep_decimal"))


def _initdir(sub):
    """Dossier ROOT/sub s'il existe, sinon ROOT."""
    d = os.path.join(ROOT, sub)
    return d if os.path.isdir(d) else ROOT


def _load_private_fonts():
    """Rend les .ttf du dossier fonts/ visibles par Tk (Windows seulement).
    À appeler AVANT la création de la fenêtre Tk. Ailleurs, les polices
    doivent être installées ; sinon une police à chasse fixe les remplace."""
    if sys.platform != "win32" or not os.path.isdir(FONT_DIR):
        return
    try:
        import ctypes
        gdi32 = ctypes.windll.gdi32
        gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint,
                                             ctypes.c_void_p]
        FR_PRIVATE = 0x10                       # police visible de ce seul processus
        for name in os.listdir(FONT_DIR):
            if name.lower().endswith((".ttf", ".otf")):
                gdi32.AddFontResourceExW(os.path.join(FONT_DIR, name),
                                         FR_PRIVATE, None)
    except Exception:  # noqa: BLE001 - confort visuel, pas critique
        pass


def _register_drag_drop(root, on_drop):
    """Glisser-déposer de fichiers depuis l'explorateur Windows, sans
    dépendance (même méthode que CPC DISK : DragAcceptFiles puis
    sous-classement de la procédure de fenêtre pour lire WM_DROPFILES).
    Renvoie False hors Windows ou en cas d'échec."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        WM_DROPFILES, GWLP_WNDPROC = 0x0233, -4
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)
        set_wl = (user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                  else user32.SetWindowLongW)
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
        try:                                    # processus admin : laisser passer
            user32.ChangeWindowMessageFilterEx.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p]
            for msg in (WM_DROPFILES, 0x004A, 0x0049):
                user32.ChangeWindowMessageFilterEx(hwnd, msg, 1, None)
        except Exception:  # noqa: BLE001
            pass
        old_proc = [None]

        def _wndproc(h, msg, wp, lp):
            """Intercepte WM_DROPFILES, laisse le reste à Tk."""
            if msg == WM_DROPFILES:
                count = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                buf = ctypes.create_unicode_buffer(32768)
                paths = [buf.value for i in range(count)
                         if shell32.DragQueryFileW(wp, i, buf, 32768)]
                shell32.DragFinish(wp)
                if paths:
                    root.after(0, lambda p=paths: on_drop(p))
                return 0
            return user32.CallWindowProcW(old_proc[0], h, msg, wp, lp)

        callback = WNDPROC(_wndproc)
        globals()["_drag_drop_callback"] = callback   # garder une référence
        old_proc[0] = set_wl(hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
        if not old_proc[0]:
            return False
        shell32.DragAcceptFiles(hwnd, True)
        return True
    except Exception:  # noqa: BLE001 - confort, pas critique
        return False


# ====================================================================== #
# Écoute
# ====================================================================== #
class Player:
    """Joue un WAV (octets) sans bloquer l'interface.

    Windows : winsound.PlaySound en asynchrone. CPython refuse
    SND_MEMORY avec SND_ASYNC (« Cannot play asynchronously from memory ») :
    le WAV en mémoire est donc écrit dans un fichier temporaire, joué avec
    SND_FILENAME | SND_ASYNC.
    Ailleurs : fichier temporaire joué par aplay, paplay ou afplay."""

    PLAYERS = (["aplay", "-q"], ["paplay"], ["afplay"])

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="smp_gui_")
        self.proc = None
        self.count = 0

    def play(self, data):
        """Joue data (fichier WAV complet en octets). Renvoie None si la
        lecture démarre, sinon un message d'erreur (langue de l'interface)."""
        self.stop()
        self.count += 1
        path = os.path.join(self.tmp, "ecoute%d.wav" % (self.count % 8))
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            return L("smp_play_tmp", e=e)
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME
                                   | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return None
            except Exception as e:  # noqa: BLE001
                return L("smp_play_err", e=e)
        for cmd in self.PLAYERS:
            if shutil.which(cmd[0]):
                try:
                    self.proc = subprocess.Popen(cmd + [path],
                                                 stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
                    return None
                except OSError:
                    continue
        return L("smp_play_none", p=path)

    def stop(self):
        """Arrête la lecture en cours."""
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None

    def close(self):
        """Arrête et efface les fichiers temporaires."""
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ====================================================================== #
# Widgets pixel art (repris de CPC DISK, en plus compact)
# ====================================================================== #
class PixelButton(tk.Canvas):
    """Bouton à relief 4 px, coins crantés, icône 8x8 facultative."""

    KINDS = {"normal": ("btn", "btn_ink"), "primary": ("pri", "pri_ink"),
             "danger": ("danger", "danger_ink")}

    def __init__(self, master, app, text="", command=None, kind="normal",
                 icon=None, padx=12):
        """Crée le bouton ; text est mis en capitales sans accents."""
        bg_key, fg_key = self.KINDS[kind]
        self._bg, self._fg = getattr(app.t, bg_key), getattr(app.t, fg_key)
        self._dim = app.t.dim
        self._text = app.caps(text)
        self._icon, self._cmd, self._font, self._padx = icon, command, app.f_btn, padx
        self._hover = self._press = self._focus = False
        self._enabled = True
        tw = self._font.measure(self._text) if self._text else 0
        iw = 16 if icon else 0
        self._content_w = tw + iw + (8 if icon and text else 0)
        self._bw = self._content_w + 2 * padx + 8
        self._bh = max(34, self._font.metrics("linespace") + 16)
        super().__init__(master, width=self._bw, height=self._bh,
                         bg=master.cget("bg"), highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, press=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(press=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda e: self._set(focus=True))
        self.bind("<FocusOut>", lambda e: self._set(focus=False))
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<Return>", lambda e: self.invoke())
        self._draw()

    def set_enabled(self, on):
        """Active ou grise le bouton."""
        self._enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def invoke(self):
        """Lance la commande (si le bouton est actif)."""
        if self._cmd and self._enabled:
            self._cmd()

    def _release(self, event):
        """Clic validé seulement si on relâche sur le bouton."""
        inside = 0 <= event.x < self._bw and 0 <= event.y < self._bh
        was = self._press
        self._set(press=False)
        if was and inside:
            self.invoke()

    def _set(self, **kw):
        """Change un état (survol, appui, focus) et redessine."""
        for k, v in kw.items():
            setattr(self, "_" + k, v)
        self._draw()

    def _draw(self):
        """Dessine le bouton : corps, relief, icône, texte."""
        w, h, n = self._bw, self._bh, 4
        self.delete("all")
        base = self._bg if self._enabled else self._dim
        body = _mix(base, "#FFFFFF", 0.15) if self._hover and self._enabled else base
        light, dark = _mix(body, "#FFFFFF", 0.55), _mix(body, "#000000", 0.35)
        press = self._press and self._enabled
        tl, br = (dark, _mix(body, "#FFFFFF", 0.35)) if press else (light, dark)
        self.create_polygon(0, n, n, n, n, 0, w - n, 0, w - n, n, w, n,
                            w, h - n, w - n, h - n, w - n, h, n, h, n, h - n,
                            0, h - n, fill=body, outline="")
        self.create_rectangle(n, 0, w - n, n, fill=tl, outline="")
        self.create_rectangle(0, n, n, h - n, fill=tl, outline="")
        self.create_rectangle(n, h - n, w - n, h, fill=br, outline="")
        self.create_rectangle(w - n, n, w, h - n, fill=br, outline="")
        fg = self._fg if self._enabled else _mix(self._dim, "#FFFFFF", 0.4)
        off = 2 if press else 0
        x = (w - self._content_w) / 2 + off
        cy = h / 2 + off
        if self._icon:
            for r, line in enumerate(ICONS[self._icon]):
                for c, ch in enumerate(line):
                    if ch == "X":
                        px, py = x + c * 2, cy - 8 + r * 2
                        self.create_rectangle(px, py, px + 2, py + 2, fill=fg,
                                              outline="")
            x += 16 + (8 if self._text else 0)
        if self._text:
            self.create_text(x, cy + 1, text=self._text, anchor="w",
                             font=self._font, fill=fg)
        if self._focus:
            self.create_rectangle(6, 6, w - 6, h - 6, outline=fg, dash=(2, 2))


class Panel(tk.Frame):
    """Cadre bordé 4 px avec bandeau de titre en vidéo inverse."""

    def __init__(self, master, app, title):
        """title : texte du bandeau (mis en capitales)."""
        super().__init__(master, bg=app.t.acc, padx=4, pady=4)
        self.head = tk.Label(self, text=app.caps(title), bg=app.t.acc,
                             fg=app.t.paper, font=app.f_head, anchor="w",
                             padx=8, pady=4)
        self.head.pack(fill="x")
        self.body = tk.Frame(self, bg=app.t.panel)
        self.body.pack(fill="both", expand=True)


class Segmented(tk.Frame):
    """Choix exclusif en cases pixel (remplace un menu déroulant)."""

    def __init__(self, master, app, var, options):
        """options : liste de (valeur, texte affiché)."""
        super().__init__(master, bg=master.cget("bg"))
        self.app, self.var = app, var
        self._enabled = True
        self._labels = []
        for value, label in options:
            lbl = tk.Label(self, text=label, font=app.f_body, padx=7, pady=0,
                           cursor="hand2", highlightthickness=2, takefocus=1)
            lbl.pack(side="left", padx=(0, 4))
            lbl.bind("<Button-1>", lambda e, v=value: self._pick(v))
            lbl.bind("<space>", lambda e, v=value: self._pick(v))
            self._labels.append((value, lbl))
        self._trace = var.trace_add("write", lambda *a: self._paint())
        self.bind("<Destroy>", self._untrace, add="+")
        self._paint()

    def _pick(self, value):
        """Choisit une valeur (si actif)."""
        if self._enabled:
            self.var.set(value)

    def set_enabled(self, on):
        """Active ou grise le choix."""
        self._enabled = bool(on)
        self._paint()

    def _untrace(self, _e=None):
        """Retire la surveillance de la variable à la destruction."""
        try:
            self.var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass

    def _paint(self):
        """Colore la case choisie en vidéo inverse."""
        t = self.app.t
        for value, lbl in self._labels:
            on = value == self.var.get()
            if self._enabled:
                bg, fg, hl = (t.ink, t.paper, t.ink) if on else (t.panel, t.acc, t.acc)
            else:
                bg, fg, hl = (t.dim, t.paper, t.dim) if on else (t.panel, t.dim, t.dim)
            try:
                lbl.config(bg=bg, fg=fg, highlightbackground=hl, highlightcolor=t.hi)
            except tk.TclError:
                pass


class PixelDialog:
    """Boîte modale (info / erreur / question) dans le style CPC."""

    def __init__(self, app, title, message, kind="info",
                 buttons=(("OK", True, "primary"),)):
        """buttons : liste de (texte, valeur renvoyée, genre de bouton)."""
        t = app.t
        self.result = None
        accent = {"info": t.acc, "error": t.danger, "ask": t.ink}.get(kind, t.acc)
        head_fg = t.danger_ink if kind == "error" else t.paper
        self.win = win = tk.Toplevel(app.root)
        win.title(title)
        win.configure(bg=accent)
        win.transient(app.root)
        win.resizable(False, False)
        tk.Label(win, text=app.caps(title), bg=accent, fg=head_fg,
                 font=app.f_head, anchor="w", padx=12, pady=8).pack(
            fill="x", padx=4, pady=(4, 0))
        body = tk.Frame(win, bg=t.panel, padx=18, pady=14)
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        tk.Label(body, text=message, bg=t.panel, fg=t.hi, font=app.f_body,
                 justify="left", wraplength=560, anchor="w").pack(fill="x", pady=(0, 14))
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
        win.update_idletasks()                  # centrer sur la fenêtre principale
        x = app.root.winfo_rootx() + (app.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        win.grab_set()
        if first is not None:
            first.focus_set()
        app.root.wait_window(win)

    def _close(self, value):
        """Ferme la boîte en gardant la réponse."""
        self.result = value
        self.win.destroy()


# ====================================================================== #
# Application
# ====================================================================== #
class SmpApp:
    """L'éditeur de banques : fenêtre autonome ou onglet de CPC DISK."""

    def __init__(self, root, model=None, host=None):
        """root : fenêtre Tk (mode autonome) ou cadre parent (mode intégré) ;
        model : BankModel (un neuf par défaut) ; host : l'application CPC DISK
        qui accueille l'éditeur (thème, échelle, disquette ouverte)."""
        self.host = host
        self.embedded = host is not None or not isinstance(root, (tk.Tk, tk.Toplevel))
        self.parent = root                      # cadre (ou fenêtre) qui reçoit l'éditeur
        self.root = root.winfo_toplevel()       # fenêtre : boîtes, after(), curseur
        self.model = model or BankModel()
        self.player = Player()
        self.bank_path = None                   # dernier .SMP ouvert ou sauvé
        self.dsk_path = os.path.join(ROOT, "build", "seq16.dsk")
        self._theme_name = "couleur"
        self._sel_index = None                  # sample choisi
        self._loading = False                   # vrai pendant le remplissage des champs
        self._apply_id = None                   # réglage en attente (anti-rebond)
        self._status_text = L("smp_st_ready_tab" if self.embedded else "smp_st_ready")
        self._status_err = False
        self.scale = self._scale()
        if not self.embedded:
            self._setup_window()
        else:
            atexit.register(self.player.close)  # pas de fermeture propre à l'onglet

        # Variables des réglages (survivent au changement de thème)
        self.v_name = tk.StringVar(self.root)
        self.v_hz = tk.StringVar(self.root)
        self.v_code = tk.StringVar(self.root)
        self.v_bits = tk.StringVar(self.root, value="4")
        self.v_decim = tk.StringVar(self.root, value="1")
        self.v_curve = tk.StringVar(self.root, value=str(wav2smp.CURVE_LOG))
        self.v_drive = tk.StringVar(self.root, value="1.0")
        self.v_trim = tk.BooleanVar(self.root, value=False)
        self.v_clean = tk.BooleanVar(self.root, value=False)
        self.v_dither = tk.StringVar(self.root, value="none")
        self.v_slices = tk.StringVar(self.root, value="1")
        for v in (self.v_name, self.v_code, self.v_bits, self.v_decim,
                  self.v_curve, self.v_drive, self.v_trim, self.v_clean,
                  self.v_dither):
            v.trace_add("write", lambda *a: self._schedule_apply())

        self._setup_fonts()
        self._apply_theme()
        self._build_ui()

        if not self.embedded:
            root.bind_all("<Control-o>", lambda e: self.open_smp())
            root.bind_all("<Control-O>", lambda e: self.open_smp())
            root.bind_all("<Control-w>", lambda e: self.add_wavs())
            root.bind_all("<Control-W>", lambda e: self.add_wavs())
            root.bind_all("<Control-s>", lambda e: self.save_smp())
            root.bind_all("<Control-S>", lambda e: self.save_smp())
            root.bind_all("<F3>", lambda e: self.toggle_monitor())
            root.bind_all("<F1>", lambda e: self.show_help())
            root.protocol("WM_DELETE_WINDOW", self.quit)
            if _register_drag_drop(root, self._on_drop):
                self._set_status(self._status_text + L("smp_st_dnd"))

    def _scale(self):
        """Échelle des polices : DPI de l'écran, ou celle de CPC DISK (DPI x
        zoom) en mode intégré."""
        if self.host is not None:
            return max(0.5, getattr(self.host, "scale", 1.0) * getattr(self.host, "zoom", 1.0))
        return max(1.0, self.root.winfo_fpixels("1i") / 96)   # 1,25 à 125 %

    def _setup_window(self):
        """Mode autonome seulement : titre, taille, position, zone de travail."""
        root = self.root
        root.title(L("smp_win_title"))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(round(1280 * self.scale), sw - 40), min(round(800 * self.scale), sh - 80)
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        root.minsize(min(1100, sw - 40), min(680, sh - 80))
        if sys.platform == "win32":
            # Zone de travail = écran moins la barre des tâches.  Si la taille
            # par défaut (et la barre de titre) n'y tient pas, on agrandit la
            # fenêtre à toute cette zone : sinon le bas (Sauver, Ajouter à la
            # disquette) passerait sous la barre des tâches.
            try:
                import ctypes
                import ctypes.wintypes
                r = ctypes.wintypes.RECT()
                ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
                work_h = r.bottom - r.top
                if round(800 * self.scale) + round(40 * self.scale) > work_h:
                    root.state("zoomed")
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    # Polices et thème
    # ------------------------------------------------------------------ #
    def _setup_fonts(self):
        """Polices pixel si elles sont présentes, sinon chasse fixe. Les
        objets sont créés une fois ; _apply_font_sizes règle leurs tailles."""
        families = set(tkfont.families(self.root))
        mono = next((f for f in ("Consolas", "Lucida Console", "Menlo",
                                 "DejaVu Sans Mono", "Courier New", "Courier")
                     if f in families), "TkFixedFont")
        self.has_title_font = PIXEL_TITLE in families
        self._has_body = PIXEL_BODY in families
        if self.has_title_font:
            self.f_title = tkfont.Font(self.root, family=PIXEL_TITLE)
            self.f_head = tkfont.Font(self.root, family=PIXEL_TITLE)
            self.f_btn = tkfont.Font(self.root, family=PIXEL_TITLE)
        else:
            self.f_title = tkfont.Font(self.root, family=mono, weight="bold")
            self.f_head = tkfont.Font(self.root, family=mono, weight="bold")
            self.f_btn = tkfont.Font(self.root, family=mono, weight="bold")
        body = PIXEL_BODY if self._has_body else mono
        self.f_body = tkfont.Font(self.root, family=body)
        self.f_small = tkfont.Font(self.root, family=body)
        self._apply_font_sizes()

    def _apply_font_sizes(self):
        """Tailles selon self.scale (mêmes tailles qu'avant l'intégration)."""
        s = self.scale

        def px8(base):
            """Press Start 2P : toujours un multiple de 8 px (net)."""
            return -8 * max(1, round(base * s / 8))

        if self.has_title_font:
            self.f_title.configure(size=px8(16))
            self.f_head.configure(size=px8(8))
            self.f_btn.configure(size=px8(8))
        else:
            self.f_title.configure(size=-round(20 * s))
            self.f_head.configure(size=-round(12 * s))
            self.f_btn.configure(size=-round(12 * s))
        self.f_body.configure(size=-round((20 if self._has_body else 14) * s))
        self.f_small.configure(size=-round((17 if self._has_body else 12) * s))

    def caps(self, text):
        """Capitales ; sans accents avec Press Start 2P (comme sur le CPC)."""
        text = text.upper()
        if self.has_title_font:
            text = "".join(c for c in unicodedata.normalize("NFD", text)
                           if unicodedata.category(c) != "Mn")
        return text

    def _apply_theme(self):
        """Couleurs et styles ttk (liste, menu déroulant). En mode intégré, le
        thème suit celui de CPC DISK et la fenêtre n'est pas touchée. Styles
        à part (Smp.*) pour ne pas modifier ceux de l'application."""
        if self.host is not None:
            self._theme_name = getattr(self.host, "_theme_name", self._theme_name)
        self.t = t = SimpleNamespace(**THEMES[self._theme_name])
        st = ttk.Style(self.root)
        if not self.embedded:
            self.root.configure(bg=t.frame)
            st.theme_use("clam")
        st.configure("Smp.Treeview", background=t.panel, fieldbackground=t.panel,
                     foreground=t.ink, font=self.f_body, borderwidth=0,
                     rowheight=self.f_body.metrics("linespace") + 4, relief="flat")
        st.map("Smp.Treeview", background=[("selected", t.ink)],
               foreground=[("selected", t.paper)])
        st.configure("Smp.Treeview.Heading", background=t.panel, foreground=t.acc,
                     font=self.f_small, relief="flat", borderwidth=0, padding=(4, 2))
        st.map("Smp.Treeview.Heading", background=[("active", t.dim)])
        st.layout("Smp.Treeview", [("Smp.Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Smp.TCombobox", fieldbackground=t.paper, background=t.acc,
                     foreground=t.ink, arrowcolor=t.paper, bordercolor=t.acc,
                     lightcolor=t.paper, darkcolor=t.paper, insertcolor=t.ink,
                     selectbackground=t.ink, selectforeground=t.paper)
        st.map("Smp.TCombobox", fieldbackground=[("readonly", t.paper)],
               foreground=[("disabled", t.dim)])
        self.root.option_add("*TCombobox*Listbox.background", t.paper)
        self.root.option_add("*TCombobox*Listbox.foreground", t.ink)
        self.root.option_add("*TCombobox*Listbox.selectBackground", t.ink)
        self.root.option_add("*TCombobox*Listbox.selectForeground", t.paper)
        self.root.option_add("*TCombobox*Listbox.font", self.f_body)

    def toggle_monitor(self):
        """F3 : bascule couleur (CTM644) <-> moniteur vert (GT65). En onglet,
        c'est CPC DISK qui bascule (et reconstruit l'onglet)."""
        if self.host is not None:
            self.host.toggle_monitor()
            return
        self._theme_name = "vert" if self._theme_name == "couleur" else "couleur"
        self.rebuild()

    def rebuild(self):
        """Reconstruit l'interface (thème, langue ou échelle changés)."""
        self._flush_pending()
        try:
            self.shell.destroy()
        except (tk.TclError, AttributeError):
            pass
        self._apply_theme()
        self._build_ui()

    def attach(self, parent):
        """Mode intégré : reconstruit l'éditeur dans un nouveau cadre (CPC DISK
        a reconstruit son interface). La banque et les réglages sont gardés."""
        self._flush_pending()
        self.parent = parent
        self._status_text = (self._status_text if self._status_err
                             else L("smp_st_ready_tab"))
        self.scale = self._scale()              # le zoom a pu changer entre-temps
        self._apply_font_sizes()
        self._apply_theme()
        self._build_ui()

    def rescale(self):
        """Mode intégré : suit le zoom de CPC DISK (polices + reconstruction)."""
        self.scale = self._scale()
        self._apply_font_sizes()
        self.rebuild()

    def _flush_pending(self):
        """Applique au modèle un réglage encore en attente, sans toucher aux
        widgets (ils vont être détruits)."""
        if not self._apply_id:
            return
        try:
            self.root.after_cancel(self._apply_id)
        except tk.TclError:
            pass
        self._apply_id = None
        i = self._sel_index
        if i is None or i >= len(self.model):
            return
        try:
            self.model.update(i, **self._read_fields(self.model.items[i]))
        except (BankError, ValueError, tk.TclError):
            pass

    # ------------------------------------------------------------------ #
    # Petits constructeurs de widgets
    # ------------------------------------------------------------------ #
    def _label(self, master, text="", fg=None, font=None, **kw):
        """Étiquette sur le fond de son parent."""
        return tk.Label(master, text=text, fg=fg or self.t.ink,
                        bg=master.cget("bg"), font=font or self.f_body, **kw)

    def _entry(self, master, var, width=8):
        """Zone de saisie aux couleurs du thème."""
        t = self.t
        return tk.Entry(master, textvariable=var, width=width, font=self.f_body,
                        bg=t.paper, fg=t.ink, insertbackground=t.ink,
                        insertwidth=8, relief="flat", bd=2, highlightthickness=2,
                        highlightbackground=t.acc, highlightcolor=t.hi,
                        selectbackground=t.ink, selectforeground=t.paper,
                        disabledbackground=t.panel, disabledforeground=t.dim)

    def _spin(self, master, var, width=5, **kw):
        """Compteur (Spinbox) aux couleurs du thème."""
        t = self.t
        return tk.Spinbox(master, textvariable=var, width=width, font=self.f_body,
                          bg=t.paper, fg=t.ink, insertbackground=t.ink,
                          buttonbackground=t.acc, relief="flat", bd=2,
                          highlightthickness=2, highlightbackground=t.acc,
                          highlightcolor=t.hi, selectbackground=t.ink,
                          selectforeground=t.paper, disabledbackground=t.panel,
                          disabledforeground=t.dim, **kw)

    def _check(self, master, text, var):
        """Case à cocher aux couleurs du thème."""
        t = self.t
        return tk.Checkbutton(master, text=text, variable=var, font=self.f_body,
                              bg=t.panel, fg=t.acc, selectcolor=t.paper,
                              activebackground=t.panel, activeforeground=t.hi,
                              disabledforeground=t.dim, highlightthickness=0,
                              bd=0, cursor="hand2")

    # ------------------------------------------------------------------ #
    # Construction de l'interface
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        """Construit tout l'éditeur (rappelée à chaque changement de thème)."""
        t = self.t
        if self.embedded:
            # Dans l'onglet : pas de cadre de « moniteur » (CPC DISK l'a déjà).
            self.shell = tk.Frame(self.parent, bg=t.paper)
            self.shell.pack(fill="both", expand=True)
            screen = self.shell
        else:
            self.shell = tk.Frame(self.parent, bg=t.frame, padx=10, pady=10)
            self.shell.pack(fill="both", expand=True)
            screen = tk.Frame(self.shell, bg=t.paper, padx=12, pady=8)
            screen.pack(fill="both", expand=True)
        shell = self.shell                      # réglage en attente gardé si détruit
        shell.bind("<Destroy>", lambda e: self._flush_pending()
                   if e.widget is shell else None, add="+")

        # --- en-tête ---
        head = tk.Frame(screen, bg=t.paper)
        head.pack(fill="x")
        if self.embedded:
            self._label(head, "SEQ-16 SAMPLER", font=self.f_head).pack(
                side="left", anchor="s")
            self._label(head, L("smp_hdr_sub"), fg=t.acc).pack(side="left", anchor="s")
            PixelButton(head, self, L("smp_btn_help"),
                        command=self.show_help).pack(side="right")
            tk.Frame(screen, bg=t.paper, height=6).pack(fill="x")
        else:
            self._label(head, "SEQ-16 SAMPLER", font=self.f_title).pack(side="left")
            self._label(head, L("smp_hdr_sub"), fg=t.acc).pack(side="left", anchor="s")
            PixelButton(head, self, L("smp_btn_monitor", v=L(
                "mon_couleur" if self._theme_name == "vert" else "mon_vert")),
                command=self.toggle_monitor).pack(side="right")
            stripes = tk.Frame(head, bg=t.paper)
            stripes.pack(side="right", padx=(0, 14))
            for c in (t.r, t.g, t.b):
                tk.Frame(stripes, bg=c, width=130, height=6).pack(pady=1)
            tk.Frame(screen, bg=t.ink, height=4).pack(fill="x", pady=(6, 8))

        # --- pied : sorties et ligne d'état (avant le contenu pour rester visible) ---
        foot = tk.Frame(screen, bg=t.paper)
        foot.pack(side="bottom", fill="x", pady=(8, 0))
        self.b_save = PixelButton(foot, self, L("smp_btn_save"), kind="primary",
                                  icon="save", command=self.save_smp)
        self.b_save.pack(side="left")
        self.b_dsk = PixelButton(foot, self, L("smp_btn_dsk"), icon="disk",
                                 command=self.add_to_dsk)
        self.b_dsk.pack(side="left", padx=(8, 0))
        self.status = self._label(foot, "", fg=t.hi, anchor="w", justify="left",
                                  width=1, font=self.f_small)
        self.status.pack(side="left", fill="x", expand=True, padx=(14, 0))
        self.status.bind("<Configure>", lambda e: self.status.config(
            wraplength=max(100, e.width - 4)))

        # --- contenu : banque à gauche, réglages et forme d'onde à droite ---
        content = tk.Frame(screen, bg=t.paper)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=5, minsize=round(480 * min(1.0, self.scale)))
        content.columnconfigure(1, weight=6, minsize=round(600 * min(1.0, self.scale)))
        content.rowconfigure(0, weight=1)
        left = tk.Frame(content, bg=t.paper)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = tk.Frame(content, bg=t.paper)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_bank_panel(left)
        self._build_settings_panel(right)
        self._build_wave_panel(right)

        self._set_status(self._status_text, self._status_err)
        self.refresh(keep=self._sel_index)

    def _build_bank_panel(self, parent):
        """Panneau de gauche : liste des samples, boutons, jauge de mémoire."""
        t = self.t
        p = Panel(parent, self, L("smp_panel_bank"))
        p.pack(fill="both", expand=True)
        body = p.body
        # Boutons sous la liste (empaquetés d'abord pour rester visibles)
        gauge = tk.Frame(body, bg=t.panel, padx=8, pady=6)
        gauge.pack(side="bottom", fill="x")
        self.gauge = tk.Canvas(gauge, height=22, bg=t.paper, highlightthickness=2,
                               highlightbackground=t.acc, bd=0)
        self.gauge.pack(fill="x")
        self.gauge.bind("<Configure>", lambda e: self._draw_gauge())
        self.gauge_lbl = self._label(gauge, "", fg=t.acc, anchor="w",
                                     font=self.f_small)
        self.gauge_lbl.pack(fill="x", pady=(4, 0))

        bar2 = tk.Frame(body, bg=t.panel, padx=8)
        bar2.pack(side="bottom", fill="x", pady=(4, 0))
        self.b_remove = PixelButton(bar2, self, L("smp_btn_remove"), icon="trash",
                                    kind="danger", command=self.remove)
        self.b_remove.pack(side="left")
        self.b_up = PixelButton(bar2, self, "", icon="up", padx=8,
                                command=lambda: self.move(-1))
        self.b_up.pack(side="left", padx=(8, 0))
        self.b_down = PixelButton(bar2, self, "", icon="down", padx=8,
                                  command=lambda: self.move(1))
        self.b_down.pack(side="left", padx=(8, 0))
        bar1 = tk.Frame(body, bg=t.panel, padx=8)
        bar1.pack(side="bottom", fill="x", pady=(6, 0))
        PixelButton(bar1, self, L("smp_btn_addwav"), icon="new",
                    command=self.add_wavs).pack(side="left")
        PixelButton(bar1, self, L("smp_btn_open"), icon="open",
                    command=self.open_smp).pack(side="left", padx=(8, 0))

        # La liste
        # Largeurs mesurées sur le contenu le plus large de chaque colonne
        # (et son titre) : elles suivent la police, donc le zoom et le DPI.
        widest = {"n": "16", "nom": "MMMMMM", "duree": "10,00", "hz": "12 500",
                  "nop": "999", "oct": "16 320", "src": "(banque .SMP)"}

        def width(key, title):
            return max(self.f_body.measure(widest[key]),
                       self.f_small.measure(title)) + round(14 * self.scale)
        cols = [(key, L(lbl), anchor) for key, lbl, anchor in (
            ("n", "smp_col_n", "e"), ("nom", "smp_col_name", "w"),
            ("duree", "smp_col_dur", "e"), ("hz", "smp_col_hz", "e"),
            ("nop", "smp_col_nop", "e"), ("oct", "smp_col_bytes", "e"),
            ("src", "smp_col_src", "w"))]
        cols = [(key, title, width(key, title), anchor) for key, title, anchor in cols]
        frame = tk.Frame(body, bg=t.panel, padx=6, pady=6)
        frame.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(frame, style="Smp.Treeview", show="headings",
                                 selectmode="browse", columns=[c[0] for c in cols])
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "src"), minwidth=30)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self.remove())

    def _build_settings_panel(self, parent):
        """Panneau des réglages du sample choisi."""
        t = self.t
        p = Panel(parent, self, L("smp_panel_settings"))
        p.pack(side="top", fill="x")
        g = tk.Frame(p.body, bg=t.panel, padx=10, pady=6)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        self._widgets_src = []                  # widgets réservés aux samples avec WAV
        self._widgets_all = []                  # widgets actifs dès qu'un sample est choisi

        def lab(text, row):
            """Étiquette de la colonne de gauche."""
            self._label(g, text, fg=t.acc, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=2)

        def line(row):
            """Ligne (cadre) de la colonne de droite."""
            f = tk.Frame(g, bg=t.panel)
            f.grid(row=row, column=1, sticky="w", pady=2)
            return f

        # Nom
        lab(L("smp_lbl_name"), 0)
        f = line(0)
        e = self._entry(f, self.v_name, width=8)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self._sync_fields())
        e.bind("<FocusOut>", lambda ev: self._sync_fields())
        self._widgets_all.append(e)
        self.src_lbl = self._label(f, "", fg=t.hi, font=self.f_small, anchor="w")
        self.src_lbl.pack(side="left", padx=(12, 0))

        # Fréquence : Hz (préréglages ou saisie) et période en NOP
        lab(L("smp_lbl_rate"), 1)
        f = line(1)
        cb = ttk.Combobox(f, textvariable=self.v_hz, width=7, style="Smp.TCombobox",
                          values=[str(r) for r in RATE_PRESETS], font=self.f_body)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda ev: self._hz_entered())
        cb.bind("<Return>", lambda ev: self._hz_entered())
        cb.bind("<FocusOut>", lambda ev: self._hz_entered())
        self._widgets_all.append(cb)
        self._label(f, L("smp_lbl_period"), fg=t.acc).pack(side="left", padx=(6, 6))
        sp = self._spin(f, self.v_code, width=4, from_=wav2smp.CODE_MIN,
                        to=wav2smp.CODE_MAX, increment=1)
        sp.pack(side="left")
        self._widgets_all.append(sp)
        self._label(f, L("smp_lbl_nop"), fg=t.acc).pack(side="left", padx=(6, 0))
        self.rate_lbl = self._label(f, "", fg=t.hi, font=self.f_small)
        self.rate_lbl.pack(side="left", padx=(10, 0))

        # Bits, décimation, courbe
        lab(L("smp_lbl_bits"), 2)
        self.seg_bits = Segmented(line(2), self, self.v_bits,
                                  [(str(b), str(b)) for b in (4, 3, 2, 1)])
        self.seg_bits.pack(side="left")
        lab(L("smp_lbl_decim"), 3)
        self.seg_decim = Segmented(line(3), self, self.v_decim,
                                   [(str(d), str(d)) for d in wav2smp.DECIMS])
        self.seg_decim.pack(side="left")
        lab(L("smp_lbl_curve"), 4)
        self.seg_curve = Segmented(line(4), self, self.v_curve,
                                   [(str(i), L("smp_curve_%d" % i))
                                    for i in range(len(CURVE_LABELS))])
        self.seg_curve.pack(side="left")

        # Réglages de conversion (il faut le WAV d'origine)
        lab(L("smp_lbl_conv"), 5)
        f = line(5)
        self._label(f, L("smp_lbl_drive"), fg=t.acc).pack(side="left", padx=(0, 4))
        sp = self._spin(f, self.v_drive, width=4, from_=0.5, to=8.0, increment=0.5,
                        format="%.1f")
        sp.pack(side="left")
        self._widgets_src.append(sp)
        for text, var in ((L("smp_lbl_trim"), self.v_trim),
                          (L("smp_lbl_clean"), self.v_clean)):
            c = self._check(f, text, var)
            c.pack(side="left", padx=(12, 0))
            self._widgets_src.append(c)
        self._label(f, L("smp_lbl_dither"), fg=t.acc).pack(side="left", padx=(12, 4))
        self.seg_dither = Segmented(f, self, self.v_dither,
                                    [("none", L("smp_dither_none")),
                                     ("noise", L("smp_dither_noise"))])
        self.seg_dither.pack(side="left")

        lab(L("smp_lbl_slices"), 6)
        f = line(6)
        sp = self._spin(f, self.v_slices, width=3, from_=1, to=16, increment=1)
        sp.pack(side="left")
        self._widgets_src.append(sp)
        self.b_slice = PixelButton(f, self, L("smp_btn_slice"), icon="cut", padx=8,
                                   command=self.apply_slices)
        self.b_slice.pack(side="left", padx=(8, 0))
        self._label(f, L("smp_slice_hint"),
                    fg=t.acc, font=self.f_small).pack(side="left", padx=(8, 0))

        # Message d'aide sur le type de sample
        self.note = self._label(g, "", fg=t.warm, font=self.f_small, anchor="w",
                                justify="left")
        self.note.grid(row=7, column=0, columnspan=2, sticky="we", pady=(4, 0))
        self.note.bind("<Configure>", lambda e: self.note.config(
            wraplength=max(100, e.width - 4)))

    def _build_wave_panel(self, parent):
        """Panneau de la forme d'onde et des boutons d'écoute."""
        t = self.t
        p = Panel(parent, self, L("smp_panel_wave"))
        p.pack(side="top", fill="both", expand=True, pady=(8, 0))
        bar = tk.Frame(p.body, bg=t.panel, padx=8, pady=6)
        bar.pack(side="bottom", fill="x")
        self.b_play_src = PixelButton(bar, self, L("smp_btn_play_src"), icon="play",
                                      command=lambda: self.play(False))
        self.b_play_src.pack(side="left")
        self.b_play_cpc = PixelButton(bar, self, L("smp_btn_play_cpc"), icon="play",
                                      kind="primary", command=lambda: self.play(True))
        self.b_play_cpc.pack(side="left", padx=(8, 0))
        PixelButton(bar, self, L("smp_btn_stop"), icon="stop",
                    command=self.player.stop).pack(side="left", padx=(8, 0))
        self.wave = tk.Canvas(p.body, bg=t.paper, highlightthickness=0, bd=0,
                              height=120)
        self.wave.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))
        self.wave.bind("<Configure>", lambda e: self._draw_wave())

    # ------------------------------------------------------------------ #
    # Rafraîchissement
    # ------------------------------------------------------------------ #
    def _set_status(self, text, error=False):
        """Ligne d'état en bas (rouge/inverse si erreur)."""
        self._status_text, self._status_err = text, error
        try:
            self.status.config(text=text, fg=self.t.danger if error else self.t.hi)
        except (tk.TclError, AttributeError):
            pass

    def refresh(self, keep=None):
        """Recharge la liste, la jauge, les champs et la forme d'onde.
        keep : indice du sample à garder choisi."""
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.model.items):
            if it.has_source:
                src = os.path.basename(it.path)
                if it.part[1] > 1:
                    src += " [%d/%d]" % (it.part[0] + 1, it.part[1])
            else:
                src = L("smp_src_bank")
            self.tree.insert("", "end", iid=str(i), values=(
                i, it.name, _sec(it.seconds), _num(round(it.rate)), it.code,
                _num(len(it.data)), src))
        n = len(self.model.items)
        if keep is not None and n:
            keep = max(0, min(n - 1, keep))
            self.tree.selection_set(str(keep))
            self.tree.see(str(keep))
        self._sel_index = keep if n else None
        self._fill_fields()
        self._draw_gauge()
        self._draw_wave()

    def _update_row(self, i):
        """Met à jour une seule ligne de la liste (après un réglage)."""
        it = self.model.items[i]
        vals = list(self.tree.item(str(i), "values"))
        vals[1:6] = [it.name, _sec(it.seconds), _num(round(it.rate)), it.code,
                     _num(len(it.data))]
        self.tree.item(str(i), values=vals)

    def _draw_gauge(self):
        """Jauge de mémoire : octets utilisés sur 16 064 (rouge au-delà)."""
        try:
            c = self.gauge
            c.delete("all")
        except (tk.TclError, AttributeError):
            return
        t = self.t
        used = self.model.used_bytes()
        limit = wav2smp.BANK_MAX_MAIN
        over = used > limit
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        frac = min(1.0, used / limit)
        c.create_rectangle(0, 0, w * frac, h, fill=t.danger if over else t.ink,
                           outline="")
        for k in range(1, 4):                   # repères tous les 4 Ko
            x = w * k * 4096 / limit
            c.create_line(x, 0, x, h, fill=t.dim)
        pct = 100 * used / limit
        txt = L("smp_gauge", u=_num(used), m=_num(limit), p=round(pct),
                n=len(self.model), s=_sec(self.model.total_seconds()))
        if over:
            txt += L("smp_gauge_over", d=_num(used - limit))
        self.gauge_lbl.config(text=txt, fg=t.danger if over else t.acc)
        ok = 0 < used <= limit
        self.b_save.set_enabled(ok)
        self.b_dsk.set_enabled(ok)

    def _draw_wave(self):
        """Dessine l'origine (en haut) et le rendu CPC (en bas), même échelle
        de temps."""
        try:
            c = self.wave
            c.delete("all")
        except (tk.TclError, AttributeError):
            return
        t = self.t
        w, h = max(10, c.winfo_width()), max(10, c.winfo_height())
        i = self._sel_index
        if i is None:
            c.create_text(w / 2, h / 2, text=L("smp_wave_pick"),
                          fill=t.acc, font=self.f_body)
            return
        try:
            orig = self.model.original(i)
            cpc = self.model.rendered(i)
        except BankError as e:
            c.create_text(w / 2, h / 2, text=e.localized(), fill=t.danger,
                          font=self.f_body)
            return
        dur = max(len(cpc[0]) / cpc[1], len(orig[0]) / orig[1] if orig else 0, 1e-6)
        lane = h / 2
        for k, (sig, col, title) in enumerate((
                (orig, t.acc, L("smp_wave_orig")), (cpc, t.ink, L("smp_wave_cpc")))):
            top = k * lane
            mid = top + lane / 2
            c.create_line(0, mid, w, mid, fill=t.dim)
            c.create_text(6, top + 4, text=title, anchor="nw", fill=col,
                          font=self.f_small)
            if sig is None:
                c.create_text(w / 2, mid, text=L("smp_wave_nosrc"), fill=t.warm,
                              font=self.f_small)
                continue
            self._draw_signal(c, sig[0], sig[1], dur, w, mid, lane * 0.42, col)
        c.create_line(0, lane, w, lane, fill=t.acc)
        c.create_text(w - 6, h - 4, text=_sec(dur), anchor="se", fill=t.acc,
                      font=self.f_small)

    @staticmethod
    def _draw_signal(c, x, rate, dur, w, mid, amp, col):
        """Enveloppe min/max par colonne de pixels d'un signal."""
        if not x:
            return
        peak = max(1e-9, max(abs(v) for v in x))
        width = max(1, int(w * (len(x) / rate) / dur))   # pixels occupés
        step = len(x) / width
        for px in range(width):
            a, b = int(px * step), max(int(px * step) + 1, int((px + 1) * step))
            seg = x[max(0, a - 1):b]            # + point d'avant : marches reliées
            lo, hi = min(seg), max(seg)
            c.create_line(px, mid - hi / peak * amp, px, mid - lo / peak * amp + 1,
                          fill=col)

    def _fill_fields(self):
        """Remplit les champs avec les réglages du sample choisi."""
        i = self._sel_index
        has = i is not None
        it = self.model.items[i] if has else None
        self._loading = True
        try:
            if has:
                s = it.settings()
                self.v_name.set(s["name"])
                self.v_code.set(str(s["code"]))
                self.v_hz.set(str(round(it.rate)))
                self.v_bits.set(str(s["bits"]))
                self.v_decim.set(str(s["decim"]))
                self.v_curve.set(str(s["curve"]))
                self.v_drive.set("%.1f" % s["drive"] if s["drive"] * 10 == int(s["drive"] * 10)
                                 else str(s["drive"]))
                self.v_trim.set(s["trim"])
                self.v_clean.set(s["clean"])
                self.v_dither.set(s["dither"])
                self.v_slices.set(str(s["slices"]))
        finally:
            self._loading = False
        src = has and it.has_source
        for wdg in self._widgets_all:
            wdg.configure(state="normal" if has else "disabled")
        for wdg in self._widgets_src:
            wdg.configure(state="normal" if src else "disabled")
        for seg in (self.seg_bits, self.seg_decim, self.seg_curve):
            seg.set_enabled(has)
        self.seg_dither.set_enabled(src)
        self.b_slice.set_enabled(src)
        self.b_play_src.set_enabled(src)
        self.b_play_cpc.set_enabled(has)
        for b in (self.b_remove, self.b_up, self.b_down):
            b.set_enabled(has)
        if not has:
            self.src_lbl.config(text="")
            self.rate_lbl.config(text="")
            self.note.config(text=L("smp_note_none"))
        elif src:
            self.src_lbl.config(text=os.path.basename(it.path))
            self.note.config(text=L("smp_note_src"))
        else:
            self.src_lbl.config(text=L("smp_src_reread"))
            self.note.config(text=L("smp_note_nosrc"))
        self._show_rate()

    def _show_rate(self):
        """Affiche la fréquence réelle et la durée du sample choisi."""
        i = self._sel_index
        if i is None:
            return
        it = self.model.items[i]
        self.rate_lbl.config(text=L("smp_rate_info", hz="%.0f" % it.rate,
                                    s=_sec(it.seconds), b=_num(len(it.data))))

    def _sync_fields(self):
        """Réécrit les champs avec les valeurs retenues (nom nettoyé, etc.)."""
        self._apply_now()
        self._fill_fields()

    # ------------------------------------------------------------------ #
    # Réglages
    # ------------------------------------------------------------------ #
    def _on_select(self, _e=None):
        """Un sample est choisi dans la liste."""
        if self._apply_id:                      # appliquer d'abord ce qui attend
            self._apply_now()
        sel = self.tree.selection()
        new = int(sel[0]) if sel else None
        if new == self._sel_index:
            return
        self._sel_index = new
        self._fill_fields()
        self._draw_wave()

    def _schedule_apply(self):
        """Un champ a changé : application différée (anti-rebond 250 ms)."""
        if self._loading or self._sel_index is None:
            return
        if self._apply_id:
            self.root.after_cancel(self._apply_id)
        self._apply_id = self.root.after(250, self._apply_now)

    def _hz_entered(self):
        """Fréquence saisie ou choisie en Hz : convertie en période (NOP)."""
        if self._loading or self._sel_index is None:
            return
        txt = self.v_hz.get().strip().replace(" ", "").replace(",", ".")
        try:
            hz = float(txt)
        except ValueError:
            self._set_status(L("smp_st_bad_hz", v=txt), True)
            return
        if not 4000 <= hz <= 16200:
            self._set_status(L("smp_e_rate"), True)
            return
        code = str(wav2smp.rate_to_code(hz))
        if code != self.v_code.get():
            self.v_code.set(code)               # déclenche l'application
        self._loading = True
        self.v_hz.set(str(round(wav2smp.code_to_rate(int(code)))))
        self._loading = False

    def _read_fields(self, it):
        """Lit les champs -> dictionnaire de réglages pour BankModel.update."""
        d = dict(name=self.v_name.get(), code=int(self.v_code.get()),
                 bits=int(self.v_bits.get()), decim=int(self.v_decim.get()),
                 curve=int(self.v_curve.get()))
        if it.has_source:
            d.update(drive=float(self.v_drive.get().replace(",", ".")),
                     trim=self.v_trim.get(), clean=self.v_clean.get(),
                     dither=self.v_dither.get())
        return d

    def _apply_now(self):
        """Applique les champs au sample choisi (reconversion si besoin)."""
        if self._apply_id:
            self.root.after_cancel(self._apply_id)
        self._apply_id = None
        i = self._sel_index
        if i is None or self._loading or i >= len(self.model):
            return
        it = self.model.items[i]
        try:
            d = self._read_fields(it)
        except (ValueError, tk.TclError):
            self._set_status(L("smp_st_bad_field"), True)
            return
        old = it.settings()
        try:
            self._busy(True)
            self.model.update(i, **d)
        except BankError as e:
            self._set_status(e.localized(), True)
            return
        finally:
            self._busy(False)
        if it.settings() != old:
            self._set_status(L("smp_st_applied", n=it.name, b=_num(len(it.data)),
                               s=_sec(it.seconds), hz="%.0f" % it.rate))
        self._update_row(i)
        self._loading = True
        self.v_hz.set(str(round(it.rate)))
        self._loading = False
        self._show_rate()
        self._draw_gauge()
        self._draw_wave()

    def _busy(self, on):
        """Curseur sablier pendant une conversion."""
        try:
            self.root.config(cursor="watch" if on else "")
            if on:
                self.root.update_idletasks()
        except tk.TclError:
            pass

    def apply_slices(self):
        """Découpe le WAV du sample choisi en N tranches."""
        i = self._sel_index
        if i is None:
            return
        try:
            n = int(self.v_slices.get())
        except ValueError:
            self._set_status(L("smp_st_bad_slices"), True)
            return
        self._apply_now()
        try:
            self._busy(True)
            first = self.model.set_slices(i, n)
        except BankError as e:
            self.error(L("smp_err_slice"), e.localized())
            return
        finally:
            self._busy(False)
        self._set_status(L("smp_st_sliced", n=n))
        self.refresh(keep=first)

    # ------------------------------------------------------------------ #
    # Liste
    # ------------------------------------------------------------------ #
    def add_wavs(self, paths=None):
        """Ajoute un ou plusieurs WAV (boîte de dialogue si paths est vide)."""
        if not paths:
            paths = filedialog.askopenfilenames(
                parent=self.root, title=L("smp_dlg_addwav"),
                initialdir=_initdir("samples"),
                filetypes=[(L("smp_ft_wav"), "*.wav *.WAV"), (L("smp_ft_all"), "*.*")])
        if not paths:
            return
        self._apply_now()
        added, errors = [], []
        self._busy(True)
        try:
            for p in paths:
                try:
                    added.append(self.model.add_wav(p))
                except BankError as e:
                    errors.append(e.localized())
                    if len(self.model) >= wav2smp.MAX_SAMPLES:
                        break
        finally:
            self._busy(False)
        if added:
            self.refresh(keep=added[-1])
            self._set_status(L("smp_st_added", n=len(added)))
        if errors:
            self.error(L("smp_err_notadded"), "\n".join(errors))

    def remove(self):
        """Retire le sample choisi."""
        i = self._sel_index
        if i is None:
            return
        self._apply_now()
        name = self.model.items[i].name
        self.model.remove(i)
        self.refresh(keep=i)
        self._set_status(L("smp_st_removed", n=name))

    def move(self, delta):
        """Monte (-1) ou descend (+1) le sample choisi."""
        i = self._sel_index
        if i is None:
            return
        self._apply_now()
        self.refresh(keep=self.model.move(i, delta))

    def open_smp(self, path=None):
        """Ouvre une banque .SMP existante (remplace la banque en cours)."""
        if not path:
            path = filedialog.askopenfilename(
                parent=self.root, title=L("smp_dlg_open"),
                initialdir=_initdir("samples"),
                filetypes=[(L("smp_ft_smp"), "*.smp *.SMP"), (L("smp_ft_all"), "*.*")])
        if not path:
            return
        self._apply_now()
        if self.model.items and self.model.dirty and not self.ask(
                L("smp_ask_open_title"), L("smp_ask_open_msg")):
            return
        try:
            self.model.open_bank(path)
        except BankError as e:
            self.error(L("smp_err_open"), e.localized())
            return
        self.bank_path = path
        self.refresh(keep=0)
        self._set_status(L("smp_st_opened", f=os.path.basename(path),
                           n=len(self.model)))

    def _on_drop(self, paths):
        """Fichiers déposés : WAV ajoutés, premier .SMP ouvert."""
        wavs = [p for p in paths if p.lower().endswith(".wav")]
        smps = [p for p in paths if p.lower().endswith(".smp")]
        if smps:
            self.open_smp(smps[0])
        if wavs:
            self.add_wavs(wavs)
        if not wavs and not smps:
            self._set_status(L("smp_st_drop_bad"), True)

    # ------------------------------------------------------------------ #
    # Écoute
    # ------------------------------------------------------------------ #
    def play(self, cpc):
        """Écoute le rendu CPC (cpc vrai) ou le son d'origine."""
        i = self._sel_index
        if i is None:
            return
        self._apply_now()
        try:
            data = self.model.rendered_wav(i) if cpc else self.model.original_wav(i)
        except BankError as e:
            self._set_status(e.localized(), True)
            return
        if data is None:
            self._set_status(L("smp_st_nosrc_play"), True)
            return
        err = self.player.play(data)
        if err:
            self._set_status(err, True)
        else:
            self._set_status(L("smp_st_playing", n=self.model.items[i].name,
                               w=L("smp_play_cpc" if cpc else "smp_play_orig")))

    # ------------------------------------------------------------------ #
    # Sorties
    # ------------------------------------------------------------------ #
    def _check_ready(self):
        """Vrai si la banque peut être écrite ; sinon explique pourquoi."""
        self._apply_now()
        try:
            self.model.checked_bytes()
            return True
        except BankError as e:
            self.error(L("smp_err_refused"), e.localized())
            return False

    def save_smp(self):
        """Sauve la banque dans un .SMP (dossier samples/ par défaut).
        Renvoie True si le fichier est écrit."""
        if not self._check_ready():
            return False
        init = self.bank_path or os.path.join(_initdir("samples"), "MABANK.SMP")
        path = filedialog.asksaveasfilename(
            parent=self.root, title=L("smp_dlg_save"),
            initialdir=os.path.dirname(init), initialfile=os.path.basename(init),
            defaultextension=".SMP",
            filetypes=[(L("smp_ft_smp"), "*.SMP *.smp"), (L("smp_ft_all"), "*.*")])
        if not path:
            return False
        try:
            size = self.model.save(path)
        except BankError as e:
            self.error(L("smp_err_save"), e.localized())
            return False
        self.bank_path = path
        self._set_status(L("smp_st_saved", p=path, n=_num(size),
                           d=_num(self.model.used_bytes())))
        return True

    def _host_disk(self):
        """Disquette ouverte dans l'onglet Disquette de CPC DISK, si elle est
        au format DATA (celui qu'attend SEQ-16) ; sinon None."""
        disk = getattr(self.host, "disk", None) if self.host is not None else None
        if disk is None:
            return None
        from ..core.amsdos import DATA, detect_format
        try:
            return disk if detect_format(disk) is DATA else None
        except Exception:  # noqa: BLE001 - image abîmée : on propose un fichier
            return None

    def add_to_dsk(self):
        """Ajoute la banque à une disquette .dsk (build/seq16.dsk par défaut),
        sous un nom AMSDOS 8.3 tiré du nom du fichier .SMP. Dans CPC DISK,
        propose aussi la disquette ouverte dans l'onglet Disquette."""
        if not self._check_ready():
            return
        if not self.bank_path and not self.save_smp():
            self._set_status(L("smp_st_save_first"), True)
            return
        name = dsk_name(self.bank_path)
        disk = self._host_disk()
        if disk is not None:
            shown = os.path.basename(self.host.path) if self.host.path else L("lbl_new")
            dlg = PixelDialog(self, L("smp_target_title"),
                              L("smp_target_msg", n=name, d=shown), kind="ask",
                              buttons=((L("smp_target_cancel"), None, "normal"),
                                       (L("smp_target_file"), "file", "normal"),
                                       (L("smp_target_open"), "open", "primary")))
            if dlg.result is None:
                return
            if dlg.result == "open":
                self._add_to_host_disk(disk, name, shown)
                return
        dsk = filedialog.askopenfilename(
            parent=self.root, title=L("smp_dlg_dsk"),
            initialdir=os.path.dirname(self.dsk_path),
            initialfile=os.path.basename(self.dsk_path),
            filetypes=[(L("smp_ft_dsk"), "*.dsk *.DSK"), (L("smp_ft_all"), "*.*")])
        if not dsk:
            return
        try:
            exists = self.model.dsk_has(dsk, name)
        except BankError as e:
            self.error(L("smp_err_dsk"), e.localized())
            return
        if exists and not self.ask(L("smp_ask_replace_title"), L(
                "smp_ask_replace_msg", n=name, d=os.path.basename(dsk))):
            return
        try:
            self.model.add_to_dsk(dsk, name)
        except BankError as e:
            self.error(L("smp_err_add"), e.localized())
            return
        self.dsk_path = dsk
        self._set_status(L("smp_st_dsk_added", n=name, d=dsk))
        host = self.host
        if host is not None and getattr(host, "path", None) and \
                os.path.abspath(host.path) == os.path.abspath(dsk):
            # Même fichier que la disquette ouverte (format non DATA écarté
            # plus haut) : la recharger pour que son catalogue soit à jour.
            host._open_path(dsk)
            host._show_tab(2)

    def _add_to_host_disk(self, disk, name, shown):
        """Écrit la banque sur la disquette ouverte dans CPC DISK, puis la
        sauve et rafraîchit son catalogue (comme « Ajouter » de l'onglet
        Disquette)."""
        try:
            exists = self.model.dsk_has(disk, name)
        except BankError as e:
            self.error(L("smp_err_dsk"), e.localized())
            return
        if exists and not self.ask(L("smp_ask_replace_title"), L(
                "smp_ask_replace_msg", n=name, d=shown)):
            return
        try:
            self.model.add_to_dsk(disk, name)
        except BankError as e:
            self.error(L("smp_err_add"), e.localized())
            return
        host = self.host
        host._scan_disk()
        host._file_secs = set()
        host._refresh(rescan=False)
        host._persist()                         # sauve (ou propose un chemin)
        self._set_status(L("smp_st_dsk_added_open", n=name, d=shown))

    # ------------------------------------------------------------------ #
    # Boîtes et fin
    # ------------------------------------------------------------------ #
    def error(self, title, message):
        """Boîte d'erreur."""
        PixelDialog(self, title, message, kind="error")

    def ask(self, title, message):
        """Question oui / non ; renvoie True pour oui."""
        dlg = PixelDialog(self, title, message, kind="ask",
                          buttons=((L("dlg_no"), False, "normal"),
                                   (L("dlg_yes"), True, "primary")))
        return bool(dlg.result)

    def show_help(self):
        """F1 (ou bouton Aide dans l'onglet) : rappel des raccourcis."""
        PixelDialog(self, L("smp_help_title"),
                    L("smp_help", m=_num(wav2smp.BANK_MAX_MAIN)))

    def quit(self):
        """Fermeture (mode autonome) : propose de garder une banque non sauvée."""
        self._apply_now()
        if self.model.items and self.model.dirty and not self.ask(
                L("smp_quit_title"), L("smp_quit_msg")):
            return
        self.player.close()
        self.root.destroy()


def run(argv=None, lang=None):
    """Point d'entrée autonome : crée la fenêtre et lance la boucle Tk.
    argv : fichiers .wav / .smp à charger (défaut : sys.argv[1:]) ;
    lang : en / fr / es (défaut : langue du système, comme CPC DISK)."""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)    # Windows 8.1 et plus
        except Exception:  # noqa: BLE001
            try:
                ctypes.windll.user32.SetProcessDPIAware()     # Windows 7
            except Exception:  # noqa: BLE001
                pass
    set_language(lang or detect_language())
    _load_private_fonts()
    root = tk.Tk()
    app = SmpApp(root)
    for p in (sys.argv[1:] if argv is None else argv):    # fichiers passés en argument
        app._on_drop([p])
    root.mainloop()


if __name__ == "__main__":
    run()
