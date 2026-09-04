# Customization

RadioTAK supports infra-TAK-style branding:

- **Title** and **accent** color (Customization page; theme dark/light)
- **Identification banner** — enable, text (≤120 chars), font, size, color
- **Agency logo** — PNG / SVG / JPEG ≤512 KB stored under `/var/lib/radiotak/branding/`
- Logo appears on the banner (both sides), sidebar, and login page
- Public routes: `GET /branding/logo`, `GET /branding/favicon` (for login without session)

Marker appearance for CoT push is configured **per TAK server** (TAK → Configure → Marker Appearance): callsign, CoT type, iconset path, color, how, CE feet.
