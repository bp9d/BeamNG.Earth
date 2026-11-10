"""Check the current state of GSI elevation tile services (2026).

GSI announced the end of the classic dem5a/dem5b/dem10b XYZ tiles (2025-03-31).
Check whether a successor service exists (dem_png / dem5a_png / dem10b_png / rel_dem...)
and what the service-list page says now.
"""
import math
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 0.4
LAT, LON = 35.681236, 139.767125


def merc_y(lat, z):
    n = 2 ** z
    return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def lon_x(lon, z):
    n = 2 ** z
    return int((lon + 180) / 360 * n) % n


def fetch(url, want=200000):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(want)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return repr(e), b""


def main():
    print("=== GSI tile list pages ===")
    for page in ("https://maps.gsi.go.jp/development/ichiran.html",
                 "https://maps.gsi.go.jp/development/ichiranxyz.html",
                 "https://maps.gsi.go.jp/development/saigai.html"):
        st, data = fetch(page)
        print(f"  {page} -> {st} ({len(data)}B)")
        if st == 200:
            text = data.decode("utf-8", "replace")
            hits = sorted(set(re.findall(r"/xyz/[A-Za-z0-9_]+", text)))
            dem = [h for h in hits if "dem" in h or "rel" in h or "elev" in h]
            print("    dem-ish paths:", dem[:20] if dem else "none")

    print("\n=== candidate elevation services at Shibuya z14 ===")
    x = lon_x(LON, 14)
    y = merc_y(LAT, 14)
    for name in ("dem_png", "dem5a_png", "dem5b_png", "dem10b_png", "rel_dem",
                 "dem5a", "dem5b", "dem10b", "demgm", "dem-gm", "elev_png"):
        st, data = fetch(f"https://cyberjapandata.gsi.go.jp/xyz/{name}/14/{x}/{y}.png")
        print(f"  {name:12s} -> {st} ({len(data)}B)")


if __name__ == "__main__":
    main()