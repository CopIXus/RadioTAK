# Security

## Authentication

- First-run / installer creates admin with Argon2id hash in `/var/lib/radiotak/auth.json`
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax`
- CSRF tokens on state-changing forms
- Login rate limiting

## Secrets

```text
/var/lib/radiotak/secrets/   mode 0700
  <files>                   mode 0600
```

Never returned by normal GET APIs. Never logged (passwords, tokens, private keys redacted).

## Privilege model

- Service user: `radiotak`
- Privileged ops only via `bin/radiotak-priv` + `/etc/sudoers.d/radiotak`
- No shell terminal in the UI
- No arbitrary file browsing

## Network

- Default bind: all interfaces on `:5001` HTTPS (self-signed); prefer LAN / Tailscale
- Do not expose the management UI to the public Internet without additional controls

## Diagnostics

Sanitized ZIP excludes passwords, tokens, private keys, and PKCS#12 contents. Optional GPS redaction.
