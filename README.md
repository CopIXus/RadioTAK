<p align="center">
  <img src="docs/logo.png" alt="RadioTAK" width="280"/>
</p>

# RadioTAK

Raspberry Pi appliance console for authorized radio-system location telemetry → TAK Server.

One clone. One password. One URL. Manage everything from your browser.

**Current version:** see [`VERSION`](VERSION)

## What Is This?

RadioTAK is an infra-TAK-style management console for Raspberry Pi 5 that:

- Installs with a single command
- Hosts a password-protected HTTPS web UI with customization (logo + banner)
- Updates from GitHub with one click
- Joins Tailscale for remote access
- Installs marketplace modules (SDR Location Gateway first; Zello Audio Bridge later)
- Forwards allowlisted radio GPS positions as Cursor-on-Target (CoT) to one or more TAK Servers
- Console waterfall / hearing gauges when the SDR module is installed (Phase 6b)

> **Scope:** Only radio systems and subscriber units you own, administer, or are explicitly authorized to monitor. Unknown radios are observed but **not** forwarded by default.

## Quick Start (Raspberry Pi OS 64-bit)

```bash
curl -fsSL https://raw.githubusercontent.com/CopIXus/RadioTAK/main/install.sh | sudo bash
```

The installer will:

1. Detect Debian/Raspberry Pi OS 64-bit
2. Install Python dependencies
3. Ask you to set an admin username and password (from the terminal, even when piped via `curl | sudo bash`)
4. Start the HTTPS console on port **5001**

Then open `https://<pi-ip>:5001` and log in. If the installer had no terminal, first visit creates the admin account.

## Updating

From the web UI: **System → Update Now**

Or over SSH:

```bash
sudo radiotak update
```

Your config, certificates, and database live in `/var/lib/radiotak/` and are never overwritten by updates.

### Universal recovery (SSH)

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/radiotak.service)
git -c safe.directory=/opt/radiotak fetch https://github.com/CopIXus/RadioTAK.git main
git -c safe.directory=/opt/radiotak checkout --force -B main FETCH_HEAD
sudo systemctl restart radiotak
```

## Reset password

```bash
sudo radiotak reset-password
```

## Development (Windows / Linux)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux:
# source .venv/bin/activate
pip install -r requirements.txt
set RADIOTAK_DATA_DIR=.data
python -m radiotak.main
```

Open `https://127.0.0.1:5001` (self-signed cert).

## Replay fixtures (no RF)

```bash
radiotak replay tests/fixtures/p25_motorola_gps.jsonl
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Marketplace modules

| Module | Status |
|--------|--------|
| SDR Location Gateway | Phase 5 — P25/DMR GPS via SDRTrunk → TAK |
| Zello Audio Bridge | Coming soon — talkgroup audio → Zello Channel API |

## License

MIT (see [LICENSE](LICENSE)). The optional SDRTrunk fork remains GPLv3.
