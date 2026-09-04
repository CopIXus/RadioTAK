# TAK Enrollment

RadioTAK supports three enrollment modes for each TAK Server:

## Mode A — Username / password (TAK Portal / Authentik)

Posts a locally generated CSR to TAK Server Marti TLS enrollment:

- `GET https://<host>:<enrollment-port>/Marti/api/tls/config`
- `POST https://<host>:<enrollment-port>/Marti/api/tls/signClient/v2` (falls back to `/signClient`)

Default enrollment port is **8446**. Fields: host, enrollment port, CoT TLS port (default **8089**), username, password/token, verify TLS.

The private key never leaves RadioTAK. The signed certificate, key, CA chain, and PKCS#12 are stored under `/var/lib/radiotak/secrets/<server-id>/`.

Uncheck **Verify TLS** when the enrollment listener uses a self-signed certificate (common on TAK Server). After enrollment, RadioTAK uses the returned CA for CoT TLS when present.

## Mode B — ATAK data package ZIP

Upload a connection preferences ZIP containing `.p12` and CA material. Parsed with PyTAK data-package helpers.

## Mode C — Existing certificate

Upload PEM cert/key or PKCS#12 with optional password.

## Channels (groups)

After certificate enrollment, RadioTAK queries Marti:

- `GET /Marti/api/groups/all` (mTLS on API port, typically **8443**)
- Selected groups stored on the server record
- Applied after the CoT TLS session is connected: `PUT /Marti/api/groups/active` (fallback `activebits` with integer bit positions from `/groups/all`)
- A HTTP 400 from those endpoints while RadioTAK is disconnected is expected; channels remain saved locally

On connect RadioTAK sends a self SA (type `a-f-G-U-C`) using the **gateway callsign** and device UID so TAK Server lists it as a connected client. Radio detections use a non-contact CoT type (default `a-n-G`) with a callsign label and a configurable stale time (default 20 minutes).

## Certificate warnings

Expiry warnings at 30 / 14 / 7 days and when expired.
