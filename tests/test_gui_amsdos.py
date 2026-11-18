"""L'interface ouvre une disquette AMSDOS par le vrai catalogue."""

import os
import tkinter as tk

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ16 = os.path.join(HERE, "..", "test_disks", "seq16.dsk")


def _display_available() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


pytestmark = pytest.mark.skipif(not _display_available(), reason="pas d'affichage")


def test_open_seq16_lists_catalog():
    from cpc_dsk.core.amsdos import AmsdosFile
    from cpc_dsk.gui import DskEditorApp
    root = tk.Tk()
    root.withdraw()
    try:
        app = DskEditorApp(root)
        app._open_path(SEQ16)
        names = [f.name for f in app._files]
        assert len(names) == 23
        assert names[0] == "SEQ16.BIN" and "BRUITS.INS" in names
        assert all(isinstance(f, AmsdosFile) for f in app._files)
        app.tree.selection_set("0")
        app._on_file_select(None)
        # SEQ16.BIN : 14 440 o + en-tête = 15 blocs de 1 Ko = 30 secteurs.
        assert len(app._file_secs) == 30
    finally:
        root.destroy()
