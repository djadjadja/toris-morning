#!/usr/bin/env python3
"""Runs once a morning. Reads the public numbers, merges them into data.json.

Rules it must never break:
  - never overwrite a real number with a null or a zero
  - never crash the workflow, a missing number is fine, a broken page is not
  - one entry per date, later runs on the same date update that entry
"""

import json, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

ARTIST_ID  = "44nxpJ4QALHoSoUFpWiIQc"
YT_CHANNEL = "UC1UP7iPrw9JuMVfaqQphQDg"
TZ         = timezone(timedelta(hours=8))
DATA       = os.path.join(os.path.dirname(__file__), "..", "data.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def get(url, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


HASHES = [
    "4bc52527bb77a5f8bbb9afe491e9aa725698d29ab73bff58d49169ee29800167",
    "35648a112beb1794e39ab931365f6ae4a8d45e65396d641eeda94e4003d41497",
    "da986392124383827dc03cbb3d66c1de81225244b6e20f8d78f9f802cc43df6e",
]


def spotify():
    out = {}
    try:
        tok = json.loads(get(
            "https://open.spotify.com/get_access_token"
            "?reason=transport&productType=web_player"))["accessToken"]
    except Exception as e:
        print("spotify: could not get a token,", e)
        return out

    for h in HASHES:
        try:
            v = {"uri": "spotify:artist:" + ARTIST_ID, "locale": ""}
            ext = {"persistedQuery": {"version": 1, "sha256Hash": h}}
            url = ("https://api-partner.spotify.com/pathfinder/v1/query"
                   "?operationName=queryArtistOverview"
                   "&variables=" + urllib.parse.quote(json.dumps(v)) +
                   "&extensions=" + urllib.parse.quote(json.dumps(ext)))
            r = json.loads(get(url, {
                "Authorization": "Bearer " + tok,
                "app-platform": "WebPlayer",
                "Accept": "application/json",
            }))
            stats = r["data"]["artistUnion"]["stats"]
            if stats.get("monthlyListeners"):
                out["spotifyListeners"] = int(stats["monthlyListeners"])
            if stats.get("followers"):
                out["spotifyFollowers"] = int(stats["followers"])
            print("spotify: ok", out)
            return out
        except Exception as e:
            print("spotify: hash failed,", str(e)[:120])
    print("spotify: every query hash failed, leaving yesterday's number alone")
    return out


def to_int(s):
    s = s.strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMB]?)", s)
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])


def youtube():
    out = {}
    try:
        h = get("https://www.youtube.com/channel/" + YT_CHANNEL)
        m = re.search(r'([\d.,]+[KMB]?)\s+subscribers', h)
        if m:
            n = to_int(m.group(1))
            if n:
                out["youtubeSubs"] = n
        m = re.search(r'"viewCountText".{0,200}?"([\d.,]+[KMB]?)\s+views?"', h)
        if m:
            n = to_int(m.group(1))
            if n:
                out["youtubeViews"] = n
        print("youtube:", out or "nothing found")
    except Exception as e:
        print("youtube: failed,", str(e)[:120])
    return out


def main():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        history = json.load(open(DATA))
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []

    fresh = {}
    fresh.update(spotify())
    fresh.update(youtube())
    fresh = {k: v for k, v in fresh.items() if isinstance(v, int) and v > 0}

    if not fresh:
        print("nothing to record this morning, leaving the file untouched")
        return 0

    existing = next((e for e in history if e.get("date") == today), None)
    if existing:
        existing.update(fresh)
    else:
        history.append(dict(fresh, date=today))

    history.sort(key=lambda e: e.get("date", ""))
    history = history[-400:]

    with open(DATA, "w") as f:
        json.dump(history, f, indent=1)
    print("wrote", today, fresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
