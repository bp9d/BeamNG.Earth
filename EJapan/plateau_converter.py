"""PLATEAU CityGML -> GeoJSON building footprints (EJ_PLAN Phase 3).

PLATEAU (Project PLATEAU, MLIT Japan) publishes each city's 3D city model as CityGML. The building
footprints and their heights are what BeamNG.Earth's buildings need (buildings.py.plan reads Overture
attributes: class, height, num_floors, roof_shape). This converter turns a PLATEAU zip's `udx/bldg/*.gml`
into GeoJSON building footprints with `height`, `num_floors` and `roof_type` properties.

    # one GeoJSON for the whole city
    python EJapan/plateau_converter.py EJapan/plateau/40130_fukuoka-shi_city_2024_citygml_2_op.zip \
        EJapan/plateau/fukuoka_buildings.geojson

    # per z14 map cell, under EJapan/plateau_data/<z>/<x>/<y>.json.gz (what plateau_layer.py reads)
    python EJapan/plateau_converter.py EJapan/plateau/40130_fukuoka-shi_city_2024_citygml_2_op.zip --split

To INSTALL a city (convert AND bump the data version so the server rebuilds the affected map cells),
use install_city.py instead: it runs this converter and updates plateau_data/manifest.json.

    python EJapan/install_city.py path/to/city.zip

The 2024 PLATEAU data is in EPSG:6697 (JGD2011 geographic, lat/lon degrees) with srsDimension 3, so the
footprint coordinates are already latitude / longitude and no projection is needed. Each point is
"lat lon height"; the footprint uses (lon, lat) as GeoJSON expects. `bldg:lod0FootPrint` holds the
ground footprint; `bldg:measuredHeight` the height in metres; `bldg:storeysAboveGround` the floor count
(9999 = unknown); `bldg:roofType` the roof shape.
"""
import argparse
import gzip
import json
import logging
import math
import os
import zipfile
import xml.etree.ElementTree as ET

log = logging.getLogger("plateau")

# CityGML 2.0 namespaces
_BLDG = "{http://www.opengis.net/citygml/building/2.0}"
_GML = "{http://www.opengis.net/gml}"
_CORE = "{http://www.opengis.net/citygml/2.0}"

# storeysAboveGround / storeysBelowGround use 9999 for "unknown"
_UNKNOWN = 9999
CELL_ZOOM = 14          # mapcells.ZOOM: the map-data cell the split files are keyed by
MAX_LAT = 85.0511287798066


def _poslist_to_ring(poslist):
    """A gml:posList ("lat lon height ...") -> [(lon, lat), ...] (GeoJSON order), dropping the height."""
    vals = [float(v) for v in poslist.split()]
    out = []
    for i in range(0, len(vals) - 2, 3):
        lat, lon = vals[i], vals[i + 1]
        out.append((lon, lat))
    return out


def _footprint(building):
    """The building's ground footprint as a GeoJSON Polygon coordinate list, or None."""
    fp = building.find(f"{_BLDG}lod0FootPrint")
    if fp is None:
        return None
    for ms in fp.iter(f"{_GML}MultiSurface"):
        for poly in ms.iter(f"{_GML}Polygon"):
            ext = poly.find(f"{_GML}exterior")
            if ext is None:
                continue
            ring = ext.find(f"{_GML}LinearRing")
            if ring is None:
                continue
            pos = ring.find(f"{_GML}posList")
            if pos is None or not pos.text:
                continue
            coords = _poslist_to_ring(pos.text)
            if len(coords) >= 4:
                return [coords]
    return None


def _float(el):
    """float of an element's text, or None."""
    if el is None or not el.text:
        return None
    try:
        return float(el.text)
    except ValueError:
        return None


def _int(el):
    """int of an element's text, or None (9999 = unknown)."""
    v = _float(el)
    if v is None or int(v) == _UNKNOWN:
        return None
    return int(v)


def _building_feature(building):
    """A GeoJSON Feature for one bldg:Building, or None if it has no usable footprint."""
    fp = _footprint(building)
    if fp is None:
        return None
    gid = building.get(f"{_GML}id")
    height = _float(building.find(f"{_BLDG}measuredHeight"))
    nf = _int(building.find(f"{_BLDG}storeysAboveGround"))
    roof = building.find(f"{_BLDG}roofType")
    roof_type = roof.text if roof is not None and roof.text else None
    return {
        "type": "Feature",
        "properties": {
            "id": gid,
            "height": height,
            "num_floors": nf,
            "roof_type": roof_type,
        },
        "geometry": {"type": "Polygon", "coordinates": fp},
    }


def convert_zip(zip_path):
    """All building footprints of a PLATEAU zip as a list of GeoJSON Features."""
    feats = []
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not name.endswith(".gml") or "/bldg/" not in name:
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError as e:
                log.warning("%s: parse error: %s", name, e)
                continue
            for building in root.iter(f"{_BLDG}Building"):
                f = _building_feature(building)
                if f is not None:
                    feats.append(f)
    return feats


def _cell_of(lat, lon, z=CELL_ZOOM):
    """The Web-Mercator z14 cell (z, x, y) holding lat / lon (mapcells.cell_of's formula)."""
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n) % n
    y = int((1.0 - math.asinh(math.tan(math.radians(max(-MAX_LAT, min(MAX_LAT, lat))))) / math.pi) / 2.0 * n)
    return z, x, max(0, min(n - 1, y))


def _centroid(feature):
    """(lat, lon) of a footprint's first ring (its centroid is close enough to pick the cell)."""
    coords = feature["geometry"]["coordinates"]
    ring = coords[0] if feature["geometry"]["type"] == "Polygon" else coords[0][0]
    lon = sum(p[0] for p in ring) / len(ring)
    lat = sum(p[1] for p in ring) / len(ring)
    return lat, lon


def split_by_cell(feats, out_dir):
    """Write the features into per-cell GeoJSON.gz files under out_dir/<z>/<x>/<y>.json.gz."""
    buckets = {}
    for f in feats:
        lat, lon = _centroid(f)
        buckets.setdefault(_cell_of(lat, lon), []).append(f)
    for (z, x, y), fs in buckets.items():
        path = os.path.join(out_dir, str(z), str(x), f"{y}.json.gz")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": fs}, fh)
    return len(buckets)


def main():
    ap = argparse.ArgumentParser(description="PLATEAU CityGML -> GeoJSON building footprints")
    ap.add_argument("zip", help="the PLATEAU citygml zip")
    ap.add_argument("out", nargs="?", help="the GeoJSON file to write (omit with --split)")
    ap.add_argument("--split", action="store_true",
                    help="write per z14 cell files under EJapan/plateau_data/<z>/<x>/<y>.json.gz")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "plateau_data"),
                    help="the --split output directory (default: EJapan/plateau_data)")
    ap.add_argument("--pretty", action="store_true", help="indent the JSON")
    args = ap.parse_args()

    feats = convert_zip(args.zip)
    if args.split:
        n = split_by_cell(feats, args.out_dir)
        print(f"{len(feats)} buildings -> {n} cells under {args.out_dir}")
        return
    if not args.out:
        ap.error("an output GeoJSON path is needed (or --split)")
    fc = {"type": "FeatureCollection", "features": feats}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=2 if args.pretty else None)
    print(f"{len(feats)} buildings -> {args.out}")


if __name__ == "__main__":
    main()
