"""PLATEAU building footprints merged into mapdata's buildings layer (EJ_PLAN Phase 3).

The converter (plateau_converter.py --split) writes one GeoJSON per z14 map cell under
EJapan/plateau_data/<z>/<x>/<y>.json.gz. This module turns that GeoJSON into a mapgeom.Features
with the same attribute columns Overture's buildings carry (height, num_floors, roof_shape, ...),
so buildings.py.plan reads it unchanged.

Where a cell has PLATEAU data, its buildings REPLACE the Overture ones they cover (no double
counting), but Overture buildings PLATEAU does not cover are KEPT: PLATEAU's Fukuoka data has holes
(e.g. around Hakata station, where the nearest PLATEAU footprint is ~500 m away), and replacing the
whole cell left those areas bare (the user, 2026-11-10: "博多駅の駅舎の場所です。ビルもなにもありません").

    f = load_and_merge_plateau_buildings(key, existing_feats, frame)

key: a mapcells.CellKey; existing_feats: the Overture buildings Features (or None); frame: the
cell's geodesy.EnuFrame. Returns existing_feats unchanged outside Japan / where no PLATEAU file
exists, else a new localized Features of PLATEAU's footprints plus the Overture ones they do not
cover.
"""
import gzip
import json
import logging
import os

import numpy as np

import mapgeom

log = logging.getLogger("earthd.plateau_layer")

# The attribute columns Overture's buildings layer carries (overture.LAYERS["buildings"]).
_TEXT = ("subtype", "class", "name", "src_dataset", "src_record", "roof_shape", "roof_orientation",
         "roof_material", "roof_color", "facade_material", "facade_color", "height_src")
_FLOAT = ("height", "min_height", "num_floors", "num_floors_underground", "min_floor", "level",
          "roof_height", "roof_direction")
_FLAG = ("is_underground", "has_parts")

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plateau_data")


def _data_version():
    """The installed cities' version (plateau_data/manifest.json, written by install_city.py): mapdata.versions()
    carries it, so cached road tiles (revisit) rebuild and pick up the new buildings after a city is installed.
    Without a manifest (no city installed yet) it is 1."""
    try:
        with open(os.path.join(_DATA_DIR, "manifest.json"), encoding="utf-8") as f:
            return int(json.load(f).get("version", 1))
    except (OSError, ValueError, TypeError):
        return 1


# Bump (install_city.py does) when the PLATEAU data or its conversion changes: mapdata.versions() carries it, so
# cached road tiles (revisit) rebuild and pick up the new buildings.
VERSION = _data_version()
# The provenance mapdata records for a cell whose buildings are PLATEAU's (the credits overlay).
PROVENANCE = {
    "id": "plateau",
    "name": "PLATEAU (Project PLATEAU, MLIT Japan)",
    "release": str(VERSION),
    "attribution": "Project PLATEAU (MLIT Japan)",
    "licence": "PLATEAU open data",
    "url": "https://www.mlit.go.jp/plateau/",
}
# PLATEAU ids are prefixed with this so they sort after Overture's (hex UUIDs start 0-9a-f): mapgeom.concat
# needs every id of its second argument to sort after the first's.
_ID_PREFIX = "~"
_COVER_CELL_M = 50.0        # m: the grid cell of the Overture-centre-in-PLATEAU-footprint test


def _path(key):
    return os.path.join(_DATA_DIR, str(key.z), str(key.x), f"{key.y}.json.gz")


def has_data(key):
    """Whether the cell has a PLATEAU file (cheap: an os.path.exists, for the credits' provenance)."""
    return os.path.exists(_path(key))


def _features_from_geojson(geojson, layer):
    """mapgeom.Features of a PLATEAU GeoJSON (Polygon / MultiPolygon footprints), ids sorted."""
    feats = [f for f in geojson.get("features", ()) if f.get("geometry")]
    feats.sort(key=lambda f: str(f.get("properties", {}).get("id", "")))
    ids, geoms, props = [], [], []
    for f in feats:
        g = f["geometry"]
        if g["type"] == "Polygon":
            rings = [np.asarray(r, np.float64) for r in g["coordinates"]]
            geoms.append((mapgeom.POLYGON, [rings]))
        elif g["type"] == "MultiPolygon":
            parts = [[np.asarray(r, np.float64) for r in poly] for poly in g["coordinates"]]
            geoms.append((mapgeom.POLYGON, parts))
        else:
            continue
        ids.append(str(f.get("properties", {}).get("id", "")))
        props.append(f.get("properties", {}))
    if not ids:
        return None
    out = mapgeom.build(layer, np.array(ids), geoms)
    n = len(ids)
    out.attrs["subtype"] = mapgeom.text_column(["building"] * n)
    out.attrs["class"] = mapgeom.text_column([str(p.get("class") or "") for p in props])
    out.attrs["name"] = mapgeom.text_column([""] * n)
    out.attrs["src_dataset"] = mapgeom.text_column(["PLATEAU"] * n)
    out.attrs["src_record"] = mapgeom.text_column([str(p.get("id") or "") for p in props])
    out.attrs["roof_shape"] = mapgeom.text_column([str(p.get("roof_type") or "") for p in props])
    out.attrs["roof_orientation"] = mapgeom.text_column([""] * n)
    out.attrs["roof_material"] = mapgeom.text_column([""] * n)
    out.attrs["roof_color"] = mapgeom.text_column([""] * n)
    out.attrs["facade_material"] = mapgeom.text_column([""] * n)
    out.attrs["facade_color"] = mapgeom.text_column([""] * n)
    out.attrs["height_src"] = mapgeom.text_column(["PLATEAU"] * n)

    def _floats(name):
        return np.array([np.nan if p.get(name) is None else float(p[name]) for p in props], np.float32)

    for name in _FLOAT:
        out.attrs[name] = _floats(name)
    for name in _FLAG:
        out.attrs[name] = np.zeros(n, bool)
    return out


def _select(f, keep):
    """Features f with only the rows where keep is True (order kept), or None when none are left."""
    idx = np.flatnonzero(keep)
    if len(idx) == len(f):
        return f
    if len(idx) == 0:
        return None
    geoms = [(f.kind[i], f.parts(i)) for i in idx]
    out = mapgeom.build(f.layer, f.ids[idx], geoms)
    for k, v in f.attrs.items():
        out.attrs[k] = v[idx]
    return out


def _covered(centres, boxes, cell=_COVER_CELL_M):
    """bool per centre (n, 2): inside any box (m, 4) [min e, min n, max e, max n] (a grid, so a cell's
    thousands of Overture centres are not tested against every PLATEAU footprint)."""
    n = len(centres)
    covered = np.zeros(n, bool)
    if n == 0 or len(boxes) == 0:
        return covered
    grid = {}
    for j, (x0, y0, x1, y1) in enumerate(boxes):
        if not (np.isfinite(x0) and np.isfinite(y0) and np.isfinite(x1) and np.isfinite(y1)):
            continue
        for ix in range(int(np.floor(x0 / cell)), int(np.floor(x1 / cell)) + 1):
            for iy in range(int(np.floor(y0 / cell)), int(np.floor(y1 / cell)) + 1):
                grid.setdefault((ix, iy), []).append(j)
    for i, (cx, cy) in enumerate(centres):
        if not (np.isfinite(cx) and np.isfinite(cy)):
            continue
        for j in grid.get((int(np.floor(cx / cell)), int(np.floor(cy / cell))), ()):
            x0, y0, x1, y1 = boxes[j]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                covered[i] = True
                break
    return covered


_logged = False


def load_and_merge_plateau_buildings(key, existing_feats, frame):
    """The cell's buildings: PLATEAU's where the cell has PLATEAU data, plus the Overture buildings
    PLATEAU does not cover (replacing the ones it does, so nothing is counted twice). frame: the
    cell's EnuFrame (the new features are localized to it)."""
    global _logged
    path = _path(key)
    if not os.path.exists(path):
        return existing_feats
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            geojson = json.load(fh)
        feats = _features_from_geojson(geojson, "buildings")
        if feats is None or len(feats) == 0:
            return existing_feats
        feats = feats.localize(frame)
        if existing_feats is not None and len(existing_feats):
            # keep the Overture buildings whose centre is not inside a PLATEAU footprint
            p_boxes = feats.boxes(frame)
            o_cx, o_cy = existing_feats.outer_centres(frame)
            covered = _covered(np.stack([o_cx, o_cy], 1), p_boxes)
            kept = _select(existing_feats, ~covered)
            if kept is not None and len(kept):
                feats.ids = np.array([_ID_PREFIX + str(x) for x in feats.ids])
                feats = mapgeom.concat(kept, feats)
        feats.__dict__["_plateau"] = True
        if not _logged:
            log.info("plateau_layer: PLATEAU buildings active (e.g. %d for %s)", len(feats), key)
            _logged = True
        return feats
    except Exception as e:
        log.warning("plateau_layer: %s: %s: %s", key, type(e).__name__, e)
        return existing_feats
