#!/usr/bin/env python3
"""Runs four times a day. Reads the public numbers, merges them into data.json.

Rules it must never break:
  - never overwrite a real number with a null or a zero
  - never crash the workflow, a missing number is fine, a broken page is not
  - one entry per date, later runs on the same date update that entry

Substrate notes, so nobody re-derives this at 2am:
  - open.spotify.com/get_access_token is retired, it answers 403 URL Blocked.
    The embed page still ships an anonymous accessToken in its markup and the
    same token is accepted by the web player's own stats query. If this ever
    breaks, look at the embed page first, not at the API.
  - queryArtistOverview carries far more than the two headline numbers:
    ten tracks with cumulative playcounts, five cities with listener counts,
    the next scheduled release, catalogue totals, and about 28 releases with
    real dates on them. All of it is free.
  - YouTube: the /channel page's "viewCountText" is an OBJECT and belongs to
    whichever video the page happens to feature. We recorded that by mistake
    until 2026-08-15 and were undercounting by two million. The real channel
    total is a bare STRING on the /about panel, next to subscriberCountText.
"""

import json, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

ARTIST_ID  = "44nxpJ4QALHoSoUFpWiIQc"
YT_CHANNEL = "UC1UP7iPrw9JuMVfaqQphQDg"
TZ         = timezone(timedelta(hours=8))
DATA       = os.path.join(os.path.dirname(__file__), "..", "data.json")
KEEP_DAYS  = 2000   # the record now reaches back to Jan 2024, do not truncate it

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

OVERVIEW_HASH = "4bc52527bb77a5f8bbb9afe491e9aa725698d29ab73bff58d49169ee29800167"


def get(url, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def num(v):
    """Anything that is a real positive whole number, or None."""
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except Exception:
        return None


# ------------------------------------------------------------------ spotify

def spotify():
    """Returns (day_fields, track_catalogue, releases). Any can be empty, never raises."""
    day, cat, rel = {}, {}, {}

    try:
        page = get("https://open.spotify.com/embed/artist/" + ARTIST_ID)
        m = re.search(r'"accessToken":"([^"]+)"', page)
        if not m:
            print("spotify: no token in the embed page")
            return day, cat, rel
        tok = m.group(1)
    except Exception as e:
        print("spotify: embed page failed,", str(e)[:120])
        return day, cat, rel

    try:
        variables = {"uri": "spotify:artist:" + ARTIST_ID, "locale": ""}
        ext = {"persistedQuery": {"version": 1, "sha256Hash": OVERVIEW_HASH}}
        url = ("https://api-partner.spotify.com/pathfinder/v1/query"
               "?operationName=queryArtistOverview"
               "&variables=" + urllib.parse.quote(json.dumps(variables)) +
               "&extensions=" + urllib.parse.quote(json.dumps(ext)))
        r = json.loads(get(url, {
            "Authorization": "Bearer " + tok,
            "app-platform": "WebPlayer",
            "Accept": "application/json",
        }))
        au = r["data"]["artistUnion"]
    except Exception as e:
        print("spotify: overview query failed,", str(e)[:160])
        return day, cat, rel

    # headline numbers
    stats = au.get("stats") or {}
    if num(stats.get("monthlyListeners")):
        day["spotifyListeners"] = num(stats["monthlyListeners"])
    if num(stats.get("followers")):
        day["spotifyFollowers"] = num(stats["followers"])

    # five cities, with how many people in each
    cities = []
    for c in ((stats.get("topCities") or {}).get("items") or [])[:5]:
        n = num(c.get("numberOfListeners"))
        if c.get("city") and n:
            cities.append({"city": c["city"], "country": c.get("country", ""), "n": n})
    if cities:
        day["cities"] = cities

    # ten songs, with cumulative plays
    tracks = {}
    disc = au.get("discography") or {}
    for item in ((disc.get("topTracks") or {}).get("items") or []):
        t = item.get("track") or {}
        tid, n = t.get("id"), num(t.get("playcount"))
        if tid and n:
            tracks[tid] = n
            cat[tid] = {"name": t.get("name") or tid,
                        "uri": t.get("uri") or ("spotify:track:" + tid)}
    if tracks:
        day["tracks"] = tracks

    # what is out, and what is coming
    latest = disc.get("latest") or {}
    if latest.get("name"):
        day["latest"] = {"name": latest["name"],
                         "date": iso_date(latest.get("date")),
                         "type": (latest.get("type") or "").title()}

    pre = (au.get("preRelease") or {})
    content = pre.get("preReleaseContent") or {}
    when = ((pre.get("releaseDate") or {}).get("isoString") or "")[:10]
    if content.get("name"):
        day["next"] = {"name": content["name"], "date": when,
                       "type": (content.get("type") or "").title()}

    # catalogue standing
    counts = {}
    for key, out in (("albums", "albums"), ("singles", "singles")):
        node = disc.get(key) or {}
        if num(node.get("totalCount")):
            counts[out] = num(node["totalCount"])
    rel = au.get("relatedContent") or {}
    for key, out in (("discoveredOnV2", "discoveredOn"),
                     ("featuringV2", "featuredIn"),
                     ("relatedArtists", "relatedArtists")):
        node = rel.get(key) or {}
        if num(node.get("totalCount")):
            counts[out] = num(node["totalCount"])
    if counts:
        day["counts"] = counts

    # every release we can see, with a real date on it. the window of ten
    # albums and ten singles slides, so we merge and never delete: the store
    # accumulates the full release history from today forward.
    def take(node):
        for it in (node.get("items") or []):
            r = it
            if isinstance(it.get("releases"), dict):
                inner = it["releases"].get("items") or []
                r = inner[0] if inner else {}
            rid = r.get("id")
            if rid and r.get("name"):
                rel[rid] = {"name": r["name"],
                            "date": iso_date(r.get("date")),
                            "type": (r.get("type") or "").title(),
                            "tracks": (r.get("tracks") or {}).get("totalCount")}

    for key in ("albums", "singles", "compilations", "popularReleasesAlbums"):
        node = disc.get(key)
        if isinstance(node, dict):
            take(node)
    if latest.get("id") and latest.get("name"):
        rel[latest["id"]] = {"name": latest["name"],
                             "date": iso_date(latest.get("date")),
                             "type": (latest.get("type") or "").title(),
                             "tracks": (latest.get("tracks") or {}).get("totalCount")}
    rel = {k: v for k, v in rel.items() if v.get("date")}

    print("spotify: ok,", len(tracks), "tracks,", len(cities), "cities,",
          len(rel), "dated releases")
    return day, cat, rel


# ------------------------------------------------------------------ youtube

def to_int(s):
    s = s.strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMB]?)", s)
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])


def youtube():
    """The about panel carries the channel's own lifetime total. Do not read
    viewCountText off the channel page: there it is an object belonging to a
    single featured video."""
    out = {}
    try:
        h = get("https://www.youtube.com/channel/" + YT_CHANNEL + "/about?hl=en")
        m = re.search(r'"viewCountText"\s*:\s*"([\d,]+)\s+views"', h)
        if m and to_int(m.group(1)):
            out["youtubeViews"] = to_int(m.group(1))
        m = re.search(r'"subscriberCountText"\s*:\s*"([\d.,]+[KMB]?)\s+subscribers"', h)
        if m and to_int(m.group(1)):
            out["youtubeSubs"] = to_int(m.group(1))
    except Exception as e:
        print("youtube: about panel failed,", str(e)[:120])

    if "youtubeSubs" not in out:
        try:
            h = get("https://www.youtube.com/channel/" + YT_CHANNEL)
            m = re.search(r'([\d.,]+[KMB]?)\s+subscribers', h)
            if m and to_int(m.group(1)):
                out["youtubeSubs"] = to_int(m.group(1))
        except Exception as e:
            print("youtube: channel page failed,", str(e)[:120])

    print("youtube:", out or "nothing found")
    return out


# ------------------------------------------------------------------ storage

def iso_date(d):
    """Spotify hands dates back as {year, month, day} or an iso string."""
    if not d:
        return ""
    if isinstance(d, str):
        return d[:10]
    y, m, dd = d.get("year"), d.get("month"), d.get("day")
    if not y:
        return ""
    return "%04d-%02d-%02d" % (y, m or 1, dd or 1)


def load():
    """Reads data.json in either the old array shape or the current one."""
    try:
        raw = json.load(open(DATA))
    except Exception:
        raw = None
    if isinstance(raw, list):
        return {"tracks": {}, "days": raw, "releases": {}}
    if isinstance(raw, dict) and isinstance(raw.get("days"), list):
        raw.setdefault("tracks", {})
        raw.setdefault("releases", {})
        return raw
    return {"tracks": {}, "days": [], "releases": {}}


def main():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    store = load()

    day, cat, rel = spotify()
    day.update(youtube())

    if not day:
        print("nothing to record this morning, leaving the file untouched")
        return 0

    store["tracks"].update(cat)
    store.setdefault("releases", {}).update(rel)

    entry = next((e for e in store["days"] if e.get("date") == today), None)
    if entry is None:
        entry = {"date": today}
        store["days"].append(entry)

    # merge, never letting a blank stand on top of something real
    for k, v in day.items():
        if v in (None, "", {}, []):
            continue
        if k == "tracks":
            merged = dict(entry.get("tracks") or {})
            merged.update(v)
            entry["tracks"] = merged
        else:
            entry[k] = v

    store["days"].sort(key=lambda e: e.get("date", ""))
    store["days"] = store["days"][-KEEP_DAYS:]
    store["updated"] = datetime.now(TZ).isoformat(timespec="minutes")

    with open(DATA, "w") as f:
        json.dump(store, f, indent=1)
    print("wrote", today, sorted(day.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
