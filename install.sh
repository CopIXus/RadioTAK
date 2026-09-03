#!/usr/bin/env bash
# RadioTAK installer — Raspberry Pi OS / Debian 64-bit
# Usage: curl -fsSL https://raw.githubusercontent.com/CopIXus/RadioTAK/main/install.sh | sudo bash
set -euo pipefail

REPO_URL="${RADIOTAK_REPO_URL:-https://github.com/CopIXus/RadioTAK.git}"
BRANCH="${RADIOTAK_BRANCH:-main}"
INSTALL_DIR="${RADIOTAK_INSTALL_DIR:-/opt/radiotak}"
DATA_DIR="${RADIOTAK_DATA_DIR:-/var/lib/radiotak}"
SERVICE_USER="radiotak"
PORT=5001

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[radiotak]${NC} $*"; }
ok() { echo -e "${GREEN}[radiotak]${NC} $*"; }
die() { echo -e "${RED}[radiotak]${NC} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root (sudo)."

ARCH=$(uname -m)
case "$ARCH" in
  aarch64|x86_64) ;;
  *) die "Unsupported architecture: $ARCH (need aarch64 or x86_64)" ;;
esac

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  info "Detected $PRETTY_NAME ($ARCH)"
fi

export DEBIAN_FRONTEND=noninteractive
info "Installing system packages…"
apt-get update -qq
apt-get install -y -qq git curl openssl python3 python3-venv python3-pip \
  ca-certificates sqlite3 > /tmp/radiotak-apt.log 2>&1 || {
  cat /tmp/radiotak-apt.log
  die "apt-get install failed"
}

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$DATA_DIR" "$DATA_DIR/secrets" "$DATA_DIR/logs" "$DATA_DIR/tls" "$DATA_DIR/modules"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR/secrets"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "Updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch "$REPO_URL" "$BRANCH"
  git -C "$INSTALL_DIR" checkout --force -B "$BRANCH" FETCH_HEAD
else
  info "Cloning $REPO_URL ($BRANCH) → $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

info "Creating Python venv…"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
"$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR" -q

AUTH_FILE="$DATA_DIR/auth.json"
if [[ ! -f "$AUTH_FILE" ]]; then
  echo
  info "Create administrator account"
  read -r -p " Admin username [admin]: " ADMIN_USER
  ADMIN_USER=${ADMIN_USER:-admin}
  while true; do
    read -r -s -p " Admin password: " ADMIN_PASS; echo
    read -r -s -p " Confirm password: " ADMIN_PASS2; echo
    [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] || { echo "Passwords do not match"; continue; }
    [[ ${#ADMIN_PASS} -ge 8 ]] || { echo "Use at least 8 characters"; continue; }
    break
  done
  HASH=$("$INSTALL_DIR/.venv/bin/python3" -c "
from argon2 import PasswordHasher
import sys
print(PasswordHasher().hash(sys.argv[1]))
" "$ADMIN_PASS")
  cat > "$AUTH_FILE" <<EOF
{
  "username": "$ADMIN_USER",
  "password_hash": "$HASH",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  chmod 600 "$AUTH_FILE"
  chown "$SERVICE_USER:$SERVICE_USER" "$AUTH_FILE"
  ok "Admin account created"
else
  info "Admin account already exists ($AUTH_FILE)"
fi

CERT="$DATA_DIR/tls/cert.pem"
KEY="$DATA_DIR/tls/key.pem"
if [[ ! -f "$CERT" ]]; then
  info "Generating self-signed TLS certificate…"
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout "$KEY" -out "$CERT" \
    -subj "/CN=RadioTAK" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
  chmod 600 "$KEY" "$CERT"
  chown "$SERVICE_USER:$SERVICE_USER" "$KEY" "$CERT"
fi

install -m 0755 "$INSTALL_DIR/bin/radiotak" /usr/local/bin/radiotak
install -m 0755 "$INSTALL_DIR/bin/radiotak-priv" /usr/local/sbin/radiotak-priv
cp "$INSTALL_DIR/deploy/sudoers/radiotak" /etc/sudoers.d/radiotak
chmod 440 /etc/sudoers.d/radiotak

cat > /etc/systemd/system/radiotak.service <<EOF
[Unit]
Description=RadioTAK Console
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=RADIOTAK_DATA_DIR=$DATA_DIR
Environment=RADIOTAK_INSTALL_DIR=$INSTALL_DIR
Environment=RADIOTAK_BIND_HTTPS=true
ExecStart=$INSTALL_DIR/.venv/bin/python -m radiotak.main
Restart=always
RestartSec=3
WatchdogSec=120
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

cp "$INSTALL_DIR/deploy/logrotate/radiotak" /etc/logrotate.d/radiotak 2>/dev/null || true

systemctl daemon-reload
systemctl enable radiotak
systemctl restart radiotak

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
ok "RadioTAK is running"
echo -e "  Open:  ${GREEN}https://${IP:-<pi-ip>}:$PORT${NC}"
echo -e "  Logs:  sudo radiotak logs"
echo -e "  Update: sudo radiotak update"
echo
