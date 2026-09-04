# Customization

RadioTAK supports infra-TAK-style branding on a **top identification bar**. Product identity in the sidebar is always RadioTAK (logo, name, version, and an update pill when a newer build is available).

- **Title** and **accent** color (Customization page; theme dark/light)
- **Identification banner** — enable, text (≤120 chars), font, size, color
- **Agency logo** — PNG / SVG / JPEG ≤512 KB stored under `/var/lib/radiotak/branding/`
- A customized console title (for example “Carter County”) and/or banner text appear in the top bar
- Agency logo appears on the banner (both sides)
- Public routes: `GET /branding/logo`, `GET /branding/favicon` (favicon is the RadioTAK product mark)

Marker appearance for CoT push is configured **per TAK server** (TAK → Configure → Marker Appearance): radio callsign, CoT type (default named marker, not an ATAK contact), iconset path, color, how, CE feet, and optional RadioTAK user position. Radio marker stale time is under Settings → Forwarding (default 20 minutes).
