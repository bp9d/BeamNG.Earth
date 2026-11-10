"""PLATEAU layer integration: plateau_layer turns a per-cell GeoJSON into mapgeom.Features with the
Overture buildings attribute schema, leaves non-PLATEAU cells unchanged, and merges PLATEAU with the
Overture buildings it does not cover (so PLATEAU's holes, e.g. around Hakata station, keep Overture's)."""
import glob
import os
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "EJapan"))

import geodesy  # noqa: E402
import mapcells  # noqa: E402
import mapgeom  # noqa: E402
import plateau_layer  # noqa: E402

DATA = ROOT / "EJapan" / "plateau_data"


def _first_cell():
    files = sorted(glob.glob(str(DATA / "*" / "*" / "*.json.gz")))
    if not files:
        return None
    p = Path(files[0])
    z, x = int(p.parent.parent.name), int(p.parent.name)
    y = int(p.name.split(".")[0])
    return mapcells.CellKey(z, x, y)


def _one_building(lon, lat, bid):
    """A tiny square footprint Features with one building (the Overture schema's key columns)."""
    ring = np.array([[lon, lat], [lon + 0.0001, lat], [lon + 0.0001, lat + 0.0001],
                     [lon, lat + 0.0001], [lon, lat]])
    f = mapgeom.build("buildings", np.array([bid]), [(mapgeom.POLYGON, [[ring]])])
    f.attrs["src_dataset"] = mapgeom.text_column(["OpenStreetMap"])
    f.attrs["height"] = np.array([10.0], np.float32)
    return f


class PlateauLayerTest(unittest.TestCase):
    def test_no_data_returns_existing(self):
        # a cell with no PLATEAU file: the existing features come back unchanged
        key = mapcells.CellKey(14, 0, 0)
        sentinel = object()
        self.assertIs(plateau_layer.load_and_merge_plateau_buildings(key, sentinel, None), sentinel)

    def test_builds_features_with_height(self):
        key = _test_cell()
        if key is None:
            self.skipTest("no PLATEAU data converted")
        lat, lon = key.center()
        frame = geodesy.EnuFrame(lat, lon, 0.0)
        f = plateau_layer.load_and_merge_plateau_buildings(key, None, frame)
        self.assertIsNotNone(f)
        self.assertGreater(len(f), 0)
        # the Overture buildings attribute schema is present
        for name in ("height", "num_floors", "roof_shape", "class", "src_dataset", "height_src"):
            self.assertIn(name, f.attrs)
        h = f.attrs["height"]
        self.assertGreater(int((~np.isnan(h)).sum()), 0)
        self.assertTrue((f.attrs["src_dataset"] == "PLATEAU").all())
        self.assertIsNotNone(f.en)

    def test_keeps_overture_buildings_plateau_does_not_cover(self):
        # Hakata station: PLATEAU's Fukuoka data has a hole there, so an Overture building at the
        # station must survive the merge (the user, 2026-11-10: "ビルもなにもありません")
        key = mapcells.cell_of(33.5897, 130.4207, 14)
        if not plateau_layer.has_data(key):
            self.skipTest("no PLATEAU data for the Hakata station cell")
        lat, lon = key.center()
        frame = geodesy.EnuFrame(lat, lon, 0.0)
        existing = _one_building(130.4207, 33.5897, "station-test")
        merged = plateau_layer.load_and_merge_plateau_buildings(key, existing, frame)
        self.assertIsNotNone(merged)
        self.assertTrue(merged.__dict__.get("_plateau"))
        ids = {str(x) for x in merged.ids}
        self.assertIn("station-test", ids, "the Overture building in PLATEAU's hole was dropped")
        self.assertTrue((merged.attrs["src_dataset"] == "PLATEAU").any())
        self.assertTrue((merged.attrs["src_dataset"] == "OpenStreetMap").any())


def _test_cell():
    return _first_cell()


if __name__ == "__main__":
    unittest.main()
