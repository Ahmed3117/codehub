.PHONY: build install install-user dev clean desktop-install deb

# ── Debian Package ──────────────────────────────────────────────────────────
deb:
	bash scripts/create_deb.sh

# ── Build ────────────────────────────────────────────────────────────────────
# Requires: pip install build
# Produces: dist/codehub-*.whl  and  dist/codehub-*.tar.gz
build:
	python -m build

# ── Install ──────────────────────────────────────────────────────────────────
# Install for current user only (no sudo needed).
# After this, the 'codehub' command is available in ~/.local/bin/
install-user: build
	pip install --user --force-reinstall dist/*.whl

# Install system-wide (requires sudo).
install: build
	sudo pip install --force-reinstall dist/*.whl

# Install in editable/dev mode — file changes take effect immediately.
dev:
	pip install --user -e .

# ── Desktop integration ───────────────────────────────────────────────────────
# Copy the .desktop entry so CodeHub appears in the application menu.
desktop-install:
	@mkdir -p ~/.local/share/applications
	@printf '[Desktop Entry]\nName=CodeHub\nComment=Session manager for code editors\nExec=codehub\nIcon=utilities-terminal\nTerminal=false\nType=Application\nCategories=Development;\n' \
		> ~/.local/share/applications/codehub.desktop
	@echo "Desktop entry installed → ~/.local/share/applications/codehub.desktop"
	@update-desktop-database ~/.local/share/applications 2>/dev/null || true

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf dist/ build/ *.egg-info codehub/*.egg-info
