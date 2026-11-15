"""Interface graphique (tkinter) de cpc_dsk.

Deux onglets :

- **Disquette (.dsk)** : ouvrir / créer / sauvegarder une image, lister les
  fichiers (couches Filer et AMSDOS), ajouter un fichier local, extraire un
  fichier vers le disque local, supprimer un fichier, inspection
  hexadécimale d'un fichier ou d'un secteur.
- **Gotek (clé USB)** : préparer le répertoire à copier sur la clé USB du
  Gotek (patron de noms, sous-dossier, index de départ), le vérifier, et
  créer une image FAT16 complète (rédacteur intégré, aucune dépendance).

Lancement:
    python -m cpc_dsk.gui
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from cpc_dsk.cli import hexdump
from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.core.cpcfs import CpcError, CpcFile, CpcFilesystem, FT_BASIC, FT_BINARY
from cpc_dsk.core.gotek import (
    DEFAULT_NAME_PATTERN,
    GotekConfig,
    GotekError,
    create_fat_image,
    prepare_usb_directory,
    verify_usb_directory,
)


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} Mo"
    if n >= 1024:
        return f"{n / 1024:.1f} Ko"
    return f"{n} o"


def _suggest_83(path: str) -> str:
    """Nom 8.3 suggéré à partir d'un nom de fichier local.

    L'extension est **conservée**, en notation CPC (espace) :
    ``monprog.bas`` -> ``MONPROG BAS``, ``data.bin`` -> ``DATA BIN``.
    """
    base = os.path.basename(path)
    stem, dot, ext = base.partition(".")
    stem = stem.upper()[:8]
    if not dot:
        return stem
    return f"{stem} {ext.upper()[:3]}"[:11].strip()


# --- Glisser-déposer depuis l'explorateur Windows ------------------------- #
def _register_drag_drop(root: "tk.Tk", on_drop) -> bool:
    """Active le glisser-déposer de fichiers (explorateur Windows) sur la
    fenêtre racine, via l'API RegisterDragHook (aucune dépendance externe).

    ``on_drop(liste_de_chemin_absolu)`` est appelé dans la boucle tkinter.
    Retourne ``False`` si l'OS ne le supporte pas (Linux/macOS).

    NB: les ``argtypes`` sont **obligatoires** — sans eux ctypes tronque les
    pointeurs (callback, HDROP) sur 32 bits en Windows 64-bit et le hook ne
    reçoit jamais les dépôts.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        WM_DROPFILES = 0x0233
        RHF_ALL = 15  # ENTER | LEAVE | OVER | DROP

        # Signature exacte du DragHookProc (MSDN) :
        #   LRESULT DragHookProc(HWND, UINT msg, DWORD_PTR dwData, DWORD_PTR dwParam)
        # dwData/dwParam sont des pointeurs 64 bits sous x64 : c_size_t
        # tronquerait le HDROP sur 32 bits et DragQueryFileW échouerait.
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p)

        user32.RegisterDragHook.argtypes = [wintypes.HWND, WNDPROC,
                                            wintypes.DWORD]
        user32.RegisterDragHook.restype = wintypes.BOOL
        shell32.DragQueryFileW.argtypes = [wintypes.HDROP, wintypes.DWORD,
                                           wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinishW.argtypes = [wintypes.HDROP]

        # NB : root.frame() renvoie le cadre DÉCORATIF du gestionnaire de
        # fenêtres (vide sous Windows -> int() levait -> DnD muet). Le HWND
        # de la fenêtre Tk est winfo_id().
        hwnd = wintypes.HWND(root.winfo_id())

        def _wndproc(h, msg, wp, lp):
            if msg == WM_DROPFILES and wp:
                count = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                buf = ctypes.create_unicode_buffer(32768)
                paths = []
                for i in range(count):
                    if shell32.DragQueryFileW(wp, i, buf, 32768):
                        paths.append(buf.value)
                shell32.DragFinishW(wp)
                if paths:
                    root.after(0, lambda p=paths: on_drop(p))
            return 0

        # Le callback doit rester référencé (sinon collecté -> plantage).
        globals()["_drag_drop_callback"] = WNDPROC(_wndproc)
        if user32.RegisterDragHook(hwnd, globals()["_drag_drop_callback"],
                                   RHF_ALL):
            return True
    except Exception:  # noqa: BLE001 — le DnD est un confort, pas critique
        pass
    return False


class AddFileDialog:
    """Petite fenêtre modale : nom 8.3, type, adresse de chargement, couche."""

    def __init__(self, master, default_name: str):
        self.result: Optional[dict] = None
        self.win = tk.Toplevel(master)
        self.win.title("Ajouter un fichier sur la disquette")
        self.win.transient(master)
        self.win.resizable(False, False)

        frm = ttk.Frame(self.win, padding=12)
        frm.grid(sticky="nsew")

        self.name = tk.StringVar(value=default_name)
        self.ftype = tk.StringVar(value="binary")
        self.load = tk.StringVar(value="0x4000")
        # AMSDOS d'abord (émulateurs + longueurs exactes) ; « both » pour
        # un disque lisible aussi par le vrai DOS/Gotek.
        self.fs = tk.StringVar(value="amsdos")

        ttk.Label(frm, text="Nom sur la disquette (8.3):").grid(
            row=0, column=0, sticky="w", pady=2)
        ttk.Entry(frm, textvariable=self.name, width=16).grid(
            row=0, column=1, padx=6, pady=2)

        ttk.Label(frm, text="Type:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Combobox(frm, textvariable=self.ftype, width=14, state="readonly",
                     values=["basic", "binary"]).grid(
            row=1, column=1, padx=6, pady=2)

        ttk.Label(frm, text="Adresse de chargement:").grid(
            row=2, column=0, sticky="w", pady=2)
        ttk.Entry(frm, textvariable=self.load, width=16).grid(
            row=2, column=1, padx=6, pady=2)

        ttk.Label(frm, text="Couche(s) d'écriture:").grid(
            row=3, column=0, sticky="w", pady=2)
        ttk.Combobox(frm, textvariable=self.fs, width=14, state="readonly",
                     values=["amsdos", "both", "filer"]).grid(
            row=3, column=1, padx=6, pady=2)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Annuler",
                   command=self.win.destroy).pack(side="left", padx=4)
        self.win.protocol("WM_DELETE_WINDOW", self.win.destroy)
        self.win.grab_set()

    def _ok(self) -> None:
        try:
            load = int(self.load.get(), 0)
        except ValueError:
            messagebox.showerror(
                "Adresse invalide",
                "Adresse de chargement invalide (ex: 0x4000).",
                parent=self.win)
            return
        self.result = {
            "name": self.name.get(),
            "file_type": FT_BASIC if self.ftype.get() == "basic" else FT_BINARY,
            "load_addr": load,
            "mode": self.fs.get(),
        }
        self.win.destroy()


class DskEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Éditeur de disquettes CPC (.dsk) & Gotek")
        self.root.geometry("1000x640")

        self.disk: Optional[ADFDisk] = None
        self.path: Optional[str] = None
        self._files: List[CpcFile] = []
        self._gotek_sources: List[str] = []

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.tab_disk = ttk.Frame(self.notebook)
        self.tab_gotek = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_disk, text=" Disquette (.dsk) ")
        self.notebook.add(self.tab_gotek, text=" Gotek (clé USB) ")

        self._build_disk_tab()
        self._build_gotek_tab()

        self.status = ttk.Label(root, text="Prêt.", relief="sunken", anchor="w")
        self.status.pack(side="bottom", fill="x")

        # Glisser-déposer depuis l'explorateur Windows.
        if _register_drag_drop(root, self._on_drop):
            self._set_status(
                "Prêt. Astuce : glissez des fichiers (explorateur) sur la "
                "fenêtre — .dsk/.adf s'ouvrent (ou alimentent l'onglet Gotek), "
                "les autres s'ajoutent à la disquette ouverte.")
        elif sys.platform == "win32":
            self._set_status("Prêt. (glisser-déposer non actif)")

    # ================================================================== #
    # Onglet Disquette
    # ================================================================== #
    def _build_disk_tab(self) -> None:
        bar = ttk.Frame(self.tab_disk, padding=(6, 4))
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Ouvrir…", command=self.open_disk).pack(side="left", padx=2)
        ttk.Button(bar, text="Nouveau", command=self.new_disk).pack(side="left", padx=2)
        ttk.Button(bar, text="Sauver", command=self.save_disk).pack(side="left", padx=2)
        ttk.Button(bar, text="Enregistrer sous…",
                   command=self.save_disk_as).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="Secteur (piste sect):").pack(side="left")
        self.sector_var = tk.StringVar(value="0 0")
        ttk.Entry(bar, textvariable=self.sector_var, width=6).pack(side="left", padx=2)
        ttk.Button(bar, text="Afficher", command=self.show_sector).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.file_label = ttk.Label(bar, text="(aucun disque)", foreground="#666")
        self.file_label.pack(side="left", padx=4)

        self.info = ttk.Label(self.tab_disk, text="Géométrie: —", padding=(8, 2),
                              anchor="w")
        self.info.pack(side="top", fill="x")

        pane = ttk.PanedWindow(self.tab_disk, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=4)

        left = ttk.LabelFrame(pane, text="Fichiers (Filer + AMSDOS)", padding=4)
        cols = ("name", "source", "type", "length", "offset")
        self.tree = ttk.Treeview(left, columns=cols, show="headings",
                                 selectmode="browse")
        self.tree.heading("name", text="Nom")
        self.tree.heading("source", text="Couche")
        self.tree.heading("type", text="Type")
        self.tree.heading("length", text="Longueur")
        self.tree.heading("offset", text="@")
        self.tree.column("name", width=130, anchor="w")
        self.tree.column("source", width=70, anchor="center")
        self.tree.column("type", width=50, anchor="center")
        self.tree.column("length", width=70, anchor="e")
        self.tree.column("offset", width=80, anchor="e")
        tvb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tvb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tvb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_file_select)

        actions = ttk.Frame(left)
        actions.pack(side="left", fill="x", pady=(6, 0))
        ttk.Button(actions, text="Ajouter…", command=self.add_file).pack(
            side="left", padx=2)
        ttk.Button(actions, text="Extraire…", command=self.extract_file).pack(
            side="left", padx=2)
        ttk.Button(actions, text="Supprimer", command=self.delete_file).pack(
            side="left", padx=2)
        pane.add(left, weight=1)

        right = ttk.LabelFrame(pane, text="Contenu (hex)", padding=4)
        self.hex_text = tk.Text(right, width=70, height=24,
                                font=("Courier", 10), state="disabled")
        hvsb = ttk.Scrollbar(right, orient="vertical", command=self.hex_text.yview)
        hsb = ttk.Scrollbar(right, orient="horizontal", command=self.hex_text.xview)
        self.hex_text.configure(xscrollcommand=hsb.set, yscrollcommand=hvsb.set)
        self.hex_text.pack(side="left", fill="both", expand=True)
        hvsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        pane.add(right, weight=2)

    def _refresh_files(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._files = []
        if self.disk is None:
            return
        fs = CpcFilesystem(self.disk)
        for f in fs.list_files():
            self._files.append(f)
            self.tree.insert(
                "", "end", iid=str(len(self._files) - 1),
                values=(f.name, f.source, f.type_name, f.length,
                        f"0x{f.offset:05X}"))

    def _selected_file(self) -> Optional[CpcFile]:
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx >= len(self._files):
            return None
        return self._files[idx]

    # ------------------------------------------------------------------ #
    # Ouverture / création / sauvegarde
    # ------------------------------------------------------------------ #
    def open_disk(self) -> None:
        path = filedialog.askopenfilename(
            title="Ouvrir une image .dsk",
            filetypes=[("CPC DSK", "*.dsk *.adf"), ("Tous", "*.*")])
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            self.disk = ADFDisk.load(path)
        except (OSError, ADFError) as exc:
            messagebox.showerror("Erreur d'ouverture", str(exc))
            return
        self.path = path
        self.file_label.config(text=path, foreground="#000")
        self._refresh()
        self._set_status(f"Ouvert: {path}")

    def new_disk(self) -> None:
        if self.disk is not None and not messagebox.askyesno(
                "Modifier", "Abandonner les modifications non sauvegardées ?"):
            return
        self.disk = ADFDisk.new_blank()
        self.path = None
        self.file_label.config(text="(nouveau)", foreground="#666")
        self._refresh()
        self._set_status("Nouvelle disquette vierge.")

    def save_disk(self) -> None:
        if self.disk is None:
            messagebox.showinfo("Sauver", "Aucune disquette à sauvegarder.")
            return
        if self.path is None:
            self.path = filedialog.asksaveasfilename(
                title="Sauver sous…", defaultextension=".dsk",
                filetypes=[("CPC DSK", "*.dsk")])
            if not self.path:
                return
        try:
            self.disk.save(self.path)
        except OSError as exc:
            messagebox.showerror("Erreur d'enregistrement", str(exc))
            return
        self.file_label.config(text=self.path, foreground="#000")
        self._set_status(f"Sauvegardé: {self.path}")

    def save_disk_as(self) -> None:
        """« Enregistrer sous » : sauvegarde la disquette sur un nouveau
        chemin (devient le chemin courant — les « Sauver » suivants
        écrivent sur ce nouveau fichier)."""
        if self.disk is None:
            messagebox.showinfo(
                "Enregistrer sous", "Aucune disquette à sauvegarder.")
            return
        path = filedialog.asksaveasfilename(
            title="Enregistrer la disquette sous…",
            defaultextension=".dsk",
            initialfile=os.path.basename(self.path) if self.path else None,
            filetypes=[("CPC DSK", "*.dsk")])
        if not path:
            return
        try:
            self.disk.save(path)
        except OSError as exc:
            messagebox.showerror("Erreur d'enregistrement", str(exc))
            return
        self.path = path
        self.file_label.config(text=path, foreground="#000")
        self._set_status(f"Enregistré sous: {path}")

    def _persist(self) -> None:
        """Sauvegarde sur le chemin courant (ou propose un chemin)."""
        if self.path is not None:
            try:
                self.disk.save(self.path)
                self._set_status(f"Sauvegardé: {self.path}")
                return
            except OSError as exc:
                messagebox.showerror("Erreur d'enregistrement", str(exc))
                return
        self.save_disk()

    def _refresh(self) -> None:
        if self.disk is None:
            self.info.config(text="Géométrie: —")
            self.tree.delete(*self.tree.get_children())
            self._files = []
            return
        self.info.config(text=self.disk.summary())
        self._refresh_files()

    # ------------------------------------------------------------------ #
    # Inspection hex
    # ------------------------------------------------------------------ #
    def _show_hex(self, data: bytes, title: str) -> None:
        self.hex_text.config(state="normal")
        self.hex_text.delete("1.0", "end")
        self.hex_text.insert("1.0", f"# {title}\n" + (hexdump(data) or "(vide)"))
        self.hex_text.config(state="disabled")

    def _on_file_select(self, _event) -> None:
        f = self._selected_file()
        if f is None or self.disk is None:
            return
        try:
            data = CpcFilesystem(self.disk).read_file(f.name, source=f.source)
        except (CpcError, ADFError) as exc:
            self._show_hex(b"", f"erreur: {exc}")
            return
        self._show_hex(
            data,
            f"{f.name}  [{f.source} {f.type_name} {f.length} o] "
            f"load={f.load_addr:#06x} @0x{f.offset:05X}")
        self._set_status(f"Fichier: {f.name} ({f.source})")

    def show_sector(self) -> None:
        if self.disk is None:
            messagebox.showinfo("Secteur", "Ouvrez d'abord une disquette.")
            return
        try:
            track_s, sec_s = self.sector_var.get().split()
            track, sector = int(track_s), int(sec_s)
            data = self.disk.get_sector(track, sector)
        except (ValueError, ADFError) as exc:
            messagebox.showerror(
                "Secteur invalide", f"« {self.sector_var.get()} » — {exc}")
            return
        self._show_hex(data, f"secteur piste {track} secteur {sector} "
                             f"({len(data)} o)")
        self._set_status(f"Secteur {track}/{sector}")

    # ------------------------------------------------------------------ #
    # Actions fichiers
    # ------------------------------------------------------------------ #
    def add_file(self) -> None:
        if self.disk is None:
            messagebox.showinfo("Ajout", "Créez ou ouvrez d'abord une disquette.")
            return
        local = filedialog.askopenfilename(
            title="Fichier local à copier sur la disquette")
        if not local:
            return
        self._do_add_file(local)

    def _do_add_file(self, local: str) -> None:
        dlg = AddFileDialog(self.root, _suggest_83(local))
        self.root.wait_window(dlg.win)
        if dlg.result is None:
            return
        try:
            with open(local, "rb") as fh:
                data = fh.read()
            CpcFilesystem(self.disk).write_file(
                dlg.result["name"], data,
                file_type=dlg.result["file_type"],
                load_addr=dlg.result["load_addr"],
                exec_addr=dlg.result["load_addr"],
                mode=dlg.result["mode"])
        except (CpcError, ADFError, OSError) as exc:
            messagebox.showerror("Échec de l'écriture", str(exc))
            return
        self._refresh_files()
        self._persist()
        self._set_status(f"Fichier {dlg.result['name']!r} ({_fmt_size(len(data))}) "
                         f"écrit [{dlg.result['mode']}].")

    def extract_file(self) -> None:
        f = self._selected_file()
        if f is None or self.disk is None:
            messagebox.showinfo("Extraction", "Sélectionnez un fichier à extraire.")
            return
        # Nom de fichier proposé avec l'extension CPC conservée :
        # « MONPROG BAS » -> « monprog.bas », sinon « nom.bin ».
        name = f.name.strip()
        if " " in name:
            base, _, ext = name.rpartition(" ")
            if ext in ("BAS", "BIN", "COM", "DOC", "SYS", "LIB", "B", "HEX"):
                base = base.strip()
                if base:
                    name = f"{base.lower()}.{ext.lower()}"
        out = filedialog.asksaveasfilename(
            title=f"Extraire {f.name} ({f.source})", initialfile=name)
        if not out:
            return
        try:
            data = CpcFilesystem(self.disk).read_file(f.name, source=f.source)
            with open(out, "wb") as fh:
                fh.write(data)
        except (CpcError, ADFError, OSError) as exc:
            messagebox.showerror("Échec de l'extraction", str(exc))
            return
        self._set_status(f"{f.name} ({f.source}) extrait vers {out} "
                         f"({_fmt_size(len(data))}).")

    def delete_file(self) -> None:
        f = self._selected_file()
        if f is None or self.disk is None:
            messagebox.showinfo("Suppression", "Sélectionnez un fichier à supprimer.")
            return
        if not messagebox.askyesno(
                "Supprimer", f"Supprimer {f.name} ({f.source}) de la disquette ?"):
            return
        try:
            CpcFilesystem(self.disk).delete_file(f.name)
        except (CpcError, ADFError) as exc:
            messagebox.showerror("Échec de la suppression", str(exc))
            return
        self._refresh_files()
        self._persist()
        self._set_status(f"Fichier {f.name!r} supprimé.")

    # ================================================================== #
    # Onglet Gotek
    # ================================================================== #
    def _build_gotek_tab(self) -> None:
        top = ttk.Frame(self.tab_gotek, padding=6)
        top.pack(fill="both", expand=True)

        sources = ttk.LabelFrame(top, text="Sources (disquettes .dsk/.adf)",
                                 padding=4)
        sources.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.gtk_tree = ttk.Treeview(
            sources, columns=("file", "size"), show="headings", height=10,
            selectmode="extended")
        self.gtk_tree.heading("file", text="Fichier")
        self.gtk_tree.heading("size", text="Taille")
        self.gtk_tree.column("file", width=380, anchor="w")
        self.gtk_tree.column("size", width=80, anchor="e")
        gs = ttk.Frame(sources)
        gs.pack(side="left", fill="x", pady=(6, 0))
        ttk.Button(gs, text="Ajouter…", command=self.gotek_add).pack(side="left", padx=2)
        ttk.Button(gs, text="Retirer", command=self.gotek_remove).pack(side="left", padx=2)
        ttk.Button(gs, text="Vider", command=self.gotek_clear).pack(side="left", padx=2)
        top.columnconfigure(0, weight=2)

        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True)
        top.columnconfigure(1, weight=1)

        opts = ttk.LabelFrame(right, text="Options de nommage", padding=4)
        opts.pack(side="top", fill="x")
        self.gtk_pattern = tk.StringVar(value=DEFAULT_NAME_PATTERN)
        self.gtk_subfolder = tk.StringVar(value="")
        self.gtk_index = tk.IntVar(value=1)
        ttk.Label(opts, text="Patron de noms:").grid(row=0, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.gtk_pattern, width=20).grid(
            row=0, column=1, padx=4)
        ttk.Label(opts, text="Sous-dossier:").grid(row=1, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.gtk_subfolder, width=20).grid(
            row=1, column=1, padx=4)
        ttk.Label(opts, text="Index de départ:").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(opts, from_=0, to=999, textvariable=self.gtk_index,
                    width=6).grid(row=2, column=1, sticky="w", padx=4)

        out = ttk.LabelFrame(right, text="Sortie (contenu de la clé USB)",
                             padding=4)
        out.pack(side="top", fill="x", pady=(6, 0))
        self.gtk_outdir = tk.StringVar(value="")
        ttk.Entry(out, textvariable=self.gtk_outdir, width=46).pack(
            side="left", fill="x", expand=True)
        ttk.Button(out, text="Choisir…", command=self.gotek_choose_outdir).pack(
            side="left", padx=4)

        acts = ttk.Frame(right)
        acts.pack(side="top", fill="x", pady=(6, 0))
        ttk.Button(acts, text="Générer le répertoire USB…",
                   command=self.gotek_prepare).pack(side="left", padx=2)
        ttk.Button(acts, text="Vérifier le dossier…",
                   command=self.gotek_verify).pack(side="left", padx=2)
        ttk.Button(acts, text="Image FAT (.img)…",
                   command=self.gotek_fat_image).pack(side="left", padx=2)

        res = ttk.LabelFrame(right, text="Résultat", padding=4)
        res.pack(side="top", fill="both", expand=True, pady=(6, 0))
        self.gtk_result = tk.Listbox(res, width=52, font=("Courier", 9))
        self.gtk_result.pack(fill="both", expand=True)

    def _gotek_config(self) -> GotekConfig:
        try:
            return GotekConfig(
                name_pattern=self.gtk_pattern.get() or DEFAULT_NAME_PATTERN,
                subfolder=self.gtk_subfolder.get().strip("/"),
                start_index=self.gtk_index.get(),
            )
        except Exception as exc:  # noqa: BLE001 — limite d'entrée GUI
            raise GotekError(f"Options invalides: {exc}") from exc

    def _gotek_check(self) -> bool:
        if not self._gotek_sources:
            messagebox.showinfo(
                "Sources vides",
                "Ajoutez au moins une disquette (.dsk/.adf) dans la liste.")
            return False
        if not self.gtk_outdir.get().strip():
            messagebox.showinfo(
                "Sortie manquante",
                "Choisissez le répertoire de sortie (contenu de la clé USB).")
            return False
        return True

    def gotek_add(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Disquettes à mettre sur la clé",
            filetypes=[("CPC DSK", "*.dsk *.adf"), ("Tous", "*.*")])
        self.gotek_add_paths(paths)

    def gotek_add_paths(self, paths: List[str]) -> None:
        for p in paths:
            if p not in self._gotek_sources:
                self._gotek_sources.append(p)
        self.gtk_tree.delete(*self.gtk_tree.get_children())
        for p in self._gotek_sources:
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            self.gtk_tree.insert("", "end", values=(p, _fmt_size(size)))
        self._set_status(f"Gotek: {len(self._gotek_sources)} source(s).")

    def gotek_remove(self) -> None:
        for iid in self.gtk_tree.selection():
            path = self.gtk_tree.item(iid, "values")[0]
            if path in self._gotek_sources:
                self._gotek_sources.remove(path)
        self.gtk_tree.delete(*self.gtk_tree.selection())

    def gotek_clear(self) -> None:
        self._gotek_sources = []
        self.gtk_tree.delete(*self.gtk_tree.get_children())

    def gotek_choose_outdir(self) -> None:
        d = filedialog.askdirectory(title="Répertoire de sortie (contenu de la clé)")
        if d:
            self.gtk_outdir.set(d)

    def _gotek_result_show(self, lines: List[str]) -> None:
        self.gtk_result.delete(0, "end")
        for line in lines:
            self.gtk_result.insert("end", line)

    def gotek_prepare(self) -> None:
        if not self._gotek_check():
            return
        try:
            config = self._gotek_config()
            created = prepare_usb_directory(
                self.gtk_outdir.get().strip(), self._gotek_sources, config)
        except (GotekError, ADFError, OSError) as exc:
            messagebox.showerror("Échec de la génération", str(exc))
            return
        self._gotek_result_show(created)
        self._set_status(
            f"Gotek: {len(created)} image(s) écrite(s) dans "
            f"{self.gtk_outdir.get().strip()}")

    def gotek_verify(self) -> None:
        out = self.gtk_outdir.get().strip()
        if not out:
            messagebox.showinfo("Vérification", "Choisissez d'abord le répertoire.")
            return
        try:
            valid = verify_usb_directory(out)
        except (GotekError, ADFError, OSError) as exc:
            messagebox.showerror("Vérification", str(exc))
            return
        self._gotek_result_show([os.path.basename(p) for p in valid])
        self._set_status(f"Gotek: {len(valid)} image(s) valide(s) dans {out}.")

    def gotek_fat_image(self) -> None:
        # Le répertoire « Sortie » n'est PAS requis ici (il ne sert qu'au
        # générer/vérifier) : le dialogue de sauvegarde donne le .img.
        if not self._gotek_sources:
            messagebox.showinfo(
                "Sources vides",
                "Ajoutez au moins une disquette (.dsk/.adf) dans la liste.")
            return
        out_img = filedialog.asksaveasfilename(
            title="Image FAT de la clé (32 Mo, à graver sur la clé USB)",
            defaultextension=".img",
            filetypes=[("Image FAT", "*.img")])
        if not out_img:
            return
        try:
            config = self._gotek_config()
            create_fat_image(out_img, self._gotek_sources, config)
        except GotekError as exc:
            messagebox.showinfo("Image FAT", str(exc))
            return
        except (OSError, ADFError) as exc:
            messagebox.showerror("Échec de l'image FAT", str(exc))
            return
        self._set_status(f"Gotek: image FAT créée: {out_img}")

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
            if self.notebook.index(self.notebook.select()) == 1:
                self.gotek_add_paths(disks)
                return
            if self.disk is None:
                self._open_path(disks[0])
            else:
                self.gotek_add_paths(disks)
                self.notebook.select(self.tab_gotek)
                return

        for p in others:
            if self.disk is None:
                messagebox.showinfo(
                    "Ajout", "Créez ou ouvrez d'abord une disquette.")
                return
            self._do_add_file(p)

    # ================================================================== #
    # Divers
    # ================================================================== #
    def _set_status(self, text: str) -> None:
        self.status.config(text=text)


def run() -> None:
    root = tk.Tk()
    DskEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
