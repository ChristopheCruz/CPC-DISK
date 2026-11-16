<div align="center">



```
 ██████╗██████╗  ██████╗    ██████╗ ██╗███████╗██╗  ██╗
██╔════╝██╔══██╗██╔════╝    ██╔══██╗██║██╔════╝██║ ██╔╝
██║     ██████╔╝██║         ██║  ██║██║███████╗█████╔╝
██║     ██╔═══╝ ██║         ██║  ██║██║╚════██║██║═██╗
╚██████╗██║     ╚██████╗    ██████╔╝██║███████║██║  ██╗
 ╚═════╝╚═╝      ╚═════╝    ╚═════╝ ╚═╝╚══════╝╚═╝  ╚═╝
        D I S K   E D I T O R   .DSK  ·  G O T E K  ·  A M S D O S

Ready
█
```

**CPC `.dsk` disk image editor, with USB key preparation for Gotek readers.**
A "CPC screen"-looking interface, in pure Python, with no external dependencies.

<img src="docs/logo.png" width="140" alt="CPC Disk Editor">

![Python](https://img.shields.io/badge/Python-3.8%2B-000080?style=flat-square&labelColor=FFFF00&logo=python&logoColor=000080)
![GUI](https://img.shields.io/badge/GUI-tkinter-000080?style=flat-square&labelColor=00FFFF)
![Dependencies](https://img.shields.io/badge/dependencies-none-000080?style=flat-square&labelColor=00FF00)
![License](https://img.shields.io/badge/license-MIT-000080?style=flat-square&labelColor=FF8000)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-000080?style=flat-square&labelColor=FFDD00&logo=buymeacoffee&logoColor=000000)](https://www.buymeacoffee.com/ChristopheCruz)

[🇬🇧 English](README.md) · [🇫🇷 Français](README.fr.md)

</div>

---

![CPC Disk Editor — Diskette tab](docs/screenshot.png)

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Running](#running)
- [Usage](#usage)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Project structure](#project-structure)
- [Supporting the project](#supporting-the-project)
- [Credits](#credits)
- [License](#license)

## Features

### Diskette tab (`.dsk`)

- **Open, create, and save** disk images in the EXTENDED CPC DSK format (`.adf` files are also accepted).
- **File catalogue** across both layers, **Filer** and **AMSDOS**: name, type, length and load address.
- **Add a local file** onto the diskette: 8.3 name, type (Basic or binary), load address, and choice of write layer (Filer, AMSDOS or both).
- **Extract** a file to the local disk, keeping its extension (`MONPROG BAS` → `monprog.bas`).
- **Delete** a file, with confirmation.
- **Hex dump** of a file or a sector, in three aligned columns: offset, bytes, ASCII.
- **Clickable sector map**: the geometry is read from the image, free sectors (filled with `E5` or `00`) are distinguished from in-use sectors, and those belonging to the selected file are highlighted.

### CP/M 2.2 support

- **Bootable CP/M 2.2 system disks** ("System format", 40 tracks × 9 × 512, sector IDs `&41..&49`): the **New CP/M** button (or `cpc-dsk new x.dsk --cpm`) builds one from a reference image extracted from a real cpm22.dsk — CP/M 2.2 + Amsdos 2.0 (`AMSDOS.COM`, `DISCKIT2.COM`, `LOGO2.COM`, `LOGO2.SUB`), ready to test on a real Gotek.
- **Automatic detection** of CP/M disks: the catalogue, add/extract/delete all operate on the CP/M directory (track 2, Filer-format entries) and the AMSDOS objects, including the "legacy" files of real disks whose content is an AMSDOS object embedded in the allocation.
- Real-disk quirks handled: CP/M character set names (Planetfall), sequential or interleaved sector ID orders (WinAPE-identical track headers on generated disks).

### Gotek tab (USB key)

- **Source list** of `.dsk` / `.adf` images, reorderable with ▲ ▼.
- **Naming pattern** (default `DISK%03d.adf`), subfolder and start index, with a live preview of the resulting names.
- **Generate** the directory to copy onto the Gotek's USB key.
- **Verify** an existing directory.
- **Create a full FAT16 image** of the key (32 MB) with a built-in FAT writer, no external tool needed.
- **Load an existing `.img` image**: list its content, send its diskettes back to the source stack, or extract everything to a folder.

### Interface

- **Amstrad CPC** look: firmware palette (blue, bright yellow, cyan), pixel fonts, 4-px relief buttons, reverse-video selection and a blinking `Ready` cursor.
- **Two monitors**: colour (CTM644) or green (GT65), toggled with F3.
- **Three interface languages**: English, French and Spanish — detected from the system locale, switchable in the window.
- **Drag & drop** from the Windows Explorer.
- **Hi-DPI friendly**: pixel fonts stay crisp at 125 %, 150 % and beyond.

The interface in the other two languages (the banner above is French):

<table>
  <tr>
    <td align="center"><img src="docs/screenshot-en.png" width="49%"></td>
    <td align="center"><img src="docs/screenshot-gotek-en.png" width="49%"></td>
  </tr>
  <tr>
    <td align="center"><em>English — diskette tab</em></td>
    <td align="center"><em>English — Gotek tab</em></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshot-es.png" width="49%"></td>
    <td align="center"><img src="docs/screenshot-gotek-es.png" width="49%"></td>
  </tr>
  <tr>
    <td align="center"><em>Spanish — diskette tab</em></td>
    <td align="center"><em>Spanish — Gotek tab</em></td>
  </tr>
</table>

## Installation

Python 3.8 or newer is all you need. `tkinter` ships with Python on Windows and macOS.

```bash
git clone https://github.com/ChristopheCruz/AmstradCPC.git
cd AmstradCPC
```

On Linux, `tkinter` is sometimes a separate package:

```bash
sudo apt install python3-tk      # Debian / Ubuntu
```

The **Press Start 2P** and **VT323** fonts are included in `cpc_dsk/fonts/`. On Windows they are loaded for the application only — nothing is installed on the system. Elsewhere, or if the folder is missing, the interface automatically falls back to a monospace font. For the pixel look on Linux or macOS, install the two `.ttf` files in your user fonts.

## Running

```bash
python -m cpc_dsk.gui
```

## Usage

### Editing a diskette

1. **Open** a `.dsk` image, or start from a blank one with **New**.
2. Select a file in the catalogue: its content is shown as hex on the right.
3. **Add**, **Extract** or **Delete** files. The diskette is saved after every change.
4. To inspect a specific sector, type `track sector` (e.g. `0 0`) then **Show**, or click directly in the sector map (**Sectors** view, F4).

### Building a CP/M system disk

1. **New CP/M** (or `cpc-dsk new cpm.dsk --cpm`) → a bootable CP/M 2.2 "System format" disk with the Amsdos utilities. `--no-utils` produces a bare system (empty directory).
2. **Add** your programs (CP/M directory layer, or AMSDOS-only objects), then **save**.
3. Copy the image to the Gotek's key (Gotek tab, `DISK001.adf`) and boot it on a real CPC: the BIOS `|CPM` loads the boot sector, the system comes up at `A>` and reads the track-2 directory.
4. Existing CP/M disks (real or home-brew) are detected automatically: open one and the catalogue shows its CP/M files, "legacy" files included (e.g. `RITDEMO.BIN` on cpm22.dsk).

```bash
cpc-dsk list cpm.dsk --source cpm       # CP/M directory
cpc-dsk list cpm.dsk --source amsdos    # AMSDOS objects
cpc-dsk read cpm.dsk PROG.COM --out prog.com
cpc-dsk write cpm.dsk MYPGM.BIN mypgm.bin --load 0x4000
```

### Preparing a key for the Gotek

1. In the **Gotek** tab (F2), **Add** your diskettes, then put them in the desired order with ▲ ▼.
2. Adjust the naming pattern, subfolder and start index if needed. The "→ USB key" column shows the name each image will get.
3. Choose the output directory (the root of the key, for example), then **Generate USB**.
4. For a blank key, **FAT image** instead produces a complete `.img` to write onto the key.

![CPC Disk Editor — Gotek tab](docs/screenshot-gotek.png)

### Drag & drop (Windows)

| What you drop | Active tab | Result |
|---|---|---|
| `.dsk` / `.adf` | Diskette, no disk open | the diskette is opened |
| `.dsk` / `.adf` | Diskette, a disk open | added to the Gotek sources |
| `.dsk` / `.adf` | Gotek | added to the sources |
| any other file | either | added to the open diskette |

## Keyboard shortcuts

| Key | Action |
|---|---|
| <kbd>F1</kbd> / <kbd>F2</kbd> | Diskette / Gotek tab |
| <kbd>F3</kbd> | Colour / green monitor |
| <kbd>F4</kbd> | Files / Sectors view |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Open a diskette |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New diskette |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save |
| <kbd>Del</kbd> | Delete the selected file or source |
| <kbd>Enter</kbd> (sector field) | Show the sector |

## Project structure

```
cpc_dsk/
├── gui.py            tkinter GUI (pixel-art skin)
├── cli.py            command-line interface
├── i18n.py           interface strings (en / fr / es)
├── data/
│   └── cpm22_system.bin   CP/M 2.2 + Amsdos 2.0 reference image (46 880 B)
├── fonts/            Press Start 2P and VT323 (OFL license)
└── core/
    ├── adf.py        disk image reader / writer
    ├── cpcfs.py      Filer and AMSDOS filesystems
    ├── cpm.py        CP/M 2.2 ("System format") filesystem + disk builder
    └── gotek.py      USB key preparation and FAT16 writer
```

## Supporting the project

CPC Disk Editor is free and will stay free. If it saved you a few hours of diskette fiddling, or brought an old 6128 back to life through a Gotek, you can buy me a coffee: it funds time for the next features.

<div align="center">

<a href="https://www.buymeacoffee.com/ChristopheCruz" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="50">
</a>

```
10 PRINT "THANKS !"
20 GOTO 10
```

</div>

A star ⭐ on the repository, a bug report or an idea in the *issues* helps just as much.

## Credits

- **Press Start 2P** by CodeMan38 and **VT323** by Peter Hull, released under the [SIL Open Font License 1.1](https://openfontlicense.org). Their licenses are in `cpc_dsk/fonts/`.
- Amstrad and CPC are trademarks of their respective owners. This project is not affiliated with any of them.

## License

[MIT](LICENSE) — see the `LICENSE` file at the root of the repository.
