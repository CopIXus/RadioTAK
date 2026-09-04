# Install on Raspberry Pi

## Requirements

- Raspberry Pi 5 (8 GB recommended for SDRTrunk)
- Raspberry Pi OS 64-bit (Bookworm) or Debian 12 aarch64
- Ethernet preferred
- Root/sudo access

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/CopIXus/RadioTAK/main/install.sh | sudo bash
```

The installer reads the admin password from `/dev/tty`, so the `curl | sudo bash` pipe is safe. If there is no terminal, open the URL below and create the account on first visit.

## After install

1. Open `https://<pi-ip>:5001` (accept self-signed cert)
2. Log in with the admin account you created (or complete first-run setup)
3. Optionally join Tailscale (System → Tailscale)
4. Marketplace → install **SDR Location Gateway**
5. **SDR** → Discover the dongle, add a radio system (control-channel MHz), start the decoder
6. Configure TAK Server(s) and radio allowlist (Units)

## Paths

| Path | Purpose |
|------|---------|
| `/opt/radiotak` | Application (git) |
| `/var/lib/radiotak` | Persistent state |
| `/etc/systemd/system/radiotak.service` | Console service |

## CLI

```bash
sudo radiotak status
sudo radiotak logs
sudo radiotak update
sudo radiotak reset-password
sudo radiotak diagnostics
```

## GitHub Actions

A CI workflow lives at `.github/workflows/ci.yml` in the working tree. Pushing it requires a GitHub token with the `workflow` scope (the Cursor/gh OAuth app used for the initial push did not include that scope). To enable:

```bash
gh auth refresh -h github.com -s workflow
git add .github/workflows/ci.yml
git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -m "Add CI workflow"
git push
```
