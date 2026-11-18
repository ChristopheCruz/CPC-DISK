"""Tests SEQ-16 sans écran : wav2smp (conversion, format .SMP, ligne de
commande), smp_model (modèle de l'éditeur) et dskio (disquette, par le
catalogue AMSDOS de cpc_dsk.core.amsdos).

Repris de tools/test_wav2smp.py et tools/test_smp_gui.py de SEQ-16. Les
tests liés aux modules propres à SEQ-16 (gen_drums, gen_smp_tables,
src/smptables.asm) restent dans SEQ-16. La disquette de référence est
test_disks/seq16.dsk (copie de build/seq16.dsk) ; on travaille toujours sur
une copie.
"""
import io
import math
import os
import random
import shutil
import struct
import tempfile
import unittest
import wave

from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.amsdos import AmsdosFilesystem, new_data_disk
from cpc_dsk.i18n import set_language
from cpc_dsk.seq16 import dskio, smp_model, wav2smp
from cpc_dsk.seq16.smp_model import BankError, BankModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ16_DSK = os.path.join(HERE, "..", "test_disks", "seq16.dsk")


def read(path):
    """Contenu d'un fichier (fermé aussitôt)."""
    with open(path, "rb") as f:
        return f.read()


def sine(freq, seconds, rate=22050, amp=0.7):
    """Sinus de test (liste de flottants)."""
    return [amp * math.sin(2 * math.pi * freq * i / rate) for i in range(int(seconds * rate))]


def write_raw_wav(path, frames, rate, width, channels):
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)


def drums_bank():
    """Banque d'usine DRUMS.SMP, relue sur test_disks/seq16.dsk."""
    return dskio.read_file(SEQ16_DSK, "DRUMS.SMP")


# ====================================================================== #
# wav2smp
# ====================================================================== #
class TestConversion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ay_table(self):
        """16 niveaux croissants, de 0 à 1 (table Ayumi)."""
        self.assertEqual(len(wav2smp.AY_LEVELS), 16)
        self.assertEqual(wav2smp.AY_LEVELS[0], 0.0)
        self.assertEqual(wav2smp.AY_LEVELS[15], 1.0)
        self.assertEqual(sorted(wav2smp.AY_LEVELS), wav2smp.AY_LEVELS)

    def test_sine_roundtrip(self):
        """Un sinus converti puis relu : taille, niveaux, forme conservée."""
        x = sine(440, 0.5, rate=44100, amp=0.8)
        s = wav2smp.convert(x, 44100, "sinus", rate=8000)
        raw = wav2smp.build_bank([s])
        back = wav2smp.parse_bank(raw)[0]
        self.assertEqual(back.name, "SINUS")
        self.assertEqual(back.code, 125)                # 1 000 000 / 8000
        self.assertEqual(len(back.data), 2000)          # 4000 échantillons / 2
        codes = wav2smp.unpack(back.data)
        self.assertTrue(all(0 <= c <= 15 for c in codes))
        self.assertIn(15, codes)                        # normalisé : crête au max
        ref = sine(440, 0.5, rate=8000, amp=0.8)
        r = wav2smp.render(codes)
        corr = sum(a * b for a, b in zip(ref, r))
        norm = math.sqrt(sum(a * a for a in ref) * sum(b * b for b in r))
        self.assertGreater(corr / norm, 0.9)

    def test_quantize_nearest(self):
        """Chaque amplitude va au niveau AY le plus proche."""
        for code, lv in enumerate(wav2smp.AY_LEVELS):
            v = lv * 2 - 1                              # amplitude -> signal
            self.assertEqual(wav2smp.quantize([v])[0], code)
        rng = random.Random(0)
        for _ in range(500):
            v = rng.uniform(-1, 1)
            c = wav2smp.quantize([v])[0]
            a = (v + 1) / 2
            best = min(abs(lv - a) for lv in wav2smp.AY_LEVELS)
            self.assertAlmostEqual(abs(wav2smp.AY_LEVELS[c] - a), best)

    def test_dither_levels(self):
        x = [math.sin(i / 7) * 0.3 for i in range(2000)]
        codes = wav2smp.quantize(x, "noise", random.Random(5))
        self.assertTrue(all(0 <= c <= 15 for c in codes))

    def test_bits(self):
        x = sine(300, 0.2, rate=44100, amp=0.8)
        for bits, mask in ((3, 0xE), (2, 0xC), (1, 0x8)):
            s = wav2smp.convert(x, 44100, "b", bits=bits)
            codes = wav2smp.unpack(s.data)
            self.assertTrue(all(c & ~mask == 0 for c in codes), bits)
        codes = wav2smp.unpack(wav2smp.convert(x, 44100, "b", bits=1).data)
        self.assertEqual(set(codes), {0, 8})

    def test_trim(self):
        x = [0.0] * 50 + [0.001, 0.5, -1.0, 0.3] + [0.0] * 80
        self.assertEqual(wav2smp.trim(x), [0.5, -1.0, 0.3])
        self.assertEqual(wav2smp.trim([0.0, 0.0]), [0.0, 0.0])

    def test_pack_order(self):
        """Premier échantillon dans les 4 bits de poids fort."""
        self.assertEqual(wav2smp.pack([1, 2, 3, 4]), bytes([0x12, 0x34]))
        self.assertEqual(wav2smp.pack([5]), bytes([0x55]))
        self.assertEqual(wav2smp.unpack(bytes([0xAB])), [10, 11])

    def test_header_and_entries(self):
        s1 = wav2smp.Sample("KICK", b"\x11" * 10, 160, decim=3, bits=2)
        s2 = wav2smp.Sample("LONGNAME", b"\x22" * 7, 80, loop=4,
                            flags=wav2smp.F_LOOP | wav2smp.F_BACKWARD | (2 << 4))
        raw = wav2smp.build_bank([s1, s2])
        self.assertEqual(raw[:4], b"SQSM")
        self.assertEqual(raw[4], 1)
        self.assertEqual(raw[5], 2)
        self.assertEqual(raw[6:16], bytes(10))
        self.assertEqual(len(raw), 16 + 2 * 16 + 17)
        e = raw[16:32]
        self.assertEqual(e[:6], b"KICK  ")
        self.assertEqual(e[6], 0)
        self.assertEqual(struct.unpack("<HHBHBB", e[7:16]), (0, 10, 160, 0xFFFF, 0, 2 | 2 << 3))
        e = raw[32:48]
        self.assertEqual(e[:6], b"LONGNA")
        self.assertEqual(struct.unpack("<H", e[7:9])[0], 10)   # après le 1er
        a, b = wav2smp.parse_bank(raw)
        self.assertEqual((a.decim, a.bits), (3, 2))
        self.assertEqual((b.loop, b.flags, b.data), (4, 0x23, b"\x22" * 7))

    def test_bad_headers(self):
        good = wav2smp.build_bank([wav2smp.Sample("A", b"\x00", 125)])
        with self.assertRaises(ValueError):
            wav2smp.parse_bank(b"XXXX" + good[4:])
        with self.assertRaises(ValueError):
            wav2smp.parse_bank(good[:4] + b"\x09" + good[5:])
        with self.assertRaises(ValueError):
            wav2smp.build_bank([])
        with self.assertRaises(ValueError):
            wav2smp.build_bank([wav2smp.Sample("A", b"\x00", 125)] * 17)

    def test_no_block_crossing(self):
        """Aucun sample ne chevauche une frontière de 16 Ko."""
        sizes = [10000, 10000, 16384, 300]
        raw = wav2smp.build_bank([wav2smp.Sample("S%d" % i, bytes([i]) * n, 125)
                                  for i, n in enumerate(sizes)])
        base = 16 + 16 * len(sizes)
        for i, n in enumerate(sizes):
            e = raw[16 + 16 * i:32 + 16 * i]
            blk, off = e[6], struct.unpack("<H", e[7:9])[0]
            self.assertLessEqual(off + n, wav2smp.BLOCK, i)
            start = base + blk * wav2smp.BLOCK + off
            self.assertEqual(raw[start:start + n], bytes([i]) * n)
        self.assertEqual([s.data for s in wav2smp.parse_bank(raw)],
                         [bytes([i]) * n for i, n in enumerate(sizes)])

    def test_rate_codes(self):
        self.assertEqual(wav2smp.rate_to_code(4000), 250)
        self.assertEqual(wav2smp.rate_to_code(16000), 62)
        self.assertEqual(wav2smp.rate_to_code(100000), 62)     # borné
        self.assertEqual(wav2smp.rate_to_code(1000), 250)

    def test_decimation_render(self):
        r = wav2smp.render([0, 15, 3, 7, 9, 1], decim=2)
        lv = wav2smp.AY_LEVELS
        expected = [lv[0], lv[0], lv[3], lv[3], lv[9], lv[9]]
        mean = sum(expected) / 6
        for a, b in zip(r, expected):
            self.assertAlmostEqual(a, b - mean)

    def test_resample_no_filter(self):
        x = list(range(100))
        self.assertEqual(wav2smp.resample(x, 1000, 250), [0, 4, 8, 12] + list(range(16, 100, 4)))
        self.assertEqual(len(wav2smp.resample(x, 1000, 250, clean=True)), 25)

    def test_wav_formats(self):
        """8 bits stéréo et 16 bits mono sont lus et mixés en mono."""
        p8 = os.path.join(self.tmp, "a.wav")
        write_raw_wav(p8, bytes([255, 1, 128, 128]), 22050, 1, 2)
        x, sr = wav2smp.read_wav(p8)
        self.assertEqual(sr, 22050)
        self.assertEqual(len(x), 2)
        self.assertAlmostEqual(x[0], 0.0, places=2)
        p16 = os.path.join(self.tmp, "b.wav")
        write_raw_wav(p16, struct.pack("<hh", 16384, -32768), 8000, 2, 1)
        x, _ = wav2smp.read_wav(p16)
        self.assertEqual(x, [0.5, -1.0])

    def test_cli_slice_and_preview(self):
        """--slice 4 : 4 samples de taille égale, 4 WAV d'écoute."""
        src = os.path.join(self.tmp, "boucle.wav")
        wav2smp.write_wav(src, sine(100, 1.0, rate=16000, amp=0.8), 16000)
        out = os.path.join(self.tmp, "B.SMP")
        wav2smp.main([src, "--slice", "4", "--rate", "8000", "-o", out])
        bank = wav2smp.parse_bank(read(out))
        self.assertEqual([s.name for s in bank], ["BOUC00", "BOUC01", "BOUC02", "BOUC03"])
        self.assertEqual({len(s.data) for s in bank}, {1000})   # 0,25 s à 8 kHz
        for s in bank:
            p = os.path.join(self.tmp, "B_%s_ecoute.wav" % s.name)
            with wave.open(p) as w:
                self.assertEqual(w.getframerate(), 8000)
                self.assertEqual(w.getnframes(), 2000)

    def test_cli_names_and_size_warning(self):
        src = os.path.join(self.tmp, "x.wav")
        wav2smp.write_wav(src, sine(200, 1.0, rate=8000, amp=0.8), 8000)
        out = os.path.join(self.tmp, "N.SMP")
        wav2smp.main([src, "--names", "ZAP", "--no-preview", "-o", out])
        raw = read(out)
        self.assertEqual(wav2smp.parse_bank(raw)[0].name, "ZAP")
        msgs = []
        wav2smp.check_sizes(raw, msgs.append)            # 4000 octets : < 4 Ko
        self.assertEqual(msgs, [])
        big = wav2smp.build_bank([wav2smp.Sample("A", bytes(16384), 125),
                                  wav2smp.Sample("B", bytes(100), 125)])
        wav2smp.check_sizes(big, msgs.append)
        self.assertIn("16 Ko", msgs[0])

    def test_cli_module_entry(self):
        """python -m cpc_dsk.seq16.wav2smp --info : la ligne de commande
        marche depuis le paquet."""
        import subprocess
        import sys
        path = os.path.join(self.tmp, "DRUMS.SMP")
        with open(path, "wb") as f:
            f.write(drums_bank())
        root = os.path.join(HERE, "..")
        r = subprocess.run([sys.executable, "-m", "cpc_dsk.seq16.wav2smp", "--info", path],
                           cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4 samples", r.stdout)


class TestCurves(unittest.TestCase):
    def test_curve_tables(self):
        t = wav2smp.CURVE_TABLES
        self.assertEqual(len(t), 5)
        self.assertEqual(t[wav2smp.CURVE_LOG], list(range(16)))     # fidèle
        for row in t:
            self.assertEqual(len(row), 16)
            self.assertTrue(all(0 <= v <= 15 for v in row))
        self.assertEqual(t[4][wav2smp.REST], wav2smp.REST)          # repos fixe

    def test_render_uses_curve(self):
        codes = [12, 15, 0]
        self.assertNotEqual(wav2smp.render(codes, curve=0), wav2smp.render(codes, curve=1))


class TestFactoryBank(unittest.TestCase):
    def test_drums_bank(self):
        """La banque d'usine (sur test_disks/seq16.dsk) : 4 sons, < 4 Ko,
        < 150 ms chacun."""
        raw = drums_bank()
        bank = wav2smp.parse_bank(raw)
        self.assertEqual([s.name for s in bank], ["KICK", "SNARE", "HAT", "CLAP"])
        self.assertLess(len(raw), wav2smp.BANK_MAX_464)
        for s in bank:
            self.assertLessEqual(s.seconds, 0.150 + 1e-9, s.name)

    def test_rebuild_identical(self):
        """parse_bank puis build_bank redonne les mêmes octets (les octets
        produits ne changent pas avec l'intégration)."""
        raw = drums_bank()
        self.assertEqual(wav2smp.build_bank(wav2smp.parse_bank(raw)), raw)


# ====================================================================== #
# dskio (ancien amsdsk) : écrit par cpc_dsk.core.amsdos
# ====================================================================== #
class TestDskio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dsk = os.path.join(self.tmp, "t.dsk")
        shutil.copy(SEQ16_DSK, self.dsk)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_add_and_read_back(self):
        before = dskio.read_file(self.dsk, "SEQ16.BIN")
        data = bytes(random.Random(1).randrange(256) for _ in range(20000))
        dskio.add_file(self.dsk, "BIG.SMP", data)              # 2 extensions
        self.assertEqual(dskio.read_file(self.dsk, "BIG.SMP"), data)
        self.assertEqual(dskio.read_file(self.dsk, "SEQ16.BIN"), before)
        dskio.add_file(self.dsk, "BIG.SMP", b"court")          # remplace
        self.assertEqual(dskio.read_file(self.dsk, "BIG.SMP"), b"court")
        files = dskio.list_files(self.dsk)
        self.assertIn("BIG.SMP", files)
        self.assertIn("SEQ16.BIN", files)

    def test_header_checksum_and_load_addr(self):
        dskio.add_file(self.dsk, "DRUMS.SMP", b"\x01\x02\x03")
        raw = dskio.read_file(self.dsk, "DRUMS.SMP", keep_header=True)
        h = raw[:128]
        self.assertEqual(h[1:12], b"DRUMS   SMP")
        self.assertEqual(h[18], 2)                              # binaire
        self.assertEqual(struct.unpack("<H", h[21:23])[0], 0)  # chargement en 0
        self.assertEqual(struct.unpack("<H", h[67:69])[0], sum(h[:67]) & 0xFFFF)
        f = AmsdosFilesystem(ADFDisk.load(self.dsk)).find("DRUMS.SMP")
        self.assertTrue(f.has_header)
        self.assertEqual((f.load_addr, f.length), (0, 3))

    def test_in_memory_disk(self):
        """ADFDisk chargé : modifié en mémoire, fichier non touché ; en cas
        d'erreur (disquette pleine), la disquette reste intacte."""
        disk = ADFDisk.load(self.dsk)
        file_before = read(self.dsk)
        dskio.add_file(disk, "MEM.SMP", b"abc")
        self.assertEqual(read(self.dsk), file_before)
        self.assertEqual(dskio.read_file(disk, "MEM.SMP"), b"abc")
        snapshot = bytes(disk._raw)
        with self.assertRaises(ValueError):                     # trop gros
            dskio.add_file(disk, "MEM.SMP", bytes(400 * 1024))
        self.assertEqual(bytes(disk._raw), snapshot)            # MEM.SMP toujours là

    def test_cli_dsk(self):
        src = os.path.join(self.tmp, "x.wav")
        wav2smp.write_wav(src, sine(200, 0.1, rate=8000, amp=0.8), 8000)
        out = os.path.join(self.tmp, "TEST.SMP")
        wav2smp.main([src, "--no-preview", "-o", out, "--dsk", self.dsk])
        self.assertEqual(dskio.read_file(self.dsk, "TEST.SMP"), read(out))

    def test_non_data_refused(self):
        bad = os.path.join(self.tmp, "x.dsk")
        with open(bad, "wb") as f:
            f.write(b"rien")
        with self.assertRaises(ValueError):
            dskio.list_files(bad)
        cpm = os.path.join(HERE, "..", "test_disks", "cpm22.dsk")    # format SYSTEM
        with self.assertRaises(ValueError):
            dskio.list_files(cpm)


# ====================================================================== #
# smp_model
# ====================================================================== #
class ModelBase(unittest.TestCase):
    """Dossier temporaire avec deux WAV de synthèse."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wav = os.path.join(self.tmp, "kick drum.wav")      # nom à nettoyer
        # silence + sinus + silence : pour vérifier --trim
        wav2smp.write_wav(self.wav, [0.0] * 2000 + sine(220, 0.4) + [0.0] * 3000, 22050)
        self.wav2 = os.path.join(self.tmp, "boucle.wav")
        wav2smp.write_wav(self.wav2, sine(110, 1.0, rate=16000), 16000)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def cli_bank(self, *args):
        """Banque produite par la ligne de commande wav2smp (référence)."""
        out = os.path.join(self.tmp, "CLI.SMP")
        wav2smp.main(list(args) + ["--no-preview", "-o", out])
        return read(out)


class TestModel(ModelBase):
    def test_add_settings_build_parse(self):
        """WAV ajouté, réglages changés, banque relue : noms, code, drapeaux, taille."""
        m = BankModel()
        i = m.add_wav(self.wav)
        self.assertEqual(m.items[i].name, "KICKDR")             # clean_name, 6 car.
        self.assertEqual(m.items[i].code, 125)                  # 8 000 Hz par défaut
        m.update(i, name="bd 1", rate=6250, bits=3, decim=2, curve=2,
                 drive=2.0, trim=True, dither="noise")
        j = m.add_wav(self.wav2, name="loop")
        m.update(j, code=100, curve=0)
        raw = m.build()
        bank = wav2smp.parse_bank(raw)
        self.assertEqual([s.name for s in bank], ["BD1", "LOOP"])
        a, b = bank
        self.assertEqual(a.code, 160)                           # 1 000 000 / 6250
        self.assertEqual((a.decim, a.bits), (2, 3))
        self.assertEqual(a.flags, 2 << 4)                       # courbe saturée
        self.assertEqual(a.loop, wav2smp.NO_LOOP)
        self.assertTrue(all(c & 1 == 0 for c in wav2smp.unpack(a.data)))  # 3 bits
        self.assertAlmostEqual(len(a.data), 1250, delta=2)      # trim : 0,4 s à 6 250 Hz
        self.assertEqual((b.code, b.flags, b.bits, b.decim), (100, 0, 4, 1))
        self.assertEqual(len(b.data), 5000)                     # 1 s à 10 kHz
        self.assertEqual(wav2smp.data_size(raw), len(a.data) + len(b.data))
        self.assertEqual(m.used_bytes(), len(a.data) + len(b.data))
        self.assertTrue(m.fits())

    def test_same_bytes_as_cli(self):
        """Mêmes réglages -> banque identique à celle de wav2smp (4 bits)."""
        m = BankModel()
        m.add_wav(self.wav, rate=6250, drive=1.5, trim=True, clean=True,
                  dither="noise", decim=3)
        self.assertEqual(m.build(), self.cli_bank(
            self.wav, "--rate", "6250", "--drive", "1.5", "--trim", "--clean",
            "--dither", "noise", "--decim", "3"))

    def test_bits_written_in_entry(self):
        """--bits : mêmes données que wav2smp, mais la fiche dit aussi les bits."""
        m = BankModel()
        m.add_wav(self.wav, bits=2)
        raw, cli = m.build(), self.cli_bank(self.wav, "--bits", "2")
        self.assertEqual(wav2smp.parse_bank(raw)[0].data, wav2smp.parse_bank(cli)[0].data)
        self.assertEqual(raw[16 + 15] >> 3 & 3, 2)              # 2 bits dans la fiche
        self.assertEqual(cli[16 + 15] >> 3 & 3, 0)              # wav2smp : « 4 bits »
        self.assertEqual(raw[:31] + raw[32:], cli[:31] + cli[32:])  # seul écart

    def test_slices_like_cli(self):
        """Découpage en 4 : mêmes noms et mêmes données que --slice 4."""
        m = BankModel()
        m.add_wav(self.wav2)
        first = m.set_slices(0, 4)
        self.assertEqual(first, 0)
        self.assertEqual([it.name for it in m.items], ["BOUC00", "BOUC01", "BOUC02", "BOUC03"])
        self.assertEqual(m.build(), self.cli_bank(self.wav2, "--slice", "4"))
        m.set_slices(2, 1)                                      # regroupe
        self.assertEqual([it.name for it in m.items], ["BOUCLE"])
        with self.assertRaises(BankError):
            m.set_slices(0, 17)

    def test_header_only_change_keeps_data(self):
        """Décimation et courbe ne reconvertissent pas ; la fréquence si."""
        m = BankModel()
        m.add_wav(self.wav)
        data = m.items[0].data
        m.update(0, decim=8, curve=4)
        self.assertIs(m.items[0].data, data)
        m.update(0, rate=4000)
        self.assertEqual(m.items[0].code, 250)
        self.assertLess(len(m.items[0].data), len(data))

    def test_reopened_bank_is_header_only(self):
        """Banque relue : pas de WAV ; seuls les réglages de fiche bougent."""
        src = BankModel()
        src.add_wav(self.wav, bits=2)
        path = os.path.join(self.tmp, "A.SMP")
        src.save(path)
        m = BankModel()
        m.open_bank(path)
        it = m.items[0]
        self.assertFalse(it.has_source)
        self.assertIsNone(m.original(0))
        self.assertIsNone(m.original_wav(0))
        self.assertEqual(it.bits, 2)
        data = it.data
        m.update(0, name="neuf", code=200, bits=4, decim=6, curve=3,
                 drive=1.0, trim=False)                         # valeurs inchangées : permis
        self.assertEqual(it.data, data)                         # données intactes
        with self.assertRaises(BankError):
            m.update(0, drive=3.0)
        with self.assertRaises(BankError):
            m.set_slices(0, 2)
        back = wav2smp.parse_bank(m.build())[0]
        self.assertEqual((back.name, back.code, back.bits, back.decim, back.flags >> 4),
                         ("NEUF", 200, 4, 6, 3))

    def test_reopen_factory_bank_unchanged(self):
        """Ouvrir puis réécrire DRUMS.SMP donne le même fichier."""
        path = os.path.join(self.tmp, "DRUMS.SMP")
        with open(path, "wb") as f:
            f.write(drums_bank())
        m = BankModel()
        m.open_bank(path)
        self.assertEqual(m.build(), read(path))
        self.assertFalse(m.dirty)

    def test_over_limit_refused(self):
        """Au-delà de 16 320 octets : save et add_to_dsk refusent, rien n'est écrit."""
        long_wav = os.path.join(self.tmp, "long.wav")
        wav2smp.write_wav(long_wav, sine(300, 4.5, rate=8000), 8000)   # 18 000 oct.
        m = BankModel()
        m.add_wav(long_wav)
        self.assertGreater(m.used_bytes(), wav2smp.BANK_MAX_MAIN)
        self.assertFalse(m.fits())
        out = os.path.join(self.tmp, "TROP.SMP")
        with self.assertRaises(BankError) as cm:
            m.save(out)
        self.assertIn("16320", cm.exception.args[0].replace(" ", ""))
        self.assertFalse(os.path.exists(out))
        dsk = os.path.join(self.tmp, "t.dsk")
        shutil.copy(SEQ16_DSK, dsk)
        before = read(dsk)
        with self.assertRaises(BankError):
            m.add_to_dsk(dsk, "TROP.SMP")
        self.assertEqual(read(dsk), before)
        m.update(0, rate=10000)                                 # 4,5 s à 10 kHz : encore trop
        self.assertFalse(m.fits())
        m.update(0, rate=4000)                                  # 9 000 octets : tient
        self.assertTrue(m.fits())
        m.save(out)
        self.assertTrue(os.path.exists(out))

    def test_limits_and_errors(self):
        """16 samples au plus, banque vide refusée, réglages invalides refusés."""
        m = BankModel()
        with self.assertRaises(BankError):
            m.build()
        self.assertEqual(m.used_bytes(), 0)
        for _ in range(16):
            m.add_wav(self.wav)
        with self.assertRaises(BankError):
            m.add_wav(self.wav)
        self.assertEqual(len(m), 16)
        for bad in (dict(bits=5), dict(decim=5), dict(curve=9), dict(code=61),
                    dict(rate=20000), dict(dither="x"), dict(volume=3)):
            with self.assertRaises(BankError, msg=bad):
                m.update(0, **bad)
        self.assertEqual(m.items[0].code, 125)                  # rien n'a bougé
        with self.assertRaises(BankError):
            m.add_wav(os.path.join(self.tmp, "absent.wav"))
        notsmp = os.path.join(self.tmp, "x.smp")
        with open(notsmp, "wb") as f:
            f.write(b"pas une banque")
        with self.assertRaises(BankError):
            m.open_bank(notsmp)

    def test_move_remove(self):
        m = BankModel()
        m.add_wav(self.wav, name="A")
        m.add_wav(self.wav, name="B")
        m.add_wav(self.wav, name="C")
        self.assertEqual(m.move(2, -1), 1)
        self.assertEqual([it.name for it in m.items], ["A", "C", "B"])
        self.assertEqual(m.move(0, -1), 0)                      # déjà en tête
        m.remove(0)
        self.assertEqual([it.name for it in m.items], ["C", "B"])

    def test_preview_wavs(self):
        """WAV d'écoute en mémoire : bonne fréquence, bonne longueur."""
        m = BankModel()
        m.add_wav(self.wav, rate=8000)
        with wave.open(io.BytesIO(m.rendered_wav(0))) as w:
            self.assertEqual(w.getframerate(), 8000)
            self.assertEqual(w.getnframes(), 2 * len(m.items[0].data))
        with wave.open(io.BytesIO(m.original_wav(0))) as w:
            self.assertEqual(w.getframerate(), 22050)
        sig, rate = m.rendered(0)
        codes = wav2smp.unpack(m.items[0].data)
        self.assertEqual(sig, wav2smp.render(codes, 1, 4, wav2smp.CURVE_LOG))

    def test_dsk_name(self):
        self.assertEqual(smp_model.dsk_name("/x/ma banque.smp"), "MABANQUE.SMP")
        self.assertEqual(smp_model.dsk_name("TRES_LONG_NOM.SMP"), "TRESLONG.SMP")
        self.assertEqual(smp_model.dsk_name("voix"), "VOIX.SMP")
        self.assertEqual(smp_model.dsk_name("é.smp"), "BANQUE.SMP")

    def test_error_messages_i18n(self):
        """BankError : texte français d'origine dans str(e), texte de la
        langue courante dans e.localized()."""
        m = BankModel()
        m.add_wav(self.wav)
        with self.assertRaises(BankError) as cm:
            m.update(0, rate=20000)
        e = cm.exception
        self.assertEqual(str(e), "La fréquence va de 4 000 à 16 000 Hz.")
        try:
            set_language("en")
            self.assertEqual(e.localized(), "The frequency ranges from 4,000 to 16,000 Hz.")
            set_language("es")
            self.assertIn("4.000", e.localized())
        finally:
            set_language("fr")
        self.assertEqual(e.localized(), str(e))
        self.assertEqual(str(BankError("texte libre")), "texte libre")
        with self.assertRaises(BankError) as cm:
            m.update(0, code=61)
        self.assertEqual(str(cm.exception), "La période va de 62 à 250 NOP.")


class TestModelDsk(ModelBase):
    def setUp(self):
        super().setUp()
        self.dsk = os.path.join(self.tmp, "copie.dsk")
        shutil.copy(SEQ16_DSK, self.dsk)
        self.real_before = read(SEQ16_DSK)

    def tearDown(self):
        # La disquette de référence ne doit jamais bouger
        self.assertEqual(read(SEQ16_DSK), self.real_before)
        super().tearDown()

    def test_add_to_copy(self):
        """Ajout puis remplacement sur une copie de seq16.dsk."""
        m = BankModel()
        m.add_wav(self.wav)
        name = smp_model.dsk_name("mes sons.smp")
        self.assertFalse(m.dsk_has(self.dsk, name))
        self.assertEqual(m.add_to_dsk(self.dsk, name), "MESSONS.SMP")
        self.assertTrue(m.dsk_has(self.dsk, name))
        self.assertEqual(dskio.read_file(self.dsk, name), m.build())
        m.update(0, rate=5000)                                  # remplace
        m.add_to_dsk(self.dsk, name)
        self.assertEqual(dskio.read_file(self.dsk, name), m.build())
        files = dskio.list_files(self.dsk)
        self.assertEqual(list(files).count("MESSONS.SMP"), 1)
        self.assertIn("SEQ16.BIN", files)
        self.assertEqual(dskio.read_file(self.dsk, "SEQ16.BIN"),
                         dskio.read_file(SEQ16_DSK, "SEQ16.BIN"))
        h = dskio.read_file(self.dsk, name, keep_header=True)[:128]
        self.assertEqual(struct.unpack("<H", h[67:69])[0], sum(h[:67]) & 0xFFFF)

    def test_add_to_loaded_disk(self):
        """Disquette chargée (comme dans l'onglet Disquette) : écrite en mémoire."""
        disk = new_data_disk()
        m = BankModel()
        m.add_wav(self.wav)
        self.assertFalse(m.dsk_has(disk, "A.SMP"))
        m.add_to_dsk(disk, "a.smp")
        self.assertTrue(m.dsk_has(disk, "A.SMP"))
        self.assertEqual(AmsdosFilesystem(disk).read_file("A.SMP"), m.build())

    def test_bad_disk(self):
        bad = os.path.join(self.tmp, "x.dsk")
        with open(bad, "wb") as f:
            f.write(b"rien")
        m = BankModel()
        m.add_wav(self.wav)
        with self.assertRaises(BankError):
            m.dsk_has(bad, "A.SMP")
        with self.assertRaises(BankError):
            m.add_to_dsk(bad, "A.SMP")


def setUpModule():
    set_language("fr")


if __name__ == "__main__":
    unittest.main()
