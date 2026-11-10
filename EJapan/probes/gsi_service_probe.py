"""Probe GSI cyberjapandata service status: which DEM XYZ services still answer, at what zooms.

1. Fetch GSI's XYZ service list page (ichiranxyz.html) and print which services are listed.
2. Probe dem5a / dem10b / dem5b at Shibuya and Fukuoka over a zoom range (Web Mercator grid only,
   since seamlessphoto already proved that is the grid in use).
"""
import math
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 0.5


def merc_y(lat, z):
    n = 2 ** z
    return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def lon_x(lon, z):
    n = 2 ** z
    return int((lon + 180) / 360 * n) % n


def fetch(url):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(200000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return repr(e), b""


def main():
    print("=== GSI XYZ service list page ===")
    url = "https://maps.gsi.go.jp/development/ichiranxyz.html"
    status, data = fetch(url)
    if status == 200:
        text = data.decode("utf-8", "replace")
        # crude extraction: lines mentioning a service path under /xyz/
        seen = set()
        for m in re.finditer(r"(?:https?://cyberjapandata\.gsi\.go\.jp)?/xyz/[A-Za-z0-9_]+", text):
            seen.add(m.group(0).rsplit("gsi.go.jp", 1)[-1])
        for s in sorted(seen):
            print("  listed:", s)
        # also grab any sentence around "dem5a"
        for m in re.finditer(r".{80}dem5a.{120}", text):
            print("  ctx:", re.sub(r"\s+", " ", m.group(0))[:220])
    else:
        print("  status:", status)

    for name, path in (("dem5a", "/xyz/dem5a"), ("dem5b", "/xyz/dem5b"), ("dem10b", "/xyz/dem10b")):
        print(f"\n=== {name} ===")
        for lat, lon, label in ((35.681236, 139.767125, "Shibuya"), (33.5902, 130.4017, "Fukuoka")):
            row = []
            for z in (10, 12, 13, 14, 15, 16):
                x = lon_x(lon, z)
                y = merc_y(lat, z)
                st, data = fetch(f"https://cyberjapandata.gsi.go.jp{path}/{z}/{x}/{y}.png")
                row.append(f"z{z}:{st}({len(data)}B)")
            print(f"  {label:8s} " + "  ".join(row))


if __name__ == "__main__":
    main()
