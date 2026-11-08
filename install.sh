#!/usr/bin/env bash
# Instala dependências, regra udev, atalho no menu e (opcional) início automático.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "==> Pacotes do sistema (PySide6, GStreamer/PipeWire, dbus-next)"
sudo dnf install -y python3-pyside6 python3-gobject gstreamer1-plugins-good pipewire-gstreamer python3-dbus-next gcc python3-devel

echo "==> Ambiente virtual"
[ -d .venv ] || python3 -m venv --system-site-packages .venv
.venv/bin/pip install -q -r requirements.txt

echo "==> Regra udev (acesso ao teclado sem root)"
sudo install -m 644 packaging/70-surara.rules /etc/udev/rules.d/70-surara.rules
sudo udevadm control --reload && sudo udevadm trigger

echo "==> Atalho no menu"
mkdir -p ~/.local/share/applications
sed "s|@BIN@|$DIR/surara-control|" packaging/surara-control.desktop > ~/.local/share/applications/surara-control.desktop

read -rp "Iniciar automaticamente (na bandeja) ao fazer login? [s/N] " r
if [[ "${r,,}" == s* ]]; then
  mkdir -p ~/.config/autostart
  sed "s|@BIN@|$DIR/surara-control --minimized|" packaging/surara-control.desktop > ~/.config/autostart/surara-control.desktop
fi
echo "Pronto. Abra “Surara Control” no menu ou rode ./surara-control"
