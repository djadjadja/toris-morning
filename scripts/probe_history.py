#!/usr/bin/env python3
"""Recon pass three. Two jobs.

1. The number we have been recording as "YouTube views, all time" is wrong.
   The regex grabs the first viewCountText on the channel page, which belongs
   to a single five year old video. Find where the real channel total lives.
2. Retry the Spotify Web API with backoff. If it opens, the full discography
   with real release dates is a genuine year of history we can chart without
   inventing anything.
"""

import json, os, re, sys, time, urllib.request

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


def find_channel_total():
    say("=== where does the channel total actually live ===")
    h = get("https://www.youtube.com/channel/" + YT_CHANNEL + "/about?hl=en")
    for m in re.finditer(r"([\d,]{7,})\s*views", h):
        n = m.group(1)
        ctx = h[max(0, m.start()-220):m.end()+40]
        say("--- candidate", n, "---")
        say("   ", ctx.replace("\n", " ")[-320:])
    tests = {
        "viewCountText.simpleText"     : r'"viewCountText"\s*:\s*\{\s*"simpleText"\s*:\s*"([\d,]+) views"',
        "content.simpleText near views": r'"content"\s*:\s*\{\s*"simpleText"\s*:\s*"([\d,]+) views"',
        "viewCount key"                : r'"viewCount"\s*:\s*"?([\d,]+)"?',
        "aboutFullMetadata"            : r'aboutFullMetadata.{0,4000}?([\d,]{7,}) views',
        "channel_metadata viewCount"   : r'"channelMetadataRenderer".{0,3000}?"viewCount"\s*:\s*"?([\d,]+)"?',
    }
    for name, pat in tests.items():
        found = re.findall(pat, h, re.S)[:4]
        say("  %-30s %s" % (name, found))
    write("about.snippet.txt", h[:1000])


def full_discography():
    say("=== spotify web api, with backoff ===")
    page = get("https://open.spotify.com/embed/artist/" + ARTIST_ID)
    m = re.search(r'"accessToken":"([^"]+)"', page)
    if not m:
        say("  no token"); return
    tok = m.group(1)
    albums, offset = [], 0
    while offset < 250:
        url = ("https://api.spotify.com/v1/artists/" + ARTIST_ID +
               "/albums?include_groups=album,single,compilation&limit=50&market=US&offset=" + str(offset))
        got = None
        for attempt in range(5):
            try:
                got = json.loads(get(url, {"Authorization": "Bearer " + tok}))
                break
            except Exception as e:
                wait = 4 * (attempt + 1)
                say("  offset", offset, "attempt", attempt, repr(e)[:90], "waiting", wait)
                time.sleep(wait)
        if got is None:
            say("  gave up at offset", offset); break
        items = got.get("items") or []
        say("  offset", offset, "->", len(items), "of", got.get("total"))
        for a in items:
            albums.append({"name": a.get("name"), "date": a.get("release_date"),
                           "precision": a.get("release_date_precision"),
                           "type": a.get("album_group") or a.get("album_type"),
                           "tracks": a.get("total_tracks"), "id": a.get("id")})
        if not got.get("next"): break
        offset += 50
        time.sleep(1.5)
    if albums:
        seen, uniq = set(), []
        for a in albums:
            if a["id"] in seen: continue
            seen.add(a["id"]); uniq.append(a)
        uniq.sort(key=lambda x: x["date"] or "")
        write("discography.json", json.dumps(uniq, indent=1))
        say("  releases with real dates:", len(uniq))
        say("  earliest:", uniq[0]["date"], "|", uniq[0]["name"])
        say("  latest  :", uniq[-1]["date"], "|", uniq[-1]["name"])
        from collections import Counter
        say("  by year:", dict(sorted(Counter((a["date"] or "?")[:4] for a in uniq).items())))
        say("  in the last 12 months:", len([a for a in uniq if (a["date"] or "") >= "2025-08-15"]))


def main():
    os.makedirs(OUT, exist_ok=True)
    find_channel_total()
    full_discography()
    write("_log3.txt", "\n".join(log))
    return 0

sys.exit(main())
