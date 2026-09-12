#!/usr/bin/env bash
# Best-effort installer for catlock. Reviews before it acts, asks before
# anything requiring sudo, and never enables/starts the service for you -
# you do that yourself once you've edited config.yaml and tested by hand.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_RULE_SRC="$INSTALL_DIR/udev/99-catlock-uinput.rules"
UDEV_RULE_DST="/etc/udev/rules.d/99-catlock-uinput.rules"
SERVICE_SRC="$INSTALL_DIR/systemd/catlock.service"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_DST="$SERVICE_DIR/catlock.service"

echo "catlock install dir: $INSTALL_DIR"
echo

echo "== Step 1: Python dependencies =="
if python3 -c "import evdev, yaml" >/dev/null 2>&1; then
    echo "evdev and PyYAML already importable."
elif command -v pacman >/dev/null 2>&1; then
    echo "Arch/Omarchy detected: python-evdev and python-yaml are both in the"
    echo "official 'extra' repo, which avoids pip/PEP-668 entirely."
    read -rp "Install with 'sudo pacman -S python-evdev python-yaml'? [y/N] " ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
        sudo pacman -S --needed python-evdev python-yaml
    else
        echo "Skipped. Install python-evdev and python-yaml manually before running catlock.py."
    fi
else
    echo "Non-Arch system: recommend a venv rather than system pip, e.g.:"
    echo "  python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
    echo "  then run catlock.py with ./.venv/bin/python catlock.py ..."
    read -rp "Try 'pip install --user -r requirements.txt' instead? [y/N] " ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
        python3 -m pip install --user -r "$INSTALL_DIR/requirements.txt"
    else
        echo "Skipped."
    fi
fi
echo

echo "== Step 2: config.yaml =="
if [[ ! -f "$INSTALL_DIR/config.yaml" ]]; then
    cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
    echo "Created config.yaml from config.example.yaml."
    echo "Run: python3 $INSTALL_DIR/catlock.py --identify"
    echo "...type on your target keyboard when it says to, then paste the"
    echo "device_path (or device_name) it prints into config.yaml."
else
    echo "config.yaml already exists, leaving it alone."
fi
echo

echo "== Step 3: uinput permissions (needs sudo) =="
echo "This installs a udev rule so your user can create a virtual keyboard"
echo "without running catlock as root: $UDEV_RULE_DST"
read -rp "Install udev rule now? [y/N] " ans
if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
    sudo cp "$UDEV_RULE_SRC" "$UDEV_RULE_DST"
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "Installed. Reloaded udev rules."
else
    echo "Skipped. See README 'Permissions' section to do this manually."
fi

if ! id -nG "$USER" | grep -qw input; then
    echo
    read -rp "Add $USER to the 'input' group now (needed for /dev/input access)? [y/N] " ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
        sudo usermod -aG input "$USER"
        echo "Added. You must log out and back in (or reboot) for this to take effect."
    else
        echo "Skipped. Add yourself to 'input' manually: sudo usermod -aG input \$USER"
    fi
fi
echo

echo "== Step 4: systemd user service =="
read -rp "Install (but not enable/start) the systemd user service? [y/N] " ans
if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
    mkdir -p "$SERVICE_DIR"
    sed "s#__INSTALL_DIR__#$INSTALL_DIR#g" "$SERVICE_SRC" > "$SERVICE_DST"
    systemctl --user daemon-reload
    echo "Installed to $SERVICE_DST."
    echo
    echo "Next, by hand, once config.yaml is correct and you've tested with:"
    echo "  python3 $INSTALL_DIR/catlock.py --config $INSTALL_DIR/config.yaml -v"
    echo "enable and start it with:"
    echo "  systemctl --user enable --now catlock.service"
else
    echo "Skipped. See README 'Running as a service' section."
fi
echo
echo "Done. Read the README's 'Before you trust this daemon' section before"
echo "relying on this - test the unlock combo thoroughly first, and keep an"
echo "external keyboard or SSH access handy until you have."
