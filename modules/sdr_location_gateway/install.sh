#!/usr/bin/env bash
# Install SDRTrunk + Xvfb + udev rules for RadioTAK SDR Location Gateway
set -euo pipefail

INSTALL_DIR="${RADIOTAK_INSTALL_DIR:-/opt/radiotak}"
DATA_DIR="${RADIOTAK_DATA_DIR:-/var/lib/radiotak}"
SDR_DIR="$DATA_DIR/sdrtrunk"
ARCH=$(uname -m)

die() { echo "sdr-install: $*" >&2; exit 1; }

pkg_available() {
  local cand
  cand=$(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')
  [[ -n "$cand" && "$cand" != "(none)" ]]
}

pick_pkg() {
  local p
  for p in "$@"; do
    if pkg_available "$p"; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

export DEBIAN_FRONTEND=noninteractive

# Debian 13 (trixie) dropped OpenJDK 17 and renamed GTK/ALSA with the t64 ABI.
JDK=$(pick_pkg openjdk-21-jre-headless openjdk-17-jre-headless default-jre-headless) \
  || die "No Java JRE package found (tried openjdk-21/17 and default-jre-headless)"
GTK=$(pick_pkg libgtk-3-0t64 libgtk-3-0) || die "No GTK3 package found"
ALSA=$(pick_pkg libasound2t64 libasound2) || true

echo "Installing packages: xvfb x11vnc wget unzip $JDK $GTK ${ALSA:-}"
apt-get install -y -qq xvfb x11vnc wget unzip "$JDK" "$GTK" ${ALSA:+"$ALSA"} \
  || die "apt-get install failed"

mkdir -p "$SDR_DIR"
cp "$INSTALL_DIR/deploy/udev/99-radiotak-sdr.rules" /etc/udev/rules.d/ 2>/dev/null || true

# Kernel DVB driver claims RTL-SDR dongles (e.g. Nooelec NESDR) as TV tuners.
# Blacklist first, then unload, then re-trigger udev so userspace can open the stick.
cat > /etc/modprobe.d/radiotak-rtl-blacklist.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832_sdr
blacklist rtl2832
blacklist dvb_usb_v2
EOF
for m in dvb_usb_rtl28xxu rtl2832_sdr rtl2832 dvb_usb_v2 dvb_core; do
  rmmod "$m" 2>/dev/null || true
done
# Unbind if rmmod was blocked by an open handle.
if [[ -d /sys/bus/usb/drivers/dvb_usb_rtl28xxu ]]; then
  for unbind in /sys/bus/usb/drivers/dvb_usb_rtl28xxu/*/unbind; do
    [[ -f "$unbind" ]] || continue
    basename "$(dirname "$unbind")" >"$unbind" 2>/dev/null || true
  done
fi
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=usb 2>/dev/null || true

# Prefer CopIXus patched release (spectrum, GPS, talkgroup audio exporters).
# Fall back to upstream DSheirer 0.6.1 if the fork asset is not published yet.
TAG="v0.6.2-radiotak.5"
UPSTREAM_TAG="v0.6.1"
ASSET="sdr-trunk-linux-aarch64-${TAG}.zip"
UP_ASSET="sdr-trunk-linux-aarch64-${UPSTREAM_TAG}.zip"
if [[ "$ARCH" == "x86_64" ]]; then
  ASSET="sdr-trunk-linux-x86_64-${TAG}.zip"
  UP_ASSET="sdr-trunk-linux-x86_64-${UPSTREAM_TAG}.zip"
fi

DEST="$SDR_DIR/app"
INSTALLED_TAG=""
WAS_ACTIVE=0
UPGRADED=0
[[ -f "$DEST/.radiotak-fork" ]] && INSTALLED_TAG=$(cat "$DEST/.radiotak-fork" 2>/dev/null || true)
NEED_DOWNLOAD=0
if [[ ! -d "$DEST" ]]; then
  NEED_DOWNLOAD=1
elif [[ "$INSTALLED_TAG" != "$TAG" ]]; then
  echo "SDRTrunk $TAG not installed (have '${INSTALLED_TAG:-stock}') — will upgrade if the fork release exists"
  NEED_DOWNLOAD=1
fi

if [[ "$NEED_DOWNLOAD" == "1" ]]; then
  echo "Downloading SDRTrunk $ASSET…"
  URL_FORK="https://github.com/CopIXus/sdrtrunk/releases/download/${TAG}/${ASSET}"
  URL_UP="https://github.com/DSheirer/sdrtrunk/releases/download/${UPSTREAM_TAG}/${UP_ASSET}"
  TMP=/tmp/sdrtrunk.zip
  GOT_FORK=0
  if wget -q -O "$TMP" "$URL_FORK"; then
    GOT_FORK=1
  elif [[ ! -d "$DEST" ]]; then
    echo "Fork release not found — using upstream $UPSTREAM_TAG"
    wget -O "$TMP" "$URL_UP" || die "Failed to download SDRTrunk from $URL_UP"
  else
    echo "Fork release $TAG not published yet — keeping existing SDRTrunk"
    rm -f "$TMP"
  fi
  if [[ -f "$TMP" ]]; then
    if systemctl is-active --quiet sdrtrunk 2>/dev/null; then
      WAS_ACTIVE=1
    fi
    systemctl stop sdrtrunk 2>/dev/null || true
    rm -rf "$DEST"
    unzip -q -o "$TMP" -d "$SDR_DIR"
    EXTRACTED=$(find "$SDR_DIR" -maxdepth 1 -type d -name 'sdr-trunk*' | head -1)
    if [[ -n "$EXTRACTED" && "$EXTRACTED" != "$DEST" ]]; then
      mv "$EXTRACTED" "$DEST"
    fi
    rm -f "$TMP"
    [[ -x "$DEST/bin/sdr-trunk" || -f "$DEST/bin/sdr-trunk" ]] || die "SDRTrunk binary missing after extract"
    if [[ "$GOT_FORK" == "1" ]]; then
      echo "$TAG" > "$DEST/.radiotak-fork"
      echo "Installed SDRTrunk $TAG (DftFrameExporter :29501, GeoEventJsonExporter :29500, AudioFrameExporter :29502)"
    else
      rm -f "$DEST/.radiotak-fork"
      echo "Installed stock SDRTrunk $UPSTREAM_TAG — waterfall and GPS export unavailable until the fork release is published"
    fi
    UPGRADED=1
  fi
fi

chown -R radiotak:radiotak "$SDR_DIR" "$DATA_DIR/modules" 2>/dev/null || true
# Headphone / HDMI jack: Java Sound only sees ALSA cards if radiotak is in `audio`.
usermod -aG audio radiotak 2>/dev/null || true

# Skip the SIMD calibration modal — nobody can click it under Xvfb, and it
# blocks playlist auto-start (empty Now Playing / no heard events).
PREFS_DIR="$DATA_DIR/.java/.userPrefs/io/github/dsheirer/preference/calibration"
mkdir -p "$PREFS_DIR"
if [[ ! -f "$PREFS_DIR/prefs.xml" ]] || ! grep -q 'hide.calibration.dialog' "$PREFS_DIR/prefs.xml" 2>/dev/null; then
    cat > "$PREFS_DIR/prefs.xml" <<'PREFS'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE map SYSTEM "http://java.sun.com/dtd/preferences.dtd">
<map MAP_XML_VERSION="1.0">
  <entry key="hide.calibration.dialog" value="true"/>
  <entry key="vector.enabled" value="false"/>
</map>
PREFS
fi
chown -R radiotak:radiotak "$DATA_DIR/.java" 2>/dev/null || true

# Compile JMBE on-device (do not vendor a prebuilt vocoder jar). Needed for
# clear P25/DMR Listen audio. Encrypted calls stay silent either way.
JMBE_DIR="$DATA_DIR/SDRTrunk/jmbe"
JMBE_JAR="$JMBE_DIR/jmbe-1.0.9.jar"
JMBE_TAG="v1.0.9"
if [[ ! -f "$JMBE_JAR" ]]; then
  echo "Compiling JMBE $JMBE_TAG for digital voice…"
  JMBE_ASSET="jmbe-creator-linux-aarch64-${JMBE_TAG}.zip"
  if [[ "$ARCH" == "x86_64" ]]; then
    JMBE_ASSET="jmbe-creator-linux-x86_64-${JMBE_TAG}.zip"
  fi
  JMBE_TMP="$SDR_DIR/${JMBE_ASSET}"
  JMBE_SRC="$SDR_DIR/jmbe-creator"
  mkdir -p "$JMBE_DIR"
  if wget -q -O "$JMBE_TMP" "https://github.com/DSheirer/jmbe/releases/download/${JMBE_TAG}/${JMBE_ASSET}"; then
    rm -rf "$JMBE_SRC"
    mkdir -p "$JMBE_SRC"
    unzip -q -o "$JMBE_TMP" -d "$JMBE_SRC"
    CREATOR=$(find "$JMBE_SRC" -type f -path '*/bin/creator' | head -1 || true)
    if [[ -n "$CREATOR" ]]; then
      chmod +x "$CREATOR" || true
      set +e
      ( cd "$JMBE_DIR" && HOME="$DATA_DIR" xvfb-run -a -s "-screen 0 640x480x24" "$CREATOR" )
      CREATOR_RC=$?
      set -e
      if [[ "$CREATOR_RC" -eq 0 ]]; then
        FOUND=$(find "$JMBE_DIR" "$JMBE_SRC" "$DATA_DIR" -maxdepth 4 -name 'jmbe-1*.jar' 2>/dev/null | head -1 || true)
        if [[ -n "$FOUND" && "$FOUND" != "$JMBE_JAR" ]]; then
          cp -f "$FOUND" "$JMBE_JAR"
        fi
      else
        echo "JMBE creator exited $CREATOR_RC" >&2
      fi
    fi
    rm -f "$JMBE_TMP"
    rm -rf "$JMBE_SRC"
  else
    echo "Could not download JMBE Creator $JMBE_ASSET" >&2
    rm -f "$JMBE_TMP"
  fi
  if [[ -f "$JMBE_JAR" ]]; then
    echo "JMBE library ready: $JMBE_JAR"
  else
    echo "JMBE compile skipped or failed — clear P25/DMR Listen audio stays silent until $JMBE_JAR exists" >&2
  fi
fi

DECODER_PREFS_DIR="$DATA_DIR/.java/.userPrefs/io/github/dsheirer/preference/decoder"
mkdir -p "$DECODER_PREFS_DIR"
if [[ -f "$JMBE_JAR" ]]; then
  cat > "$DECODER_PREFS_DIR/prefs.xml" <<PREFS
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE map SYSTEM "http://java.sun.com/dtd/preferences.dtd">
<map MAP_XML_VERSION="1.0">
  <entry key="alert.jmbe.required" value="false"/>
  <entry key="path.jmbe.library.1.0.0" value="$JMBE_JAR"/>
</map>
PREFS
elif [[ ! -f "$DECODER_PREFS_DIR/prefs.xml" ]] || ! grep -q 'alert.jmbe.required' "$DECODER_PREFS_DIR/prefs.xml" 2>/dev/null; then
  cat > "$DECODER_PREFS_DIR/prefs.xml" <<'PREFS'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE map SYSTEM "http://java.sun.com/dtd/preferences.dtd">
<map MAP_XML_VERSION="1.0">
  <entry key="alert.jmbe.required" value="false"/>
</map>
PREFS
fi
chown -R radiotak:radiotak "$DATA_DIR/.java" "$JMBE_DIR" 2>/dev/null || true

# systemd units
cat > /etc/systemd/system/sdrtrunk.service <<EOF
[Unit]
Description=SDRTrunk (RadioTAK) under Xvfb
After=network.target radiotak.service

[Service]
Type=simple
User=radiotak
Group=radiotak
SupplementaryGroups=audio
Environment=DISPLAY=:99
Environment=HOME=$DATA_DIR
WorkingDirectory=$DEST
ExecStartPre=/usr/bin/mkdir -p $DATA_DIR/SDRTrunk/playlist
ExecStart=/usr/bin/xvfb-run -a -s "-screen 0 1280x800x24" $DEST/bin/sdr-trunk
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sdrtrunk.service || true
# Fresh install: do not auto-start until configured — operator starts from UI.
# Upgrade of a running decoder: bring it back so the operator is not left with a stopped service.
if [[ "$UPGRADED" == "1" && "$WAS_ACTIVE" == "1" ]]; then
  echo "Restarting sdrtrunk with the new build…"
  systemctl restart sdrtrunk 2>/dev/null || true
fi
echo "SDR Location Gateway dependencies installed."
echo "Configure a radio system in the UI, then start sdrtrunk.service."
