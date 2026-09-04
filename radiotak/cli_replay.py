"""CLI: python -m radiotak.cli_replay <file.jsonl>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(description="Replay decoder JSONL into RadioTAK pipeline")
    parser.add_argument("file", help="JSONL fixture path")
    parser.add_argument("--approve", nargs="*", help="radio_ids to auto-approve for this run")
    parser.add_argument(
        "--approve-default",
        action="store_true",
        help="approve radio 1234567 (default if none given)",
    )
    args = parser.parse_args(argv)

    from modules.sdr_location_gateway.sdrtrunk.adapter import replay_jsonl
    from radiotak.config import get_settings
    from radiotak.db import RadioIdentity, get_session_factory, init_db
    from radiotak.gateway.tak import TakConnectionManager, tak_registry

    get_settings().ensure_dirs()
    init_db()

    Session = get_session_factory()
    db = Session()
    try:
        approve = list(args.approve or [])
        if args.approve_default or not approve:
            approve.append("1234567")
        for rid in approve:
            existing = db.scalar(select(RadioIdentity).where(RadioIdentity.radio_id == rid))
            if existing:
                existing.forward_to_tak = True
                existing.enabled = True
                existing.callsign = existing.callsign or f"UNIT-{rid}"
            else:
                db.add(
                    RadioIdentity(
                        radio_id=rid,
                        system_id="TN-P25",
                        callsign=f"UNIT-{rid}",
                        forward_to_tak=True,
                        enabled=True,
                    )
                )
        db.commit()
    finally:
        db.close()

    mgr = TakConnectionManager(server_id="replay", host="", dry_run=True)
    tak_registry.upsert(mgr)

    stats = replay_jsonl(args.file, send_to_tak=True)
    print(json.dumps(stats, indent=2))
    print(f"dry-run sent={mgr.metrics.cot_sent} dropped={mgr.metrics.cot_dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
