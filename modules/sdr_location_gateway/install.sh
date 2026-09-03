#!/usr/bin/env bash
# Install SDRTrunk + Xvfb + udev rules for RadioTAK SDR Location Gateway
set -euo pipefail

INSTALL_DIR="${RADIOTAK_INSTALL_DIR:-/opt/radiotak}"
DATA_DIR="${RADIOTAK_DATA_DIR:-/var/lib/radiotak}"
SDR_DIR="$DATA_DIR/sdrtrunk"
ARCH=$(uname -m)

export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq xvfb x11vnc openjdk-17-jre-headless wget unzip \
  libgtk-3-0 libasound2t64 2>/dev/null || apt-get install -y -qq xvfb x11vnc openjdk-17-jre-headless wget unzip libgtk-3-0

mkdir -p "$SDR_DIR"
cp "$INSTALL_DIR/deploy/udev/99-radiotak-sdr.rules" /etc/udev/rules.d/ 2>/dev/null || true
udevadm control --reload-rules 2>/dev/null || true
echo "blacklist dvb_usb_rtl28xxu" > /etc/modprobe.d/radiotak-rtl-blacklist.conf

# Prefer CopIXus patched release; fall back to upstream DSheirer release
TAG="v0.6.1"
ASSET="sdr-trunk-linux-aarch64-${TAG}.zip"
if [[ "$ARCH" == "x86_64" ]]; then
  ASSET="sdr-trunk-linux-x86_64-${TAG}.zip"
fi

DEST="$SDR_DIR/app"
if [[ ! -d "$DEST" ]]; then
  echo "Downloading SDRTrunk $ASSET…"
  URL_FORK="https://github.com/CopIXus/sdrtrunk/releases/download/${TAG}/${ASSET}"
  URL_UP="https://github.com/DSheirer/sdrtrunk/releases/download/${TAG}/${ASSET}"
  TMP=/tmp/sdrtrunk.zip
  if ! wget -q -O "$TMP" "$URL_FORK"; then
    echo "Fork release not found — using upstream"
    wget -q -O "$TMP" "$URL_UP"
  fi
  unzip -q -o "$TMP" -d "$SDR_DIR"
  # Normalize extracted folder name
  EXTRACTED=$(find "$SDR_DIR" -maxdepth 1 -type d -name 'sdr-trunk*' | head -1)
  if [[ -n "$EXTRACTED" && "$EXTRACTED" != "$DEST" ]]; then
    mv "$EXTRACTED" "$DEST"
  fi
  rm -f "$TMP"
fi

# systemd units
cat > /etc/systemd/system/sdrtrunk.service <<EOF
[Unit]
Description=SDRTrunk (RadioTAK) under Xvfb
After=network.target radiotak.service

[Service]
Type=simple
User=radiotak
Group=radiotak
Environment=DISPLAY=:99
Environment=HOME=$DATA_DIR
WorkingDirectory=$DEST
ExecStartPre=/usr/bin/mkdir -p $DATA_DIR/.sdrtrunk
ExecStart=/usr/bin/xvfb-run -a -s "-screen 0 1280x800x24" $DEST/bin/sdr-trunk
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sdrtrunk.service || true
# Do not auto-start until configured — operator starts from UI
echo "SDR Location Gateway dependencies installed."
echo "Configure a radio system in the UI, then start sdrtrunk.service."
