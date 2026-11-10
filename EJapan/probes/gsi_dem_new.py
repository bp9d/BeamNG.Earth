"""Verify GSI's new elevation tile services (dem_png / dem5a_png): grid, zoom range, decode.

Shibuya (35.681236 N, 139.767125 E) ground elevation ~40-60 m.
"""
import io
import math
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 0.4
LAT, LON = 35.681236, 139.767125


def merc_y(lat, z):
    n = 2 ** z
    return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def ll_y(lat, z):
    n = 2 ** z
    return int((90 - lat) / 180 * n)


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


def dem_stat(data):
    if not data:
        return "no-data"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        cx, cy = w // 2, h // 2
        r, g, b = im.getpixel((cx, cy))
        raw = r * 65536 + g * 256 + b
        return (f"{w}x{h} center=({r},{g},{b}) raw={raw} "
                f"h={raw * 0.01 - 10000:.1f}m (with -10000) / {raw * 0.01:.1f}m (without)")
    except Exception as e:  # noqa: BLE001
        return f"decode-fail {e!r} ({len(data)}B)"


def run(service, zs):
    print(f"\n=== {service}  Shibuya ===")
    for z in zs:
        x = lon_x(LON, z)
        row = []
        for name, y in (("merc", merc_y(LAT, z)), ("4326", ll_y(LAT, z))):
            st, data = fetch(f"https://cyberjapandata.gsi.go.jp/xyz/{service}/{z}/{x}/{y}.png")
            row.append(f"{name:5s} y={y:6d} -> {st} ({len(data)}B) {dem_stat(data) if st == 200 else ''}")
        print(f"z{z:<3d} x={x:7d}   " + "  ".join(row))


if __name__ == "__main__":
    run("dem_png", (10, 12, 13, 14, 15, 16))
    run("dem5a_png", (10, 12, 13, 14, 15, 16))