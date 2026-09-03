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

# Git refuses "dubious ownership" when this script runs as root but /opt/radiotak
# is owned by the radiotak service user (normal after the first install).
if ! git config --system --get-all safe.directory 2>/dev/null | grep -qx "$INSTALL_DIR"; then
  git config --system --add safe.directory "$INSTALL_DIR" || true
fi
git_ok() { git -c "safe.directory=$INSTALL_DIR" "$@"; }

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
  git_ok -C "$INSTALL_DIR" fetch "$REPO_URL" "$BRANCH"
  git_ok -C "$INSTALL_DIR" checkout --force -B "$BRANCH" FETCH_HEAD
else
  info "Cloning $REPO_URL ($BRANCH) → $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  git_ok clone --depth 1 -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

info "Creating Python venv…"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
"$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR" -q
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

write_admin_auth() {
  local user="$1" password="$2"
  # Write via Python so Argon2 hashes (which contain '$') are never expanded by bash.
  RADIOTAK_DATA_DIR="$DATA_DIR" \
  RADIOTAK_ADMIN_USER="$user" \
  RADIOTAK_ADMIN_PASSWORD="$password" \
    "$INSTALL_DIR/.venv/bin/python3" -c '
import os
from radiotak.auth import save_auth
save_auth(os.environ["RADIOTAK_ADMIN_USER"], os.environ["RADIOTAK_ADMIN_PASSWORD"])
'
  chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/auth.json"
}

# /dev/tty always exists as a device node; it only works with a controlling terminal.
has_tty() { (exec <>/dev/tty) 2>/dev/null; }

AUTH_FILE="$DATA_DIR/auth.json"
if [[ ! -f "$AUTH_FILE" ]]; then
  if [[ -n "${RADIOTAK_ADMIN_PASSWORD:-}" ]]; then
    [[ ${#RADIOTAK_ADMIN_PASSWORD} -ge 8 ]] || die "RADIOTAK_ADMIN_PASSWORD must be at least 8 characters"
    write_admin_auth "${RADIOTAK_ADMIN_USER:-admin}" "$RADIOTAK_ADMIN_PASSWORD"
    unset RADIOTAK_ADMIN_PASSWORD
    ok "Admin account created"
  elif has_tty; then
    # Read from the controlling terminal, not stdin — curl|bash otherwise
    # consumes the rest of this script as the "password" and then dies on EOF.
    echo
    info "Create administrator account"
    read -r -p " Admin username [admin]: " ADMIN_USER < /dev/tty || true
    ADMIN_USER=${ADMIN_USER:-admin}
    while true; do
      read -r -s -p " Admin password: " ADMIN_PASS < /dev/tty || die "No password entered"
      echo
      read -r -s -p " Confirm password: " ADMIN_PASS2 < /dev/tty || die "No password entered"
      echo
      [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] || { echo "Passwords do not match"; continue; }
      [[ ${#ADMIN_PASS} -ge 8 ]] || { echo "Use at least 8 characters"; continue; }
      break
    done
    write_admin_auth "$ADMIN_USER" "$ADMIN_PASS"
    unset ADMIN_PASS ADMIN_PASS2
    ok "Admin account created"
  else
    info "No terminal attached — create the admin account in the web UI on first visit"
  fi
else
  info "Admin account already exists ($AUTH_FILE)"
fi

CERT="$DATA_DIR/tls/cert.pem"
KEY="$DATA_DIR/tls/key.pem"
if [[ ! -f "$CERT" ]]; then
  info "Generating self-signed TLS certificate…"
  SAN_PARTS=(DNS:localhost IP:127.0.0.1)
  if hn=$(hostname -s 2>/dev/null); then
    [[ -n "$hn" ]] && SAN_PARTS+=("DNS:$hn")
  fi
  for ip in $(hostname -I 2>/dev/null); do
    SAN_PARTS+=("IP:$ip")
  done
  SAN=$(IFS=,; echo "${SAN_PARTS[*]}")
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout "$KEY" -out "$CERT" \
    -subj "/CN=RadioTAK" \
    -addext "subjectAltName=${SAN}" >/dev/null 2>&1 \
    || die "Failed to generate TLS certificate"
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
