"""Verify the decode of GSI's new elevation tiles (dem_png / dem5a_png) over the whole tile.

Shibuya (35.681236 N, 139.767125 E) ground elevation ~40-60 m. If the RGB decode
(R*65536+G*256+B)*0.01-10000 is right, the tile's valid pixels should cluster around
that, with 0 (nodata) pixels for sea / outside coverage.
"""
import io
import math
import statistics
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


def fetch(url):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return repr(e), b""


def tile_stats(data):
    if not data:
        return "no-data"
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    px = list(im.getdata())
    vals = [(r * 65536 + g * 256 + b) for (r, g, b) in px]
    nodata = sum(1 for v in vals if v == 0)
    valid = [v * 0.01 - 10000 for v in vals if v != 0]
    if not valid:
        return f"{w}x{h} ALL NODATA"
    return (f"{w}x{h} nodata={nodata}/{len(vals)}  valid h: min={min(valid):.1f} "
            f"max={max(valid):.1f} mean={statistics.mean(valid):.1f} "
            f"median={statistics.median(valid):.1f}")


def run(service, z):
    x = lon_x(LON, z)
    y = merc_y(LAT, z)
    st, data = fetch(f"https://cyberjapandata.gsi.go.jp/xyz/{service}/{z}/{x}/{y}.png")
    print(f"{service} z{z} x={x} y={y} -> {st} ({len(data)}B)  {tile_stats(data) if st == 200 else ''}")


if __name__ == "__main__":
    for z in (13, 14, 15):
        run("dem_png", z)
    for z in (13, 14, 15):
        run("dem5a_png", z)