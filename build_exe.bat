@echo off
rem ============================================================
rem  Construit l'executable Windows de l'editeur de disquettes
rem  CPC + Gotek (cpc-dsk-gui.exe) depuis un PC Windows.
rem
rem  Pre-requis : Python 3.10+ (avec tkinter) depuis python.org
rem  L'executable est genere dans dist\
rem  L'onglet Samples SEQ-16 (cpc_dsk\seq16) est importe a la
rem  demande : --hidden-import le force dans l'executable. Il n'a pas
rem  de fichier de donnees en plus (polices = cpc_dsk\fonts).
rem  Les fichiers HxC (firmware HxC2001, proprietaires) ne sont PAS
rem  inclus : l'utilisateur les place dans un dossier HXC\ a cote de
rem  l'executable.
rem ============================================================

python -m pip install --upgrade pyinstaller
python -m PyInstaller --onefile --windowed --clean --name cpc-dsk-gui run_gui.py --hidden-import cpc_dsk.seq16.smp_gui --add-data "cpc_dsk\fonts;cpc_dsk/fonts" --add-data "cpc_dsk\data;cpc_dsk/data" --add-data "cpc_dsk\icon.ico;cpc_dsk"

if exist dist\cpc-dsk-gui.exe (
    echo.
    echo OK : executable genere dans dist\cpc-dsk-gui.exe
    echo Copiez-le sur le bureau (ou ailleurs) pour l'executer.
) else (
    echo.
    echo ECHEC : la generation a echoue, voyez le journal plus haut.
)
pause
