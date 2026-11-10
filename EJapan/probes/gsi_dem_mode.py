"""Determine the pixel format of GSI's new elevation tiles (dem_png / dem5a_png).

Try: (a) 16-bit grayscale PNG, (b) RGB with the classic decode, (c) 16-bit RGB.
Shibuya ground elevation ~40-60 m.
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


def analyze(data, label):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    print(f"\n{label}: mode={im.mode} size={im.size}")

    # 16-bit grayscale
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        vals = list(im.getdata())
        nodata = sum(1 for v in vals if v == 0)
        valid = [v * 0.01 - 10000 for v in vals if v != 0]
        if valid:
            print(f"  16-bit gray: nodata={nodata}/{len(vals)}  h: min={min(valid):.1f} "
                  f"max={max(valid):.1f} mean={statistics.mean(valid):.1f} median={statistics.median(valid):.1f}")
        return

    # RGB: try classic decode and 16-bit-per-channel
    rgb = im.convert("RGB")
    px = list(rgb.getdata())
    classic = [(r * 65536 + g * 256 + b) * 0.01 - 10000 for (r, g, b) in px]
    valid = [v for v in classic if v > -9999]
    if valid:
        print(f"  RGB classic: min={min(valid):.1f} max={max(valid):.1f} "
              f"mean={statistics.mean(valid):.1f} median={statistics.median(valid):.1f}  (n={len(valid)})")
    # 16-bit per channel: (R*256+G) style
    hi = [(r * 256 + g) * 0.01 - 10000 for (r, g, b) in px]
    valid2 = [v for v in hi if v > -9999]
    if valid2:
        print(f"  RGB 16bit(RG): min={min(valid2):.1f} max={max(valid2):.1f} "
              f"mean={statistics.mean(valid2):.1f} median={statistics.median(valid2):.1f}  (n={len(valid2)})")
    # sample some pixels
    for i in (0, 1000, 32768, 65000):
        r, g, b = px[i]
        print(f"  px[{i}] = ({r},{g},{b})")


def run(service, z):
    x = lon_x(LON, z)
    y = merc_y(LAT, z)
    st, data = fetch(f"https://cyberjapandata.gsi.go.jp/xyz/{service}/{z}/{x}/{y}.png")
    print(f"\n=== {service} z{z} x={x} y={y} -> {st} ({len(data)}B)")
    if st == 200:
        analyze(data, f"{service} z{z}")


if __name__ == "__main__":
    run("dem_png", 14)
    run("dem5a_png", 15)