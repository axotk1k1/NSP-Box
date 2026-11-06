# Running on Arch Linux (unofficial fork)

```bash
sudo pacman -S --needed python tk git
git clone git@github.com:axotk1k1/NSP-Box.git && cd NSP-Box
./run-linux.sh                       # GUI
./run-linux.sh --package DIR --output out.nsp   # CLI
```

Tests: `.venv/bin/python test_engine.py` (also `test_nsp`, `test_dlc`, `test_nup`, `test_emulator_patch`, ...).
`test_ui.py` needs a desktop session and Windows shell-drop features.

Notes
- Packaging (NSP/NUP/DLC) is pure Python and works on Linux. Folder drag-and-drop is Windows-only; use Browse or paste a path.
- The **Emulator patch** feature targets Windows x64 `.exe` builds only.
- This fork makes the output commit no-overwrite on POSIX (hard link instead of `rename`).
