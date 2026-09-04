# Security

## Authentication

- First-run: installer (terminal or `RADIOTAK_ADMIN_PASSWORD`) or the web UI at `/setup` creates admin with Argon2id hash in `/var/lib/radiotak/auth.json`
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax`
- CSRF tokens on state-changing forms
- Login rate limiting

## Secrets

```text
/var/lib/radiotak/secrets/   mode 0700
  <files>                   mode 0600
```

Never returned by normal GET APIs. Never logged (passwords, tokens, private keys, traffic key hex redacted).

Traffic encryption keys live in `secrets/traffic_keys/` plus a 0600 decoder file at `SDRTrunk/traffic_keys.json`. The UI never redisplays hex after save.

## Privilege model

- Service user: `radiotak`
- Privileged ops only via `bin/radiotak-priv` + `/etc/sudoers.d/radiotak`
- No shell terminal in the UI
- No arbitrary file browsing

## Network

- Default bind: all interfaces on `:5001` HTTPS (self-signed); prefer LAN / Tailscale
- Do not expose the management UI to the public Internet without additional controls

## Diagnostics

Sanitized ZIP excludes passwords, tokens, private keys, PKCS#12 contents, and traffic encryption keys. Optional GPS redaction.
