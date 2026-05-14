#!/bin/bash
set -e

# Configuration
APP_NAME="codehub"
VERSION="0.1.4"
ARCH="amd64"
PKG_NAME="${APP_NAME}_${VERSION}_${ARCH}"
# Use /tmp for building to ensure correct Unix permissions (required for dpkg-deb)
BUILD_DIR="/tmp/codehub_deb_build"
WORKSPACE_DIR=$(pwd)

echo "---------------------------------------------------"
echo "Building Debian package: ${PKG_NAME}.deb"
echo "Build Directory: $BUILD_DIR"
echo "Workspace:       $WORKSPACE_DIR"
echo "---------------------------------------------------"

# 1. Clean up
rm -rf "$BUILD_DIR"
rm -f "$WORKSPACE_DIR/${PKG_NAME}.deb"

# 2. Create directory structure
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/$APP_NAME/$APP_NAME"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"

# 3. Create Control file
cat > "$BUILD_DIR/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, python3-xlib, python3-psutil
Replaces: coder3
Conflicts: coder3
Maintainer: Ahmed Issa <ahmed@example.com>
Description: CodeHub Session Manager
 A professional session manager for code editors (VS Code, Cursor, Zed)
 with embedded window support for Linux/X11.
 Designed for Ubuntu Cinnamon and other X11-based desktops.
 (Formerly known as Coder3)
EOF

# 4. Create postinst script
cat > "$BUILD_DIR/DEBIAN/postinst" <<EOF
#!/bin/bash
set -e
update-desktop-database /usr/share/applications
gtk-update-icon-cache /usr/share/icons/hicolor
echo "---------------------------------------------------"
echo " CodeHub has been installed successfully!"
echo " You can find it in your application menu."
echo "---------------------------------------------------"
EOF

# 5. Create Launcher script
cat > "$BUILD_DIR/usr/bin/$APP_NAME" <<EOF
#!/bin/bash
# Add the app directory to PYTHONPATH so imports work correctly
export PYTHONPATH="/usr/share/$APP_NAME:\$PYTHONPATH"
exec python3 /usr/share/$APP_NAME/run.py "\$@"
EOF

# 6. Copy source code
echo "Copying source files..."
cp -r "$WORKSPACE_DIR/codehub/"* "$BUILD_DIR/usr/share/$APP_NAME/$APP_NAME/"
cp "$WORKSPACE_DIR/run.py" "$BUILD_DIR/usr/share/$APP_NAME/"

# Remove pycache and other non-essential files
find "$BUILD_DIR/usr/share/$APP_NAME" -type d -name "__pycache__" -exec rm -rf {} +
find "$BUILD_DIR/usr/share/$APP_NAME" -name "*.pyc" -delete

# 7. Create Desktop entry
cat > "$BUILD_DIR/usr/share/applications/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Name=CodeHub
Comment=Session manager for code editors
Exec=$APP_NAME
Icon=$APP_NAME
Terminal=false
Type=Application
Categories=Development;
Keywords=Editor;Session;Manager;VSCode;Cursor;
EOF

# 8. Copy icon
ICON_SRC="$WORKSPACE_DIR/coder3_0.1.0_amd64/usr/share/icons/hicolor/256x256/apps/coder3.png"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps/"
    echo "Icon added to package."
else
    echo "Warning: Icon not found at $ICON_SRC"
fi

# 9. Set permissions (Crucial for dpkg-deb)
echo "Setting permissions..."
find "$BUILD_DIR" -type d -exec chmod 755 {} +
find "$BUILD_DIR" -type f -exec chmod 644 {} +
chmod 755 "$BUILD_DIR/DEBIAN/postinst"
chmod 755 "$BUILD_DIR/usr/bin/$APP_NAME"
chmod 755 "$BUILD_DIR/usr/share/$APP_NAME/run.py"

# 10. Build the package
echo "Generating .deb file..."
dpkg-deb --build "$BUILD_DIR" "$WORKSPACE_DIR/${PKG_NAME}.deb"

# 11. Cleanup build dir
rm -rf "$BUILD_DIR"

echo "---------------------------------------------------"
echo " SUCCESS: ${PKG_NAME}.deb is ready!"
echo " Location: $WORKSPACE_DIR/${PKG_NAME}.deb"
echo " Install it with: sudo apt install ./${PKG_NAME}.deb"
echo "---------------------------------------------------"
