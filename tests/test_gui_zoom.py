"""Tests de régression du zoom GUI (nécessitent un affichage disponible).

Sans affichage (CI headless), les tests sont ignorés.
"""

import tkinter as tk

import pytest


def _display_available() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


HAS_DISPLAY = _display_available()


@pytest.mark.skipif(not HAS_DISPLAY, reason="pas d'affichage disponible")
def test_zoom_changes_font_sizes_and_resets():
    """Le zoom module les polices ; le reset restaure l'état initial."""
    from cpc_dsk.gui import DskEditorApp

    root = tk.Tk()
    app = DskEditorApp(root)
    root.update_idletasks()
    root.update()
    assert hasattr(app, "zoom_lbl"), "contrôle de zoom absent de l'en-tête"
    assert app._zoomables, "aucun widget zoomable enregistré"
    base_body = app.f_body.cget("size")
    base_bw = app._zoomables[0]._bw

    # Dézoom (3 × -10 % → 70 %) : la police de corps (non quantifiée) diminue.
    for _ in range(3):
        app.zoom_out()
    root.update()
    assert app.zoom == pytest.approx(0.7)
    assert abs(app.f_body.cget("size")) < abs(base_body)
    assert app.zoom_lbl.cget("text").startswith("70")

    # Réinitialisation : les valeurs de base sont restaurées.
    app.zoom_reset()
    root.update()
    assert app.f_body.cget("size") == base_body
    assert app._zoomables[0]._bw == base_bw

    # Zoom-in (3 × +10 % → 130 %) : la police de corps augmente.
    for _ in range(3):
        app.zoom_in()
    root.update()
    assert abs(app.f_body.cget("size")) > abs(base_body)
    root.destroy()


@pytest.mark.skipif(not HAS_DISPLAY, reason="pas d'affichage disponible")
def test_zoom_clamped_to_bounds():
    """Le facteur de zoom reste borné dans [0.5, 2.0]."""
    from cpc_dsk.gui import DskEditorApp

    root = tk.Tk()
    app = DskEditorApp(root)
    root.update()
    for _ in range(50):
        app.zoom_out()
    assert app.zoom == pytest.approx(0.5)
    for _ in range(50):
        app.zoom_in()
    assert app.zoom == pytest.approx(2.0)
    root.destroy()
