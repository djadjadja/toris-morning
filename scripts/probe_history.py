#!/usr/bin/env python3
"""Second recon pass. Three questions:

1. Does the anonymous embed token work against the ordinary Spotify Web API?
   If it does we can read the FULL discography with real release dates, which
   is a genuine year of history that needs no inventing.
2. Is the Wayback index reachable at all from here, on a retry?
3. Our YouTube view count disagrees with Social Blade by about 2 million.
   Which one is the channel total?
"""

import json, os, re, sys, time, urllib.request, urllib.parse

ARTIST_ID  = "44nxpJ4QALHoSoUFpWiIQc"
YT_CHANNEL = "UC1UP7iPrw9JuMVfaqQphQDg"
OUT = os.path.join(os.path.dirname(__file__), "..", "probe", "history")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
log = []

def say(*a):
    s = " ".join(str(x) for x in a); print(s); log.append(s)

def get(url, headers=None, timeout=45):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers: h.update(headers)
    return urllib.request.urlopen(urllib.request.Request(url, headers=h),
                                  timeout=timeout).read().decode("utf-8", "ignore")

def write(name, text):
    with open(os.path.join(OUT, name), "w") as f: f.write(text)
    say("wrote", name, "(%d bytes)" % len(text))

def token():
    page = get("https://open.spotify.com/embed/artist/" + ARTIST_ID)
    m = re.search(r'"accessToken":"([^"]+)"', page)
    return m.group(1) if m else None


def q1_web_api(tok):
    say("=== 1. does the embed token open the ordinary Web API ===")
    albums, offset = [], 0
    while offset < 200:
        url = ("https://api.spotify.com/v1/artists/" + ARTIST_ID +
               "/albums?include_groups=album,single,compilation&limit=50&market=US&offset=" + str(offset))
        try:
            r = json.loads(get(url, {"Authorization": "Bearer " + tok}))
        except Exception as e:
            say("  web api FAILED at offset", offset, repr(e)[:140]); break
        items = r.get("items") or []
        say("  offset", offset, "->", len(items), "of", r.get("total"))
        for a in items:
            albums.append({"name": a.get("name"), "date": a.get("release_date"),
                           "precision": a.get("release_date_precision"),
                           "type": a.get("album_group") or a.get("album_type"),
                           "tracks": a.get("total_tracks"), "id": a.get("id")})
        if not r.get("next"): break
        offset += 50
        time.sleep(0.3)
    if albums:
        albums.sort(key=lambda x: x["date"] or "")
        write("discography.json", json.dumps(albums, indent=1))
        say("  TOTAL releases with real dates:", len(albums))
        say("  earliest:", albums[0]["date"], albums[0]["name"])
        say("  latest  :", albums[-1]["date"], albums[-1]["name"])
        from collections import Counter
        by_year = Counter((a["date"] or "?")[:4] for a in albums)
        say("  by year:", dict(sorted(by_year.items())))
        last12 = [a for a in albums if (a["date"] or "") >= "2025-08-15"]
        say("  released in the last 12 months:", len(last12))
    return albums


def q2_wayback():
    say("=== 2. wayback, retried ===")
    for attempt in range(3):
        try:
            url = ("https://web.archive.org/cdx/search/cdx?url=" +
                   urllib.parse.quote("open.spotify.com/artist/" + ARTIST_ID) +
                   "&output=json&limit=200&filter=statuscode:200&collapse=timestamp:8")
            rows = json.loads(get(url, timeout=60))
            say("  attempt", attempt, "->", max(0, len(rows) - 1), "snapshots")
            if len(rows) > 1:
                write("wayback.index.json", json.dumps(rows, indent=1))
            return rows
        except Exception as e:
            say("  attempt", attempt, "failed", repr(e)[:110]); time.sleep(6)
    return []


def q3_youtube_total():
    say("=== 3. which number is the real channel view total ===")
    for path, name in [("/about", "about"), ("", "root"), ("/videos", "videos")]:
        try:
            h = get("https://www.youtube.com/channel/" + YT_CHANNEL + path +
                    ("?hl=en" if "?" not in path else ""))
        except Exception as e:
            say(" ", name, "failed", repr(e)[:90]); continue
        subs = re.findall(r'"([\d.,]+[KMB]?) subscribers"', h)[:3]
        views_any = re.findall(r'"([\d,]+) views"', h)[:6]
        views_total = re.findall(r'"viewCountText"\s*:\s*\{\s*"simpleText"\s*:\s*"([\d,]+) views"', h)[:4]
        about_views = re.findall(r'([\d,]{7,})\s*views', h)[:6]
        say(" ", name, "| subs", subs, "| viewCountText", views_total,
            "| any-views", views_any, "| big", about_views)
    h = get("https://www.youtube.com/channel/" + YT_CHANNEL)
    m = re.search(r'"viewCountText".{0,200}?"([\d.,]+[KMB]?)\s+views?"', h)
    say("  current fetcher regex yields:", m.group(1) if m else None)
    ctx = h[max(0, m.start()-300):m.end()+120] if m else ""
    write("youtube.viewcount.context.txt", ctx)


def main():
    os.makedirs(OUT, exist_ok=True)
    tok = token()
    say("embed token:", "ok" if tok else "MISSING")
    if tok: q1_web_api(tok)
    q2_wayback()
    q3_youtube_total()
    write("_log2.txt", "\n".join(log))
    return 0

sys.exit(main())
