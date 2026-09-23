# TAK Enrollment

RadioTAK supports three enrollment modes for each TAK Server, plus a **Portal streaming feed** profile for WRITE-only data feeds.

## Portal streaming WRITE feed (recommended for radio markers)

Use this when you want RadioTAK to push into a TAK Portal Integration that only members of a `*_READ` channel can see — without the feed receiving user SA / location.

1. In **TAK Portal → Integrations**, create an Integration:
   - **Make Streaming Data Feed?** = Yes  
   - Groups: select only the target `*_WRITE` channel(s)  
   - Note the assigned **data-feed port**
2. Click **Download Certs** (zip with pem/key/p12).
3. In RadioTAK → **TAK Servers**:
   - Add feed with profile **Portal streaming data feed (WRITE)**  
   - Set **Feed / CoT TLS port** to the Portal data-feed port  
   - **Import certs** → upload the Portal zip  
4. Confirm:
   - RadioTAK shows **connected** and increasing **Sent** / last send  
   - Portal Integrations shows **Connected** for that `nodered-*` user  

Streaming feeds do **not** call Marti `PUT /groups/active` (filter groups are on the data feed). Gateway presence SA is off so RadioTAK is not a mutual-location contact.

Users join the matching `*_READ` group in Portal/ATAK to receive markers without sharing their SA into the WRITE feed.

## Mode A — Username / password (TAK Portal / Authentik)

Posts a locally generated CSR to TAK Server Marti TLS enrollment:

- `GET https://<host>:<enrollment-port>/Marti/api/tls/config`
- `POST https://<host>:<enrollment-port>/Marti/api/tls/signClient/v2` (falls back to `/signClient`)

Default enrollment port is **8446**. Fields: host, enrollment port, CoT TLS port (default **8089**), username, password/token, verify TLS.

The private key never leaves RadioTAK. The signed certificate, key, CA chain, and PKCS#12 are stored under `/var/lib/radiotak/secrets/<server-id>/`.

Uncheck **Verify TLS** when the enrollment listener uses a self-signed certificate (common on TAK Server). After enrollment, RadioTAK uses the returned CA for CoT TLS when present. The CoT stream (8089) verifies that CA and does **not** require the TAK keystore certificate hostname to match the FQDN (hostname mismatch is normal).

## Mode B — ATAK data package ZIP / Portal cert zip

Upload a connection preferences ZIP or a Portal **Download Certs** zip containing `.pem`/`.key`/`.p12` and CA material.

## Mode C — Existing certificate

Upload PEM cert/key or PKCS#12 with optional password.

## Channels (groups) — standard profile only

After certificate enrollment on a **standard** CoT profile, RadioTAK queries Marti:

- `GET /Marti/api/groups/all` (mTLS on API port, typically **8443**)
- Selected groups stored on the server record
- Applied after the CoT TLS session is connected: `PUT /Marti/api/groups/active` (fallback `activebits` with integer bit positions from `/groups/all`)
- A HTTP 400 from those endpoints while RadioTAK is disconnected is expected; channels remain saved locally

On connect (standard profile) RadioTAK sends a self SA (type `a-f-G-U-C`) using the **gateway callsign** and device UID so TAK Server lists it as a connected client. Radio detections use a non-contact CoT type (default `a-n-G`) with a callsign label and a configurable stale time (default 20 minutes).

## Certificate warnings

Expiry warnings at 30 / 14 / 7 days and when expired.
