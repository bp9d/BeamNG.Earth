"""One-shot probe: which tiling does GSI cyberjapandata's XYZ service use?

For a fixed lat/lon there are two candidate (z,x,y):
  - Web Mercator (EPSG:3857) slippy: y from asinh(tan(lat))
  - Lat/lon (EPSG:4326) equidistant: y from (90-lat)/180
Only y differs. Fetch both and report which one returns the real imagery
(non-blank photo / plausible DEM elevation for that spot).

Shibuya (35.681 N, 139.767 E) real ground elevation is ~40-60 m.
"""
import io
import math
import statistics
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 0.7  # be polite to GSI (rate-limited public service)

PHOTO = "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
DEM5A = "https://cyberjapandata.gsi.go.jp/xyz/dem5a/{z}/{x}/{y}.png"


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
    except Exception as e:  # noqa: BLE001
        return repr(e), b""


def photo_stat(data):
    if not data:
        return "no-data"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        small = im.resize((32, 32))
        getter = getattr(small, "get_flattened_data", None)
        px = list(getter()) if getter is not None else list(small.getdata())
        means = [sum(c) / 3 for c in px]
        st = statistics.pstdev(means)
        blank = st < 6.0 and (max(means) - min(means)) < 18
        return f"{im.size[0]}x{im.size[1]} blank={blank} std={st:.1f}"
    except Exception as e:  # noqa: BLE001
        return f"decode-fail {e!r} ({len(data)} B)"


def dem_stat(data):
    """Decode the centre pixel of a GSI DEM tile: (R*65536+G*256+B)*0.01 - 10000 m."""
    if not data:
        return "no-data"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        r, g, b = im.getpixel((im.size[0] // 2, im.size[1] // 2))
        raw = r * 65536 + g * 256 + b
        return f"center RGB=({r},{g},{b})  raw={raw}  h(+-10000)={raw * 0.01 - 10000:.1f} m  h(no off)={raw * 0.01:.1f} m"
    except Exception as e:  # noqa: BLE001
        return f"decode-fail {e!r} ({len(data)} B)"


def run(kind, tmpl, lat, lon, z, stat):
    label = "seamlessphoto" if "photo" in kind else kind
    print(f"\n=== {label} z{z}  lat={lat} lon={lon} ===")
    x = lon_x(lon, z)
    for name, y in (("WEB_MERCATOR", merc_y(lat, z)), ("LATLON_4326", ll_y(lat, z))):
        url = tmpl.format(z=z, x=x, y=y)
        status, data = fetch(url)
        print(f"  {name:14s} x={x:6d} y={y:6d}  status={status}  bytes={len(data):7d}  {stat(data)}")


if __name__ == "__main__":
    LAT, LON = 35.681236, 139.767125   # Shibuya
    run("photo", PHOTO, LAT, LON, 16, photo_stat)
    run("photo", PHOTO, LAT, LON, 17, photo_stat)
    run("dem5a", DEM5A, LAT, LON, 15, dem_stat)
    # a mountainous inland spot: Fukuoka (33.59 N, 130.40 E), elevation there ~20-50 m plain
    run("photo", PHOTO, 33.5902, 130.4017, 16, photo_stat)
    run("dem5a", DEM5A, 33.5902, 130.4017, 15, dem_stat)
