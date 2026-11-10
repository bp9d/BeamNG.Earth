"""Decisive grid test. For seamlessphoto and dem5a around Shibuya, count how many 200s
a +/-R tile neighbourhood gives for the Web-Mercator candidate vs the EPSG:4326 candidate.
The grid that yields a solid block of 200s is the grid the service actually uses."""
import math
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 0.15
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


def status_of(url):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return "ERR"


def count200(base, x, y, z, r):
    c = 0
    tot = 0
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            tot += 1
            st = status_of(base.format(z=z, x=x + dx, y=y + dy))
            if st == 200:
                c += 1
    return c, tot


def run(label, base, z, r):
    x = lon_x(LON, z)
    ym = merc_y(LAT, z)
    yl = ll_y(LAT, z)
    cm, tm = count200(base, x, ym, z, r)
    cl, tl = count200(base, x, yl, z, r)
    print(f"\n{label} z{z}  x={x}  (window {(2*r+1)}x{(2*r+1)} = {tm} tiles)")
    print(f"  WEB_MERCATOR  y={ym:6d}  -> {cm:2d}/{tm} are 200")
    print(f"  EPSG4326      y={yl:6d}  -> {cl:2d}/{tl} are 200")
    print(f"  VERDICT: {'WEB_MERCATOR' if cm > cl else ('EPSG4326' if cl > cm else 'NEITHER')}")


if __name__ == "__main__":
    PHOTO = "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
    DEM = "https://cyberjapandata.gsi.go.jp/xyz/dem5a/{z}/{x}/{y}.png"
    run("seamlessphoto", PHOTO, 16, 2)
    # dem5a: try z13, z14, z15 (5m DEM documented z0..z15) with a wider window
    run("dem5a", DEM, 14, 6)
    run("dem5a", DEM, 15, 6)
