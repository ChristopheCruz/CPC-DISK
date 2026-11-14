"""Interface graphique (tkinter) de cpc_dsk.

Ouvre une image ``.dsk`` (ADF), affiche sa géométrie, permet de parcourir les
pistes / faces / secteurs et d'inspecter le contenu brut d'un secteur en
hexadécimal. C'est une première itération de l'éditeur visuel.

Lancement:
    python -m cpc_dsk.gui
ou:
    cpc-dsk-gui          (si le point d'entrée est installé)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.cli import hexdump


class DskEditorApp:
    """Fenêtre principale de l'éditeur de disquettes."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Éditeur de disquettes CPC (.dsk ADF)")
        self.root.geometry("900x560")

        self.disk: ADFDisk | None = None
        self.path: str | None = None

        self._build_toolbar()
        self._build_info()
        self._build_panes()
        self._build_status()

    # ------------------------------------------------------------------ #
    # Construction de l'interface
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
        self.info = ttk.Label(self.root, text="Géométrie: —", padding=(8, 2))
        self.info.pack(side="top", fill="x")

    def _build_panes(self) -> None:
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=4)

        # Arbre de navigation (piste -> face -> secteur).
        tree_frame = ttk.LabelFrame(pane, text="Navigation", padding=4)
        self.tree = ttk.Treeview(tree_frame, columns=("addr",), show="tree headings")
        self.tree.heading("#0", text="Piste / Face / Secteur")
        self.tree.heading("addr", text="Adresse")
        self.tree.column("addr", width=90, anchor="e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        pane.add(tree_frame, weight=1)

        # Zone hexadécimale.
        hex_frame = ttk.LabelFrame(pane, text="Contenu du secteur (hex)", padding=4)
        self.hex_text = tk.Text(hex_frame, width=60, height=20,
                                font=("Courier", 10), state="disabled")
        hsb = ttk.Scrollbar(hex_frame, orient="horizontal", command=self.hex_text.xview)
        hvsb = ttk.Scrollbar(hex_frame, orient="vertical", command=self.hex_text.yview)
        self.hex_text.configure(xscrollcommand=hsb.set, yscrollcommand=hvsb.set)
        self.hex_text.pack(side="left", fill="both", expand=True)
        hvsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        pane.add(hex_frame, weight=2)

    def _build_status(self) -> None:
        self.status = ttk.Label(self.root, text="Prêt.", relief="sunken", anchor="w")
        self.status.pack(side="bottom", fill="x")

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def open_disk(self) -> None:
        path = filedialog.askopenfilename(
            title="Ouvrir une image .dsk",
            filetypes=[("ADF / DSK", "*.dsk *.adf"), ("Tous les fichiers", "*.*")])
        if not path:
            return
        try:
            self.disk = ADFDisk.load(path)
        except (OSError, ADFError) as exc:
            messagebox.showerror("Erreur d'ouverture", str(exc))
            return
        self.path = path
        self.file_label.config(text=path, foreground="#000")
        self._refresh_info()
        self._populate_tree()
        self._set_status(f"Ouvert: {path}")

    def new_disk(self) -> None:
        if self.disk is not None and not self._confirm_discard():
            return
        self.disk = ADFDisk.new_blank()
        self.path = None
        self.file_label.config(text="(nouveau, non sauvegardé)", foreground="#666")
        self._refresh_info()
        self._populate_tree()
        self._set_status("Nouvelle disquette vierge (non sauvegardée).")

    def save_disk(self) -> None:
        if self.disk is None:
            messagebox.showinfo("Sauver", "Aucune disquette à sauvegarder.")
            return
        if self.path is None:
            self.path = filedialog.asksaveasfilename(
                title="Sauver sous…", defaultextension=".dsk",
                filetypes=[("ADF / DSK", "*.dsk")])
            if not self.path:
                return
        try:
            self.disk.save(self.path)
        except OSError as exc:
            messagebox.showerror("Erreur d'enregistrement", str(exc))
            return
        self.file_label.config(text=self.path, foreground="#000")
        self._set_status(f"Sauvegardé: {self.path}")

    def _confirm_discard(self) -> bool:
        return messagebox.askyesno(
            "Modifier", "Abandonner les modifications non sauvegardées ?")

    # ------------------------------------------------------------------ #
    # Mise à jour de l'affichage
    # ------------------------------------------------------------------ #
    def _refresh_info(self) -> None:
        if self.disk is None:
            self.info.config(text="Géométrie: —")
            return
        d = self.disk
        self.info.config(
            text=(f"Géométrie: {d.tracks} pistes x {d.sides} faces x "
                  f"{d.sectors_per_track} secteurs x {d.sector_size} o   |   "
                  f"Capacité: {d.data_capacity // 1024} Ko   |   "
                  f"Fichier: {d.expected_file_size()} o"))

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        if self.disk is None:
            return
        for track in range(self.disk.tracks):
            for side in range(self.disk.sides):
                node = self.tree.insert(
                    "", "end",
                    text=f"Piste {track} — Face {side}",
                    values=(f"T{track}/F{side}",))
                for sector in range(self.disk.sectors_per_track):
                    self.tree.insert(
                        node, "end",
                        text=f"Secteur {sector}",
                        values=(f"{track},{side},{sector}",))
            # Garde l'arbre raisonnable: ne déplier que la première piste.
            self.tree.item(node, open=(track == 0))

    def _on_select(self, _event) -> None:
        sel = self.tree.selection()
        if not sel or self.disk is None:
            return
        item = sel[0]
        values = self.tree.item(item, "values")
        if not values:
            return
        try:
            track, side, sector = (int(x) for x in values[0].split(","))
        except ValueError:
            return  # Un nœud piste/face a été sélectionné (pas un secteur).
        data = self.disk.get_sector(track, side, sector)
        self._show_hex(data, f"piste={track} face={side} secteur={sector}")

    def _show_hex(self, data: bytes, title: str) -> None:
        self.hex_text.config(state="normal")
        self.hex_text.delete("1.0", "end")
        self.hex_text.insert("1.0", f"# {title}\n" + hexdump(data))
        self.hex_text.config(state="disabled")
        self._set_status(title)

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)


def run() -> None:
    root = tk.Tk()
    DskEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
