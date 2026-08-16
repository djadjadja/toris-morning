#!/usr/bin/env python3
"""One off: fold David's own Spotify for Artists export into data.json.

This is real data he exported himself on 2026-08-15, not anything generated.
Every row it writes carries "src": "sfa" so the provenance stays visible, and
any row the machine already recorded live wins field by field over the import.

The payload is columnar and delta encoded, then gzipped and base64'd, purely so
that pushing it through an API costs a fifth of what the raw rows would. Three
characters were mangled on the way up, so patches/errata.json carries the
corrections. gzip's own CRC is the proof they are right: if any of this were
wrong the decompress below would raise rather than quietly produce nonsense.

Delete this script and its payload once it has run.
"""

import base64, gzip, json, os, sys
from datetime import date, timedelta

HERE    = os.path.dirname(__file__)
DATA    = os.path.join(HERE, "..", "data.json")
PAYLOAD = os.path.join(HERE, "..", "patches", "payload.b64")
ERRATA  = os.path.join(HERE, "..", "patches", "errata.json")


def expand():
    blob = list("".join(open(PAYLOAD).read().split()))
    if os.path.exists(ERRATA):
        fixes = json.load(open(ERRATA))
        for i, ch in fixes:
            blob[i] = ch
        print("applied", len(fixes), "character corrections")
    c = json.loads(gzip.decompress(base64.b64decode("".join(blob))))
    start = date.fromisoformat(c["start"])
    rows = [{"date": (start + timedelta(days=i)).isoformat(), "src": c["src"]}
            for i in range(c["n"])]
    for field, deltas in c["cols"].items():
        run = 0
        for i, dv in enumerate(deltas):
            if dv is None:
                continue
            run += dv
            rows[i][field] = run
    return rows


def main():
    imported = expand()
    print("payload carries", len(imported), "days,",
          imported[0]["date"], "to", imported[-1]["date"])

    store = json.load(open(DATA))
    if isinstance(store, list):
        store = {"tracks": {}, "days": store, "releases": {}}
    store.setdefault("tracks", {})
    store.setdefault("releases", {})

    by_date = {e["date"]: dict(e) for e in imported if e.get("date")}

    kept = 0
    for e in store.get("days", []):
        d = e.get("date")
        if not d:
            continue
        merged = dict(by_date.get(d, {}))
        merged.update(e)          # anything read live wins
        by_date[d] = merged
        kept += 1

    store["days"] = sorted(by_date.values(), key=lambda e: e["date"])
    store["imported"] = {
        "source": "Spotify for Artists export, uploaded by David",
        "on": "2026-08-15",
        "covers": imported[0]["date"] + " to " + imported[-1]["date"],
        "days": len(imported),
    }

    with open(DATA, "w") as f:
        json.dump(store, f, separators=(",", ":"))

    print("kept", kept, "live rows")
    print("data.json now holds", len(store["days"]), "days,",
          store["days"][0]["date"], "to", store["days"][-1]["date"],
          "|", os.path.getsize(DATA), "bytes")
    return 0


sys.exit(main())
