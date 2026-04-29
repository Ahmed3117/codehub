# Coder3 — Installation Guide

Coder3 is a session manager for code editors (VS Code, Cursor, Zed, etc.) with embedded window support on Linux/X11.

---

## Requirements

- **Linux** with an **X11** display server (Xorg — not Wayland)
- **Python 3.10 or newer**
- **GTK3 system libraries** (see step 1 below)

---

## Step 1 — Install system dependencies

GTK3 cannot be installed via pip; it must come from your system package manager.

**Debian / Ubuntu / Linux Mint:**
```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
```

**Fedora / RHEL / CentOS:**
```sh
sudo dnf install python3-gobject gtk3
```

**Arch Linux:**
```sh
sudo pacman -S python-gobject gtk3
```

---

## Step 2 — Install Coder3 from the wheel file

You will receive a file named `coder3-0.1.0-py3-none-any.whl`. Run:

```sh
pip install --user coder3-0.1.0-py3-none-any.whl
```

> If your system blocks pip (externally-managed environment), add `--break-system-packages`:
> ```sh
> pip install --user --break-system-packages coder3-0.1.0-py3-none-any.whl
> ```

---

## Step 3 — Make sure `~/.local/bin` is on your PATH

After a user install, the `coder3` command lands in `~/.local/bin`. Check:

```sh
echo $PATH | grep -o "$HOME/.local/bin"
```

If nothing is printed, add this line to your `~/.bashrc` or `~/.zshrc` and restart your terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

---

## Step 4 — Run the app

```sh
coder3
```

Or alternatively:

```sh
python3 -m coder3
```

---

## Optional — Add a desktop menu entry

To make Coder3 appear in your application menu (e.g. in the Start Menu / Activities):

```sh
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/coder3.desktop << 'EOF'
[Desktop Entry]
Name=Coder3
Comment=Session manager for code editors
Exec=coder3
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Development;
EOF
update-desktop-database ~/.local/share/applications
```

---

## Uninstalling

```sh
pip uninstall coder3
```

---

## Troubleshooting

**`coder3: command not found`**
→ `~/.local/bin` is not on your PATH. See Step 3.

**`ModuleNotFoundError: No module named 'gi'`**
→ GTK3 system libraries are missing. Repeat Step 1.

**App opens but windows do not embed**
→ You may be running Wayland. Coder3 requires Xorg (X11). Log out and choose an Xorg session at the login screen.

**`error: externally-managed-environment` from pip**
→ Add `--break-system-packages` to the pip command (see Step 2 note).

---

## For the maintainer — rebuilding the package

> This section is only relevant if you have the source code and want to rebuild.

```sh
# One-time: install the build tool
pip install build --break-system-packages

# Build (creates dist/coder3-0.1.0-py3-none-any.whl)
python3 -m build

# Or use the Makefile shortcut
make build
```

The file to share with others is `dist/coder3-0.1.0-py3-none-any.whl`.  
The `dist/` and `build/` directories are excluded from git via `.gitignore`.
