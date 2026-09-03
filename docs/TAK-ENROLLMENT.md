# TAK Enrollment

RadioTAK supports three enrollment modes for each TAK Server:

## Mode A — Username / password (TAK Portal / Authentik)

Uses PyTAK `enroll_tak(host, username, password)` against the enrollment HTTPS port (default **8446**).

Fields: host, enrollment port, CoT TLS port (default **8089**), username, password/token, verify TLS, optional CA upload.

Resulting PKCS#12 is converted to PEM under `/var/lib/radiotak/secrets/<server-id>/`.

## Mode B — ATAK data package ZIP

Upload a connection preferences ZIP containing `.p12` and CA material. Parsed with PyTAK data-package helpers.

## Mode C — Existing certificate

Upload PEM cert/key or PKCS#12 with optional password.

## Channels (groups)

After certificate enrollment, RadioTAK queries Marti:

- `GET /Marti/api/groups/all` (mTLS on API port, typically **8443**)
- Selected groups stored on the server record
- On connect: `PUT /Marti/api/groups/active` (fallback `activebits`)

## Certificate warnings

Expiry warnings at 30 / 14 / 7 days and when expired.
