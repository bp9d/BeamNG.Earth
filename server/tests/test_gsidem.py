"""GSI Japan elevation tiles (EJapan/gsidem.py): the signed 24-bit decode, the Japan BBox, and the
dem5a_png -> dem_png fallback. No network: the decode and BBox tests are synthetic, the fallback test
uses a fake fetcher."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # server/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "EJapan"))  # EJapan/
import gsidem  # noqa: E402
import netfetch  # noqa: E402

BASE = "https://cyberjapandata.gsi.go.jp/xyz"


def _png(rgb):
    """A 256x256 RGB PNG from a [256, 256, 3] uint8 array."""
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG")
    return buf.getvalue()


def _tile(r, g, b):
    """A 256x256 PNG whose every pixel is (r, g, b)."""
    rgb = np.zeros((256, 256, 3), np.uint8)
    rgb[..., 0], rgb[..., 1], rgb[..., 2] = r, g, b
    return _png(rgb)


class FakeFetcher:
    """A netfetch.Fetcher stand-in: url -> bytes, or None for a 404 (netfetch.NotFound)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def register_chain(self, *a, **k):
        pass

    def miss_alive(self, path, url):
        return False

    def get(self, url, *, kind="demand", headers=None, lane=None):
        self.calls.append(url)
        if url in self.responses and self.responses[url] is not None:
            return SimpleNamespace(body=self.responses[url])
        raise netfetch.NotFound(url)


class DecodeTest(unittest.TestCase):
    def test_positive_height(self):
        # x = 2^16 R + 2^8 G + B; x < 2^23 -> h = x * 0.01.  100.0 m -> x = 10000 -> (0, 39, 16)
        h, ok = gsidem._decode(_tile(0, 39, 16))
        self.assertTrue(ok.all())
        self.assertAlmostEqual(float(h[0, 0]), 100.0, places=1)

    def test_nodata(self):
        # (128, 0, 0) -> x = 2^23 -> NA
        h, ok = gsidem._decode(_tile(128, 0, 0))
        self.assertFalse(ok.any())

    def test_negative_height(self):
        # x > 2^23 -> h = (x - 2^24) * 0.01.  -50.0 m -> x = 2^24 - 5000 = 16772216 -> (255, 236, 120)
        h, ok = gsidem._decode(_tile(255, 236, 120))
        self.assertTrue(ok.all())
        self.assertAlmostEqual(float(h[0, 0]), -50.0, places=1)


class CoversTest(unittest.TestCase):
    def test_japan_inside(self):
        self.assertTrue(gsidem.covers(14, 14126, 6567))     # Fukuoka
        self.assertTrue(gsidem.covers(14, 14547, 6463))     # Tokyo

    def test_outside(self):
        self.assertFalse(gsidem.covers(5, 10, 10))          # the Atlantic


class FallbackTest(unittest.TestCase):
    def test_dem5a_then_dem_png(self):
        # dem5a_png 404, dem_png valid: the tile comes from dem_png
        fetcher = FakeFetcher({
            f"{BASE}/dem5a_png/14/14126/6567.png": None,
            f"{BASE}/dem_png/14/14126/6567.png": _tile(0, 39, 16),
        })
        with tempfile.TemporaryDirectory() as d:
            g = gsidem.GsiDem(d, fetcher)
            got = g.tile(14, 14126, 6567)
        self.assertIsNotNone(got)
        h, ok = got
        self.assertTrue(ok.all())
        self.assertAlmostEqual(float(h[0, 0]), 100.0, places=1)
        self.assertIn(f"{BASE}/dem5a_png/14/14126/6567.png", fetcher.calls)
        self.assertIn(f"{BASE}/dem_png/14/14126/6567.png", fetcher.calls)

    def test_dem5a_serves(self):
        # dem5a_png valid: dem_png is not asked
        fetcher = FakeFetcher({f"{BASE}/dem5a_png/14/14126/6567.png": _tile(0, 39, 16)})
        with tempfile.TemporaryDirectory() as d:
            g = gsidem.GsiDem(d, fetcher)
            got = g.tile(14, 14126, 6567)
        self.assertIsNotNone(got)
        self.assertNotIn(f"{BASE}/dem_png/14/14126/6567.png", fetcher.calls)

    def test_none_where_no_data(self):
        # both services 404: tile is None (the caller keeps Mapterhorn)
        fetcher = FakeFetcher({
            f"{BASE}/dem5a_png/14/14126/6567.png": None,
            f"{BASE}/dem_png/14/14126/6567.png": None,
        })
        with tempfile.TemporaryDirectory() as d:
            g = gsidem.GsiDem(d, fetcher)
            got = g.tile(14, 14126, 6567)
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()