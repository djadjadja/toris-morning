#!/usr/bin/env python3
"""One-off reconnaissance. Not part of the daily run.

Asks every public endpoint we might live off, dumps what comes back into
probe/ so a human (or a model) can read the shape once and then delete this
file. Runs on a GitHub Actions runner because that IP is not blocked.
"""

import json, os, re, sys, urllib.request, urllib.parse

ARTIST_ID  = "44nxpJ4QALHoSoUFpWiIQc"
YT_CHANNEL = "UC1UP7iPrw9JuMVfaqQphQDg"
OUT        = os.path.join(os.path.dirname(__file__), "..", "probe")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

log = []


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    log.append(line)


def get(url, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "ignore")


def write(name, text):
    with open(os.path.join(OUT, name), "w") as f:
        f.write(text)
    say("wrote probe/%s  (%d bytes)" % (name, len(text)))


# ---------------------------------------------------------------- shape dump

def shape(node, depth=0, path=""):
    """Human readable outline of a JSON tree. Arrays collapse to first item."""
    pad = "  " * depth
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("avatarImage", "visuals", "sharingInfo", "coverArt", "image",
                     "images", "extractedColors", "previews", "audioPreview"):
                out.append("%s%s: <skipped media>" % (pad, k))
                continue
            if isinstance(v, dict):
                out.append("%s%s:" % (pad, k))
                out += shape(v, depth + 1, path + "/" + k)
            elif isinstance(v, list):
                out.append("%s%s: [%d]" % (pad, k, len(v)))
                if v and depth < 7:
                    out += shape(v[0], depth + 1, path + "/" + k + "[0]")
            else:
                s = str(v)
                if len(s) > 90:
                    s = s[:90] + "..."
                out.append("%s%s = %s" % (pad, k, s))
    elif isinstance(node, list):
        if node and depth < 7:
            out += shape(node[0], depth, path + "[0]")
    else:
        s = str(node)
        out.append("%s%s" % (pad, s[:90]))
    return out


# ---------------------------------------------------------------- spotify

def spotify_token():
    page = get("https://open.spotify.com/embed/artist/" + ARTIST_ID)
    m = re.search(r'"accessToken":"([^"]+)"', page)
    if not m:
        say("spotify: NO TOKEN in embed page")
        return None
    say("spotify: token ok, length", len(m.group(1)))
    return m.group(1)


def pathfinder(tok, op, variables, sha):
    url = ("https://api-partner.spotify.com/pathfinder/v1/query"
           "?operationName=" + op +
           "&variables=" + urllib.parse.quote(json.dumps(variables)) +
           "&extensions=" + urllib.parse.quote(json.dumps(
               {"persistedQuery": {"version": 1, "sha256Hash": sha}})))
    return json.loads(get(url, {
        "Authorization": "Bearer " + tok,
        "app-platform": "WebPlayer",
        "Accept": "application/json",
    }))


def do_spotify():
    tok = spotify_token()
    if not tok:
        return

    # 1. the overview we already use, dumped whole
    try:
        r = pathfinder(tok, "queryArtistOverview",
                       {"uri": "spotify:artist:" + ARTIST_ID, "locale": ""},
                       "4bc52527bb77a5f8bbb9afe491e9aa725698d29ab73bff58d49169ee29800167")
        write("overview.raw.json", json.dumps(r, indent=1))
        au = r.get("data", {}).get("artistUnion", {})
        write("overview.shape.txt", "\n".join(shape(au)))

        # 2. the specific things worth designing around, pulled out flat
        picked = {}
        stats = au.get("stats", {})
        picked["stats"] = stats
        profile = au.get("profile", {})
        picked["profile_keys"] = sorted(profile.keys())
        picked["name"] = profile.get("name")
        picked["verified"] = profile.get("verified")
        picked["biography_len"] = len(str(profile.get("biography", "")))

        tracks = (au.get("discography", {}) or {}).get("topTracks", {}) or {}
        items = tracks.get("items", []) or []
        picked["topTracks"] = [{
            "name": (i.get("track") or {}).get("name"),
            "uri":  (i.get("track") or {}).get("uri"),
            "playcount": (i.get("track") or {}).get("playcount"),
        } for i in items]
        say("spotify: topTracks found:", len(items))

        disc = au.get("discography", {}) or {}
        for key in ("albums", "singles", "compilations", "popularReleases", "latest"):
            node = disc.get(key)
            if isinstance(node, dict):
                picked["disc_" + key + "_total"] = node.get("totalCount")
            elif node:
                picked["disc_" + key] = str(node)[:300]

        rel = au.get("relatedContent", {}) or {}
        picked["relatedContent_keys"] = sorted(rel.keys())
        for k, v in rel.items():
            if isinstance(v, dict):
                picked["related_" + k + "_total"] = v.get("totalCount")

        picked["goods_keys"] = sorted((au.get("goods") or {}).keys())
        write("overview.picked.json", json.dumps(picked, indent=1))
    except Exception as e:
        say("spotify overview FAILED:", repr(e)[:300])

    # 3. is there a discography-with-playcounts query we can page?
    for op, sha, var in [
        ("queryArtistDiscographyAll",
         "9380995a9d4663cbcb5113fef3c6aabf70ae6d407ba61793fe5adfa2941a4e1a",
         {"uri": "spotify:artist:" + ARTIST_ID, "offset": 0, "limit": 50}),
        ("queryArtistDiscographySingles",
         "9380995a9d4663cbcb5113fef3c6aabf70ae6d407ba61793fe5adfa2941a4e1a",
         {"uri": "spotify:artist:" + ARTIST_ID, "offset": 0, "limit": 50}),
    ]:
        try:
            r = pathfinder(tok, op, var, sha)
            if r.get("errors"):
                say(op, "-> errors:", json.dumps(r["errors"])[:200])
            else:
                write(op + ".shape.txt", "\n".join(shape(r.get("data", {}))))
        except Exception as e:
            say(op, "FAILED:", repr(e)[:200])


# ---------------------------------------------------------------- youtube

def do_youtube():
    # RSS: cheap, stable, gives the latest 15 uploads. Does it carry views?
    try:
        x = get("https://www.youtube.com/feeds/videos.xml?channel_id=" + YT_CHANNEL)
        write("youtube.rss.xml", x[:60000])
        say("youtube rss: has media:statistics?", "media:statistics" in x)
        say("youtube rss: entry count", x.count("<entry>"))
    except Exception as e:
        say("youtube rss FAILED:", repr(e)[:200])

    # The /videos tab carries per video viewCountText in ytInitialData.
    try:
        h = get("https://www.youtube.com/channel/" + YT_CHANNEL + "/videos")
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", h, re.S)
        if not m:
            say("youtube videos: no ytInitialData")
        else:
            d = json.loads(m.group(1))
            found = []

            def walk(o):
                if len(found) > 30:
                    return
                if isinstance(o, dict):
                    if "videoId" in o and "title" in o:
                        t = o.get("title", {})
                        title = t.get("simpleText") or "".join(
                            r.get("text", "") for r in (t.get("runs") or []))
                        vc = o.get("viewCountText") or {}
                        views = vc.get("simpleText") or "".join(
                            r.get("text", "") for r in (vc.get("runs") or []))
                        pub = (o.get("publishedTimeText") or {}).get("simpleText")
                        if title:
                            found.append({"videoId": o["videoId"], "title": title,
                                          "views": views, "published": pub})
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)

            walk(d)
            write("youtube.videos.json", json.dumps(found, indent=1))
            say("youtube videos: parsed", len(found), "entries")
    except Exception as e:
        say("youtube videos FAILED:", repr(e)[:200])


def main():
    os.makedirs(OUT, exist_ok=True)
    do_spotify()
    do_youtube()
    write("_log.txt", "\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
