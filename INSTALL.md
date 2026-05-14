# CodeHub — Installation Guide

CodeHub is a session manager for code editors (VS Code, Cursor, Zed, etc.) with embedded window support on Linux/X11.

---

## 🚀 Quick Install (Debian/Ubuntu/Mint)

If you have the `.deb` file, this is the easiest way to install CodeHub with all its dependencies:

```sh
sudo apt update
sudo apt install ./codehub_0.1.1_amd64.deb
```

After installation, you can launch **CodeHub** from your application menu.

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

## Step 2 — Install CodeHub from the wheel file

You will receive a file named `codehub-0.1.1-py3-none-any.whl`. Run:

```sh
pip install --user codehub-0.1.1-py3-none-any.whl
```

> If your system blocks pip (externally-managed environment), add `--break-system-packages`:
> ```sh
> pip install --user --break-system-packages codehub-0.1.1-py3-none-any.whl
> ```

---

## Step 3 — Make sure `~/.local/bin` is on your PATH

After a user install, the `codehub` command lands in `~/.local/bin`. Check:

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
codehub
```

Or alternatively:

```sh
python3 -m codehub
```

---

## Optional — Add a desktop menu entry

To make CodeHub appear in your application menu (e.g. in the Start Menu / Activities):

```sh
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/codehub.desktop << 'EOF'
[Desktop Entry]
Name=CodeHub
Comment=Session manager for code editors
Exec=codehub
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
pip uninstall codehub
```

---

## Troubleshooting

**`codehub: command not found`**
→ `~/.local/bin` is not on your PATH. See Step 3.

**`ModuleNotFoundError: No module named 'gi'`**
→ GTK3 system libraries are missing. Repeat Step 1.

**App opens but windows do not embed**
→ You may be running Wayland. CodeHub requires Xorg (X11). Log out and choose an Xorg session at the login screen.

**`error: externally-managed-environment` from pip**
→ Add `--break-system-packages` to the pip command (see Step 2 note).

---

## For the maintainer — rebuilding the package

> This section is only relevant if you have the source code and want to rebuild.

```sh
# One-time: install the build tool
pip install build --break-system-packages

# Build (creates dist/codehub-0.1.1-py3-none-any.whl)
python3 -m build

# Or use the Makefile shortcut
make build
```

The file to share with others is `dist/codehub-0.1.1-py3-none-any.whl`.  
The `dist/` and `build/` directories are excluded from git via `.gitignore`.
