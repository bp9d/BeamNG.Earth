"""Sweep: which zooms does GSI dem5a (and seamlessphoto) answer at, on which grid, for Japan?

Shibuya 35.681236 N, 139.767125 E. For each zoom z we ask both candidate y values
(Web Mercator and lat/lon equidistant) and report the first zooms that return data.
"""
import math
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 0.5
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


def fetch(url, want_bytes=True):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(60000) if want_bytes else b""
            return r.status, data
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return repr(e), b""


def probe(service, path_tmpl, zs):
    print(f"\n=== {service}  Shibuya ===")
    for z in zs:
        x = lon_x(LON, z)
        row = []
        for name, y in (("merc", merc_y(LAT, z)), ("4326", ll_y(LAT, z))):
            url = path_tmpl.format(z=z, x=x, y=y)
            status, data = fetch(url, want_bytes=(z in (14, 15)))
            row.append(f"{name:5s} y={y:6d} -> {status} ({len(data)}B)")
        print(f"z{z:<3d} x={x:7d}   " + "  ".join(row))


if __name__ == "__main__":
    probe("dem5a", "https://cyberjapandata.gsi.go.jp/xyz/dem5a/{z}/{x}/{y}.png",
          range(0, 16))
    probe("seamlessphoto (low z)",
          "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", range(0, 6))
