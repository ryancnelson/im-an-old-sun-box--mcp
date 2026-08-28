#!/usr/bin/bash

set -euo pipefail
umask 022

WHEEL=${1:?usage: install.sh PATH_TO_WHEEL}
PREFIX=/opt/old-sun-console

[[ -f "$WHEEL" ]] || { echo "wheel not found: $WHEEL" >&2; exit 1; }
mkdir -p "$PREFIX/bin" /etc/old-sun-console
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade pip
"$PREFIX/venv/bin/pip" install "$WHEEL"
cp "$(dirname "$0")/start-console" "$PREFIX/bin/start-console"
chmod 0755 "$PREFIX/bin/start-console"

echo "Installed application under $PREFIX."
echo "Next: install /etc/old-sun-console/console.env mode 0600, import the SMF manifest, and enable the service."
