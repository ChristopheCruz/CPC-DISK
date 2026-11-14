"""Interface graphique (tkinter) de cpc_dsk.

Ouvre une image ``.dsk`` (CPC), affiche sa géométrie et sa liste de fichiers,
et permet d'inspecter en hexadécimal le contenu d'un fichier ou d'un secteur.

Lancement:
    python -m cpc_dsk.gui
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List

from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.core.cpcfs import CpcFile, CpcFilesystem
from cpc_dsk.cli import hexdump


class DskEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Éditeur de disquettes CPC (.dsk)")
        self.root.geometry("920x580")

        self.disk: ADFDisk | None = None
        self.path: str | None = None
        self._files: List[CpcFile] = []

        self._build_toolbar()
        self._build_info()
        self._build_panes()
        self._build_status()

    # ------------------------------------------------------------------ #
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Ouvrir…", command=self.open_disk).pack(side="left", padx=2)
        ttk.Button(bar, text="Nouveau", command=self.new_disk).pack(side="left", padx=2)
        ttk.Button(bar, text="Sauver", command=self.save_disk).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="Fichier:").pack(side="left")
        self.file_label = ttk.Label(bar, text="(aucun)", foreground="#666")
        self.file_label.pack(side="left", padx=4)

    def _build_info(self) -> None:
        self.info = ttk.Label(self.root, text="Géométrie: —", padding=(8, 2),
                              anchor="w")
        self.info.pack(side="top", fill="x")

    def _build_panes(self) -> None:
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=4)

        left = ttk.LabelFrame(pane, text="Fichiers", padding=4)
        self.file_list = tk.Listbox(left, width=30, exportselection=False)
        fsb = ttk.Scrollbar(left, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=fsb.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        fsb.pack(side="right", fill="y")
        self.file_list.bind("<<ListboxSelect>>", self._on_file_select)
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
        pane.add(right, weight=3)

    def _build_status(self) -> None:
        self.status = ttk.Label(self.root, text="Prêt.", relief="sunken", anchor="w")
        self.status.pack(side="bottom", fill="x")

    # ------------------------------------------------------------------ #
    def open_disk(self) -> None:
        path = filedialog.askopenfilename(
            title="Ouvrir une image .dsk",
            filetypes=[("CPC DSK", "*.dsk *.adf"), ("Tous", "*.*")])
        if not path:
            return
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

    # ------------------------------------------------------------------ #
    def _refresh(self) -> None:
        if self.disk is None:
            self.info.config(text="Géométrie: —")
            self.file_list.delete(0, "end")
            return
        self.info.config(text=self.disk.summary())
        self.file_list.delete(0, "end")
        fs = CpcFilesystem(self.disk)
        self._files: List[CpcFile] = fs.list_files()
        for f in self._files:
            self.file_list.insert("end",
                                  f"{f.name}  [{f.source} {f.type_name} {f.length}o]")
        self._show_hex(b"", "(sélectionne un fichier)")

    def _on_file_select(self, _event) -> None:
        sel = self.file_list.curselection()
        if not sel or self.disk is None:
            return
        idx = sel[0]
        if idx >= len(self._files):
            return
        f = self._files[idx]
        try:
            data = CpcFilesystem(self.disk).read_file(f.name, source=f.source)
        except Exception as exc:  # noqa: BLE001 - affichage GUI
            self._show_hex(b"", f"erreur: {exc}")
            return
        self._show_hex(data, f"{f.name}  [{f.source} {f.type_name} {f.length} o] "
                             f"load={f.load_addr:#06x}")
        self._set_status(f"Fichier: {f.name} ({f.source})")

    def _show_hex(self, data: bytes, title: str) -> None:
        self.hex_text.config(state="normal")
        self.hex_text.delete("1.0", "end")
        self.hex_text.insert("1.0", f"# {title}\n" + (hexdump(data) or "(vide)"))
        self.hex_text.config(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)


def run() -> None:
    root = tk.Tk()
    DskEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
