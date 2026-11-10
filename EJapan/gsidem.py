"""GSI Japan's elevation tiles (dem*_png): 5 m / 10 m bare-earth DEMs (基盤地図情報数値標高モデル).

Why (EJ_PLAN Phase 1): Mapterhorn's z13-z15 tiles over Japan are a coarse global model drawn out (Copernicus GLO-30,
~30 m), and the terrain's 1 m lattice (heightmap.py) wants the real ground. GSI publishes its national elevation model
as Web-Mercator XYZ PNG tiles (dem5a_png 5 m, dem_png 10 m), a DTM (no buildings or trees), free to use with
attribution (国土地理院). The tiles are 256 px, Web Mercator (no coordinate transform), heights in a signed 24-bit
RGB encoding.

    g = GsiDem(cache_dir, fetcher)
    got = g.tile(z, x, y)       # None, or (heights float32 [512, 512], valid bool [512, 512]) on dem.py's grid

Reads go through netfetch (the shared Fetcher: rate limits, retries, circuit breaker) and are cached on disk, so a
place is fetched once. dem5a_png serves z1-15; z16 (the near terrain) is its z15 parent upsampled 2x. Where dem5a_png
has nothing (404) dem_png (DEM10B, z1-14) fills in; where neither has data the caller keeps Mapterhorn's heights.

Decode (GSI 標高タイルの詳細仕様, demtile.html): x = 2^16 R + 2^8 G + B; x < 2^23 -> h = x * 0.01; x = 2^23 -> NA
((R, G, B) = (128, 0, 0)); x > 2^23 -> h = (x - 2^24) * 0.01.
"""
import io
import logging
import math
import os
import threading

import numpy as np
from PIL import Image

import cache as cachemod
import netfetch
import staging

log = logging.getLogger("earthd.gsidem")

HOST = "cyberjapandata.gsi.go.jp"
BASE = f"https://{HOST}/xyz"
# (service, max_zoom): dem5a_png (5 m) first, dem_png (DEM10B, 10 m) as the fallback
SERVICES = (("dem5a_png", 15), ("dem_png", 14))
# Where to ask at all: Japan, as lat / lon (south, west, north, east)
BOUNDS = (24.0, 122.9, 45.6, 146.0)
TILE = 512                      # dem.py's tile size
MIN_ZOOM = 13                   # coarser tiles (far terrain) keep Mapterhorn
MAX_ZOOM = 15                   # dem5a_png's finest zoom; z16 is its z15 parent upsampled
NODATA = 1 << 23                # x == 2^23: no data ((R, G, B) = (128, 0, 0))


def tile_bounds(z, x, y):
    """(south, west, north, east) of tile (z, x, y)."""
    n = 2 ** z
    lat = lambda yy: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))     # noqa: E731
    return lat(y + 1), x / n * 360.0 - 180.0, lat(y), (x + 1) / n * 360.0 - 180.0


def covers(z, x, y):
    """Whether tile (z, x, y) touches BOUNDS (where GSI is asked at all)."""
    s, w, n, e = tile_bounds(z, x, y)
    S, W, N, E = BOUNDS
    return s < N and n > S and w < E and e > W


def _decode(data):
    """(heights float32 [256, 256], valid bool [256, 256]) of a GSI dem*_png tile (signed 24-bit RGB)."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.asarray(im)
    r = arr[..., 0].astype(np.int32)
    g = arr[..., 1].astype(np.int32)
    b = arr[..., 2].astype(np.int32)
    x = (r << 16) | (g << 8) | b
    h = np.where(x < NODATA, x * 0.01, (x - (1 << 24)) * 0.01).astype(np.float32)
    ok = x != NODATA
    return h, ok


def _resize(a, size):
    if a.shape[0] == size:
        return a
    return np.asarray(Image.fromarray(a, mode="F").resize((size, size), Image.BILINEAR))


def _resize_valid(h, ok, size):
    """h / ok (256x256) resampled to size x size, nodata pixels not contaminating the heights: a normalized
    bilinear, each output pixel the mean of the valid source pixels under it (a plain BILINEAR would blend the
    nodata value -83886 into the land)."""
    hf = np.where(ok, h, 0.0).astype(np.float32)
    hz = _resize(hf, size)
    wz = _resize(ok.astype(np.float32), size)
    with np.errstate(invalid="ignore", divide="ignore"):
        hz = np.where(wz > 0.5, hz / np.maximum(wz, 1e-6), 0.0)
    return hz.astype(np.float32), wz > 0.5


class GsiDem:
    disk = cachemod.NONE        # the server's cache.Cache; set by earthd

    def __init__(self, cache_dir, fetcher):
        self.cache_dir, self.fetcher = cache_dir, fetcher
        self.fetcher.register_chain("gsidem", (f"{BASE}/dem5a_png/{{z}}/{{x}}/{{y}}.png",))
        self.stats = {"tiles": 0, "empty": 0, "errors": 0}

    def _path(self, service, z, x, y):
        return os.path.join(self.cache_dir, service, str(z), str(x), f"{y}.png")

    def _fetch(self, service, z, x, y):
        """Raw tile bytes from disk cache or network; None for a (cached) 404. Raises netfetch.FetchError."""
        path = self._path(service, z, x, y)
        miss = path[:-4] + ".404"
        data = self.disk.read(path)
        if data is not None:
            return data
        url = f"{BASE}/{service}/{z}/{x}/{y}.png"
        if self.fetcher.miss_alive(miss, url):
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            data = self.fetcher.get(url, kind="demand").body
        except netfetch.NotFound:
            open(miss, "wb").close()        # (re)written: its mtime starts the marker's TTL
            self.disk.wrote(miss, 0)
            return None
        except netfetch.FetchError:
            raise
        tmp = f"{path}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        staging.replace_cached(tmp, path)
        self.disk.wrote(path, len(data))
        if os.path.exists(miss):            # an expired marker: the host has data there now
            os.remove(miss)
            self.disk.forget(miss)
        return data

    def _tile(self, z, x, y):
        """(heights, valid) of tile (z, x, y) from the services, or None where neither has data."""
        for service, maxz in SERVICES:
            if z > maxz:
                continue
            try:
                data = self._fetch(service, z, x, y)
            except netfetch.FetchError as e:
                self.stats["errors"] += 1
                log.debug("gsidem %s %s: %s", service, (z, x, y), e)
                continue
            if data is None:
                continue
            h, ok = _decode(data)
            return _resize_valid(h, ok, TILE)
        return None

    def _from_ancestor(self, z, x, y, z0):
        """Tile (z, x, y) bilinear from its z0 ancestor's 512x512 grid (z16 from the z15 parent)."""
        d = z - z0
        ax, ay = x >> d, y >> d
        got = self.tile(z0, ax, ay)
        if got is None:
            return None
        h, ok = got
        k = 2 ** d
        i = (np.arange(TILE) + 0.5) / k - 0.5
        u = np.clip((x - ax * k) * TILE / k + i, 0, TILE - 1)
        v = np.clip((y - ay * k) * TILE / k + i, 0, TILE - 1)
        u0 = np.minimum(np.floor(u).astype(np.int64), TILE - 2)
        v0 = np.minimum(np.floor(v).astype(np.int64), TILE - 2)
        fu, fv = (u - u0)[None, :], (v - v0)[:, None]

        def _bil(a):
            a00 = a[np.ix_(v0, u0)]
            a01 = a[np.ix_(v0, u0 + 1)]
            a10 = a[np.ix_(v0 + 1, u0)]
            a11 = a[np.ix_(v0 + 1, u0 + 1)]
            return ((a00 * (1 - fu) + a01 * fu) * (1 - fv) + (a10 * (1 - fu) + a11 * fu) * fv)

        # normalized: the z15 tile's invalid (0) pixels do not drag the z16 heights down
        hf = np.where(ok, h, 0.0).astype(np.float32)
        hz = _bil(hf)
        wz = _bil(ok.astype(np.float32))
        with np.errstate(invalid="ignore", divide="ignore"):
            hz = np.where(wz > 0.5, hz / np.maximum(wz, 1e-6), 0.0)
        return hz.astype(np.float32), wz > 0.5

    def tile(self, z, x, y):
        """Heights and their validity on dem.py's tile (z, x, y), or None where GSI has nothing there.
        Network failures raise netfetch.FetchError (the caller keeps its own heights)."""
        if not covers(z, x, y):
            return None
        if z > MAX_ZOOM:        # z16: the near terrain, from the z15 parent upsampled
            return self._from_ancestor(z, x, y, MAX_ZOOM)
        got = self._tile(z, x, y)
        if got is None:
            return None
        h, ok = got
        self.stats["tiles"] += 1
        if not ok.any():
            self.stats["empty"] += 1
            return None
        return h, ok