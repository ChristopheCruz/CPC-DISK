"""Tests de l'éditeur de banques SEQ-16 (cpc_dsk.seq16.smp_gui) : fenêtre
autonome, et onglet « SAMPLES SEQ-16 » de CPC DISK.

Repris de tools/test_smp_gui.py de SEQ-16 (partie interface). Sautés sans
écran. Aucune boîte de dialogue n'est ouverte (actions appelées avec leurs
fichiers).
"""
import math
import os
import shutil
import tempfile
import tkinter as tk
import unittest

import pytest

from cpc_dsk.i18n import set_language
from cpc_dsk.seq16 import dskio, wav2smp

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ16_DSK = os.path.join(HERE, "..", "test_disks", "seq16.dsk")


def _display_available() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


pytestmark = pytest.mark.skipif(not _display_available(), reason="pas d'affichage")


def sine(freq, seconds, rate=22050, amp=0.7):
    """Sinus de test (liste de flottants)."""
    return [amp * math.sin(2 * math.pi * freq * i / rate) for i in range(int(seconds * rate))]


class Base(unittest.TestCase):
    """Dossier temporaire avec deux WAV de synthèse et la banque d'usine."""

    def setUp(self):
        set_language("fr")
        self.tmp = tempfile.mkdtemp()
        self.wav = os.path.join(self.tmp, "kick drum.wav")
        wav2smp.write_wav(self.wav, [0.0] * 2000 + sine(220, 0.4) + [0.0] * 3000, 22050)
        self.wav2 = os.path.join(self.tmp, "boucle.wav")
        wav2smp.write_wav(self.wav2, sine(110, 1.0, rate=16000), 16000)
        self.drums = os.path.join(self.tmp, "DRUMS.SMP")
        with open(self.drums, "wb") as f:
            f.write(dskio.read_file(SEQ16_DSK, "DRUMS.SMP"))
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        finally:
            shutil.rmtree(self.tmp)

    def pump(self):
        """Traite les événements Tk en attente."""
        self.root.update()


class TestStandalone(Base):
    """Fenêtre autonome (python -m cpc_dsk.seq16.smp_gui)."""

    def setUp(self):
        super().setUp()
        from cpc_dsk.seq16 import smp_gui
        self.app = smp_gui.SmpApp(self.root)

    def tearDown(self):
        self.app.player.close()
        super().tearDown()

    def test_window_mode(self):
        app = self.app
        self.assertFalse(app.embedded)
        self.assertIs(app.root, self.root)
        self.assertEqual(self.root.title(), "SEQ-16 SAMPLER - banques .SMP")

    def test_build_add_edit_theme(self):
        app = self.app
        app.add_wavs([self.wav, self.wav2])
        self.pump()
        self.assertEqual(len(app.tree.get_children()), 2)
        self.assertEqual(app._sel_index, 1)
        app.v_bits.set("2")                                     # réglage
        app.v_name.set("zz top")
        app._apply_now()
        it = app.model.items[1]
        self.assertEqual((it.bits, it.name), (2, "ZZTOP"))
        self.assertEqual(app.tree.item("1", "values")[1], "ZZTOP")
        app.v_hz.set("6250")                                    # fréquence en Hz
        app._hz_entered()
        app._apply_now()
        self.assertEqual(it.code, 160)
        app.v_slices.set("2")
        app.apply_slices()
        self.assertEqual(len(app.model), 3)
        app.move(-1)
        app.toggle_monitor()                                    # F3 : reconstruit
        self.pump()
        self.assertEqual(app._theme_name, "vert")
        self.assertEqual(len(app.tree.get_children()), 3)
        app.remove()
        self.assertEqual(len(app.model), 2)

    def test_open_bank_disables_source_settings(self):
        app = self.app
        app.open_smp(self.drums)
        self.pump()
        self.assertEqual(len(app.tree.get_children()), 4)
        self.assertEqual(str(app._widgets_src[0].cget("state")), "disabled")
        self.assertIn("pas de WAV", app.note.cget("text"))
        self.assertFalse(app.b_play_src._enabled)
        self.assertTrue(app.b_save._enabled)

    def test_gauge_over_limit(self):
        long_wav = os.path.join(self.tmp, "long.wav")
        wav2smp.write_wav(long_wav, sine(300, 4.5, rate=8000), 8000)
        self.app.add_wavs([long_wav])
        self.pump()
        self.assertIn("TROP GRAND", self.app.gauge_lbl.cget("text"))
        self.assertFalse(self.app.b_save._enabled)

    def test_status_error_localized(self):
        """Erreur du modèle affichée dans la langue de l'interface."""
        app = self.app
        app.add_wavs([self.wav])
        set_language("en")
        app.v_hz.set("99999")
        app._hz_entered()
        self.assertEqual(app.status.cget("text"),
                         "The frequency ranges from 4,000 to 16,000 Hz.")


class TestEmbedded(Base):
    """Onglet « SAMPLES SEQ-16 » de CPC DISK."""

    def setUp(self):
        super().setUp()
        from cpc_dsk.gui import DskEditorApp
        self.app = DskEditorApp(self.root)
        set_language("fr")
        self.app.set_language("fr")

    def tearDown(self):
        if self.app._smp is not None:
            self.app._smp.player.close()
        super().tearDown()

    def test_tab_exists_and_builds_lazily(self):
        app = self.app
        self.assertEqual([lbl.cget("text") for lbl in app._tab_labels][2], "SAMPLES SEQ-16")
        self.assertIsNone(app._smp)                             # pas construit d'avance
        app._show_tab(2)
        self.pump()
        smp = app._smp
        self.assertIsNotNone(smp)
        self.assertTrue(smp.embedded)
        self.assertIs(smp.parent, app.tab_samples)
        self.assertIs(smp.root, self.root)
        self.assertEqual(app.tab_samples.winfo_manager(), "pack")   # affiché
        self.assertEqual(app.tab_disk.winfo_manager(), "")          # caché
        # La fenêtre reste celle de CPC DISK (titre non remplacé).
        self.assertNotIn("SAMPLER", self.root.title())
        # Ctrl+W / drag-drop routés vers l'éditeur quand l'onglet est affiché.
        app._on_drop([self.wav])
        self.assertEqual(len(smp.model), 1)
        app._show_tab(0)
        self.assertEqual(app.tab_samples.winfo_manager(), "")

    def test_language_and_theme_rebuild_keep_bank(self):
        app = self.app
        app._show_tab(2)
        smp = app._smp
        smp.add_wavs([self.wav, self.wav2])
        app.set_language("en")                                  # reconstruit l'interface
        self.pump()
        self.assertIs(app._smp, smp)
        self.assertIs(smp.parent, app.tab_samples)
        self.assertEqual(len(smp.tree.get_children()), 2)
        self.assertEqual(app._tab_labels[2].cget("text"), "SAMPLES SEQ-16")
        self.assertIn("MEMORY", smp.gauge_lbl.cget("text"))
        app.toggle_monitor()
        self.pump()
        self.assertEqual(smp._theme_name, "vert")
        self.assertEqual(smp.t.paper, app.t.paper)
        self.assertEqual(len(smp.tree.get_children()), 2)
        app.zoom_in()                                           # suit le zoom
        self.pump()
        self.assertAlmostEqual(smp.scale, app.scale * app.zoom)
        set_language("fr")

    def test_add_to_open_disk(self):
        """« Ajouter à la disquette » vers la disquette ouverte dans l'onglet
        Disquette : écrite, sauvée, catalogue rafraîchi."""
        app = self.app
        dsk = os.path.join(self.tmp, "copie.dsk")
        shutil.copy(SEQ16_DSK, dsk)
        app._open_path(dsk)
        app._show_tab(2)
        smp = app._smp
        smp.add_wavs([self.wav])
        smp.bank_path = os.path.join(self.tmp, "mes sons.smp")
        self.assertIs(smp._host_disk(), app.disk)
        smp._add_to_host_disk(app.disk, "MESSONS.SMP", "copie.dsk")
        self.assertIn("MESSONS.SMP", [f.name for f in app._files])
        self.assertEqual(dskio.read_file(dsk, "MESSONS.SMP"), smp.model.build())
        self.assertIn("disquette ouverte", smp.status.cget("text"))


if __name__ == "__main__":
    unittest.main()
