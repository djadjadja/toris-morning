#!/usr/bin/env python3
"""One-off reconnaissance: is there a real year of history anywhere public?

We will not invent numbers for this page. So before backfilling anything we
check whether somebody else has been recording, and whether their record is
reachable without a login.

Candidates, in order of how much we would trust them:
  1. Wayback Machine snapshots of the Spotify artist page and its embed page.
     If a snapshot carries monthlyListeners, that is a real observation with a
     real date on it.
  2. Social Blade, which has been recording YouTube subs and views monthly for
     years and publishes it.
  3. kworb, which publishes daily Spotify listener counts but only for artists
     above its coverage threshold.
  4. Songstats, which has an artist page with a listener history chart.

Writes everything into probe/history/.
"""

import json, os, re, sys, urllib.request, urllib.parse

ARTIST_ID  = "44nxpJ4QALHoSoUFpWiIQc"
YT_CHANNEL = "UC1UP7iPrw9JuMVfaqQphQDg"
OUT = os.path.join(os.path.dirname(__file__), "..", "probe", "history")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

log = []


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    log.append(line)


def get(url, headers=None, timeout=45):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
         "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def write(name, text):
    with open(os.path.join(OUT, name), "w") as f:
        f.write(text)
    say("wrote", name, "(%d bytes)" % len(text))


# ------------------------------------------------------------ wayback

def cdx(target, label):
    """Ask the Wayback index what snapshots exist. Collapse to one a day."""
    url = ("http://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(target) +
           "&output=json&limit=400&filter=statuscode:200&collapse=timestamp:8")
    try:
        rows = json.loads(get(url))
    except Exception as e:
        say("cdx", label, "FAILED", repr(e)[:160])
        return []
    if not rows or len(rows) < 2:
        say("cdx", label, "-> no snapshots")
        return []
    head, body = rows[0], rows[1:]
    ts = [r[head.index("timestamp")] for r in body]
    say("cdx", label, "->", len(ts), "snapshots,", ts[0][:8], "to", ts[-1][:8])
    return ts


LISTENER_PATTERNS = [
    r'"monthlyListeners"\s*:\s*(\d+)',
    r'monthly_listeners["\s:]+(\d[\d,]*)',
    r'([\d,]{4,})\s+monthly listeners',
    r'"followers"\s*:\s*\{\s*"totalCount"\s*:\s*(\d+)',
]


def mine_snapshots(target, ts_list, label, cap=40):
    """Pull a spread of snapshots and look for a listener figure in each."""
    found = []
    step = max(1, len(ts_list) // cap)
    picked = ts_list[::step][:cap]
    for ts in picked:
        url = "http://web.archive.org/web/" + ts + "id_/" + target
        try:
            html = get(url, timeout=40)
        except Exception as e:
            say("  snap", ts, "failed", repr(e)[:80])
            continue
        hit = None
        for pat in LISTENER_PATTERNS:
            m = re.search(pat, html)
            if m:
                hit = {"pattern": pat, "value": m.group(1)}
                break
        date = ts[0:4] + "-" + ts[4:6] + "-" + ts[6:8]
        say("  snap", date, "->", hit["value"] if hit else "nothing", "(%d bytes)" % len(html))
        if hit:
            found.append({"date": date, "raw": hit["value"], "pattern": hit["pattern"]})
    if found:
        write(label + ".wayback.json", json.dumps(found, indent=1))
    return found


# ------------------------------------------------------------ social blade

def socialblade():
    for path in ("monthly", ""):
        url = "https://socialblade.com/youtube/channel/" + YT_CHANNEL + ("/" + path if path else "")
        try:
            html = get(url, {"Referer": "https://socialblade.com/"})
        except Exception as e:
            say("socialblade", path or "root", "FAILED", repr(e)[:120])
            continue
        say("socialblade", path or "root", "-> %d bytes" % len(html))
        write("socialblade" + ("." + path if path else "") + ".html", html[:400000])
        rows = re.findall(
            r'(\d{4}-\d{2}-\d{2})[^0-9+-]{0,400}?([+-]?[\d,]+)\s*</div>\s*</div>\s*'
            r'<div[^>]*>\s*<div[^>]*>\s*([+-]?[\d,]+)', html)
        say("socialblade rows matched:", len(rows))
        if rows:
            write("socialblade.rows.json", json.dumps(rows[:60], indent=1))
            return rows
    return []


# ------------------------------------------------------------ the rest

def try_page(url, name, needle=None):
    try:
        html = get(url)
    except Exception as e:
        say(name, "FAILED", repr(e)[:120])
        return None
    say(name, "-> %d bytes" % len(html), ("| contains %r: %s" % (needle, needle in html)) if needle else "")
    write(name + ".html", html[:300000])
    return html


def main():
    os.makedirs(OUT, exist_ok=True)

    say("=== wayback: spotify artist page ===")
    target = "open.spotify.com/artist/" + ARTIST_ID
    ts = cdx(target, "artist")
    if ts:
        mine_snapshots("https://" + target, ts, "artist")

    say("=== wayback: spotify embed page ===")
    target2 = "open.spotify.com/embed/artist/" + ARTIST_ID
    ts2 = cdx(target2, "embed")
    if ts2:
        mine_snapshots("https://" + target2, ts2, "embed")

    say("=== wayback: youtube channel ===")
    target3 = "youtube.com/channel/" + YT_CHANNEL
    ts3 = cdx(target3, "youtube")
    if ts3:
        mine_snapshots("https://www." + target3, ts3, "youtube")

    say("=== social blade ===")
    socialblade()

    say("=== kworb ===")
    for u, n in [("https://kworb.net/spotify/artist/%s.html" % ARTIST_ID, "kworb.artist"),
                 ("https://kworb.net/spotify/artist/%s_songs.html" % ARTIST_ID, "kworb.songs")]:
        try_page(u, n)

    say("=== songstats ===")
    try_page("https://songstats.com/artist/" + ARTIST_ID, "songstats", "David Andrew")

    write("_log.txt", "\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
