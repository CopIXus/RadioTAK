"""Field help registry for form popovers and the Help page."""

from __future__ import annotations

import json

HELP: dict[str, dict[str, str]] = {
    "tak.name": {
        "label": "Server name",
        "what": "Friendly label shown in the RadioTAK console for this TAK connection.",
        "where": "Choose any name you will recognize (agency, region, or FQDN).",
        "example": "TN TAK / samsung.copix.us",
    },
    "tak.host": {
        "label": "Host / FQDN",
        "what": "Hostname or IP of the TAK Server used for CoT streaming and enrollment.",
        "where": "Same host you use in ATAK/iTAK network preferences or infra-TAK Caddy FQDN.",
        "example": "tak.example.org",
    },
    "tak.cot_port": {
        "label": "CoT / streaming port",
        "what": "TLS port where RadioTAK sends Cursor-on-Target events.",
        "where": "TAK Server CoreConfig connector (default 8089) or infra-TAK TAK Server page.",
        "example": "8089",
    },
    "tak.enrollment_port": {
        "label": "Enrollment port",
        "what": "Port used for certificate enrollment (username/password → client cert).",
        "where": "TAK Server CoreConfig enrollment connector; default 8446 on most installs.",
        "example": "8446",
    },
    "tak.api_port": {
        "label": "Marti API port",
        "what": "HTTPS Marti API for group/channel listing after enrollment.",
        "where": "Usually 8443 on TAK Server; same port CloudTAK uses for Marti.",
        "example": "8443",
    },
    "tak.callsign": {
        "label": "Gateway callsign",
        "what": "Callsign TAK Server shows for this RadioTAK connection in the connected-clients dashboard.",
        "where": "Operator choice; sent as RadioTAK's own SA presence when the CoT stream connects.",
        "example": "CarterCo-RadioTAK",
    },
    "tak.default_callsign": {
        "label": "Default radio callsign",
        "what": "Fallback callsign for forwarded radios when the unit has no callsign set.",
        "where": "Marker Appearance on this TAK server; unit edit overrides this.",
        "example": "Radio",
    },
    "tak.cot_type": {
        "label": "Radio CoT type",
        "what": "CoT type for radio detection markers. Neutral/unknown ground types show a name on the map but do not appear in ATAK Contacts. Friendly unit (a-f-G-U-C) does show as a contact.",
        "where": "TAK → Configure → Marker Appearance, or override per radio on Units → Edit.",
        "example": "a-n-G",
    },
    "tak.iconset_path": {
        "label": "Iconset path",
        "what": "ATAK/CloudTAK usericon path: iconset UUID + group/name.",
        "where": "In CloudTAK/ATAK, inspect a marker's icon property (uuid:Group/name).",
        "example": "34ae1613-…:Hiking/star",
    },
    "tak.marker_color": {
        "label": "Marker color",
        "what": "Hex color for the CoT marker on TAK clients and the RadioTAK map.",
        "where": "Any #RRGGBB value; matches CloudTAK marker-color.",
        "example": "#1100ff",
    },
    "tak.cot_how": {
        "label": "CoT how",
        "what": "How the location was obtained (machine GPS, human entry, etc.).",
        "where": "CoT 2.0 how attribute; m-g = machine GPS, h-g-i-g-o = human/GUI.",
        "example": "m-g",
    },
    "tak.default_ce_feet": {
        "label": "Default CE (feet)",
        "what": "Circular error / position accuracy written to CoT when the radio report has none.",
        "where": "Converted to meters for the CoT point ce attribute (2000 ft ≈ 609.6 m).",
        "example": "2000",
    },
    "tak.presence_lat": {
        "label": "RadioTAK user latitude",
        "what": "Map position for the RadioTAK gateway user. Leave blank if you only need the callsign in the TAK Server client list.",
        "where": "TAK → Configure → Marker Appearance. Same WGS-84 latitude ATAK uses.",
        "example": "36.297",
    },
    "tak.presence_lon": {
        "label": "RadioTAK user longitude",
        "what": "Map position for the RadioTAK gateway user. Leave blank if you only need the callsign in the TAK Server client list.",
        "where": "TAK → Configure → Marker Appearance.",
        "example": "-82.342",
    },
    "tak.username": {
        "label": "Enrollment username",
        "what": "TAK Server / Authentik user used for certificate enrollment.",
        "where": "Account provisioned on the TAK Server or via Authentik LDAP.",
        "example": "radiotak-gateway",
    },
    "tak.password": {
        "label": "Enrollment password",
        "what": "Password or token for enrollment. Use the eye icon to confirm what you typed. Not stored in plaintext after enrollment.",
        "where": "Same credential used to enroll ATAK/iTAK clients.",
        "example": "",
    },
    "unit.radio_id": {
        "label": "Radio ID",
        "what": "Subscriber / radio unit ID from the trunked system (RID).",
        "where": "Observed Units table after the decoder hears GPS, or your radio programming.",
        "example": "1234567",
    },
    "unit.system_id": {
        "label": "System ID",
        "what": "Optional radio system identifier to disambiguate the same RID on multiple systems.",
        "where": "Matches the Radio System name/protocol context from the SDR page.",
        "example": "County P25",
    },
    "unit.callsign": {
        "label": "Callsign",
        "what": "Display name on TAK and the map for this radio.",
        "where": "Operator choice; overrides TAK server default callsign when set.",
        "example": "Engine 4",
    },
    "unit.cot_type": {
        "label": "Unit CoT type",
        "what": "Per-radio CoT type. Neutral/unknown ground types label the marker without adding an ATAK contact. Use a-f-G-U-C only if this radio should appear in Contacts.",
        "where": "Units → Edit; overrides TAK server Marker Appearance when set.",
        "example": "a-n-G",
    },
    "unit.stale_seconds": {
        "label": "Radio marker stale",
        "what": "How long a radio location stays on ATAK after the last GPS report, then stales out. Settings default is 1200 seconds (20 minutes). On a unit, 0 means use Settings.",
        "where": "Settings → Forwarding for the default; Units → Edit to override one radio.",
        "example": "1200",
    },
    "sdr.gain": {
        "label": "Gain (dB)",
        "what": "Tuner RF gain. Auto mode lets SDRTrunk pick; manual uses this value.",
        "where": "SDR page → Saved tuner settings. Applied when the playlist/tuner config is written.",
        "example": "28.0",
    },
    "sdr.ppm": {
        "label": "PPM correction",
        "what": "Crystal frequency correction for the dongle in parts-per-million.",
        "where": "Calibrate against a known channel; many RTL sticks need 0–60 ppm.",
        "example": "15",
    },
    "sdr.bias_tee": {
        "label": "Bias tee",
        "what": "Power the antenna feedline from the SDR (if the dongle supports it).",
        "where": "Only enable if your antenna/LNA expects bias-T power.",
        "example": "",
    },
    "sdr.frequencies": {
        "label": "Frequencies (MHz)",
        "what": "Control-channel frequencies for trunked P25/DMR, or conventional NFM channels.",
        "where": "RadioReference / FCC license / agency programming — enter CC, not random voice channels.",
        "example": "851.0125",
    },
    "sdr.protocol": {
        "label": "Protocol",
        "what": "Decoder mode written into the SDRTrunk playlist.",
        "where": "P25 C4FM, P25 LSM/CQPSK, DMR, or NFM conventional.",
        "example": "P25",
    },
    "tailscale.auth_key": {
        "label": "Tailscale auth key",
        "what": "One-time or reusable key that joins this Pi to your tailnet.",
        "where": "Tailscale admin → Settings → Keys → Auth keys.",
        "example": "tskey-auth-…",
    },
    "tailscale.hostname": {
        "label": "Tailscale hostname",
        "what": "Name this device advertises on the tailnet.",
        "where": "Operator choice; shows in the Tailscale machines list.",
        "example": "radiotak-pi",
    },
    "settings.min_interval": {
        "label": "Min interval (sec)",
        "what": "Minimum seconds between forwarded updates for the same radio.",
        "where": "Settings → Forwarding; reduces TAK spam from chatty GPS.",
        "example": "2",
    },
    "settings.unknown_radios": {
        "label": "Unknown radios",
        "what": "Whether unapproved radios are denied or only observed.",
        "where": "Settings → Forwarding. Default deny keeps the allowlist strict.",
        "example": "deny",
    },
    "settings.map_history": {
        "label": "Map history (minutes)",
        "what": "How far back last-known positions are shown on the map.",
        "where": "Settings → Forwarding / Map.",
        "example": "60",
    },
    "cust.banner_text": {
        "label": "Banner text",
        "what": "Centered heading in the top bar when set (and Show banner is checked).",
        "where": "Customization page; max 120 characters. Uncheck Show banner to hide.",
        "example": "County OEM RadioTAK",
    },
    "cust.title": {
        "label": "Console title",
        "what": "Optional agency name for the top bar. The sidebar always says RadioTAK.",
        "where": "Customization → Console identity. Leave as RadioTAK to omit the top bar.",
        "example": "Carter County",
    },
    "cust.logo": {
        "label": "Agency logo",
        "what": "PNG, SVG, or JPEG (max 512 KB) shown on the top identification banner.",
        "where": "Customization → Agency Logo upload.",
        "example": "agency-seal.png",
    },
}


def get_help(key: str) -> dict[str, str]:
    return HELP.get(key, {"label": key, "what": "", "where": "", "example": ""})


def help_as_json() -> str:
    return json.dumps(HELP)


def all_help() -> dict[str, dict[str, str]]:
    return HELP


def help_keys() -> list[str]:
    return sorted(HELP.keys())
