"""Shared CoT / forwarding constants."""

# Radio detections: named map markers, not ATAK Contacts (a-f-G-U-C is SA/contact).
DETECTION_COT_TYPE = "a-n-G"
SA_COT_TYPE = "a-f-G-U-C"
DEFAULT_STALE_SECONDS = 1200  # 20 minutes — P25 GPS reports are infrequent
PRESENCE_STALE_SECONDS = 90
PRESENCE_INTERVAL_SECONDS = 30.0
SA_ENDPOINT = "*:-1:stcp"
