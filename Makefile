.PHONY: build install install-user dev clean desktop-install

# ── Build ────────────────────────────────────────────────────────────────────
# Requires: pip install build
# Produces: dist/coder3-*.whl  and  dist/coder3-*.tar.gz
build:
	python -m build

# ── Install ──────────────────────────────────────────────────────────────────
# Install for current user only (no sudo needed).
# After this, the 'coder3' command is available in ~/.local/bin/
install-user: build
	pip install --user --force-reinstall dist/*.whl

# Install system-wide (requires sudo).
install: build
	sudo pip install --force-reinstall dist/*.whl

# Install in editable/dev mode — file changes take effect immediately.
dev:
	pip install --user -e .

# ── Desktop integration ───────────────────────────────────────────────────────
# Copy the .desktop entry so Coder3 appears in the application menu.
desktop-install:
	@mkdir -p ~/.local/share/applications
	@printf '[Desktop Entry]\nName=Coder3\nComment=Session manager for code editors\nExec=coder3\nIcon=utilities-terminal\nTerminal=false\nType=Application\nCategories=Development;\n' \
		> ~/.local/share/applications/coder3.desktop
	@echo "Desktop entry installed → ~/.local/share/applications/coder3.desktop"
	@update-desktop-database ~/.local/share/applications 2>/dev/null || true

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf dist/ build/ *.egg-info coder3/*.egg-info
