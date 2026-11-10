#!/usr/bin/env python3
"""Install a PLATEAU city's buildings into BeamNG.Earth (one command).

    # a PLATEAU CityGML zip already downloaded
    python EJapan/install_city.py path/to/40130_fukuoka-shi_city_2024_citygml_2_op.zip

    # download it first (a direct URL to the zip)
    python EJapan/install_city.py --url https://example.com/city.zip --name fukuoka

    # what is installed
    python EJapan/install_city.py --list

It converts the zip's CityGML building footprints into per-map-cell files under
EJapan/plateau_data/<z>/<x>/<y>.json.gz (what plateau_layer.py reads) and bumps
EJapan/plateau_data/manifest.json's version, so the server rebuilds the affected
map cells on its next start (mapdata.versions() carries the version).

Only the standard library is needed: any Python 3.8+ works. The server's own
Python is .venv/Scripts/python.exe (Windows) or .venv/bin/python (Linux), made by
install.py; either runs this. On Windows, run_server.bat's Python is the same one:

    .venv\\Scripts\\python.exe EJapan\\install_city.py city.zip

PLATEAU data: https://www.mlit.go.jp/plateau/opendata/ (each city's "3D都市モデル"
zip, CityGML). The zip must hold udx/bldg/*.gml (the building footprints).
"""
import argparse
import datetime
import json
import os
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import plateau_converter as conv

DATA_DIR = os.path.join(HERE, "plateau_data")
MANIFEST = os.path.join(DATA_DIR, "manifest.json")


def load_manifest():
    """The installed cities' manifest ({"version": int, "cities": [...]}), or a fresh one."""
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("version", 1)
            d.setdefault("cities", [])
            return d
    except (OSError, ValueError):
        pass
    return {"version": 1, "cities": []}


def save_manifest(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST)


def _download(url, dest):
    print(f"downloading {url} ...")
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def _city_name(zip_path, given):
    if given:
        return given
    base = os.path.basename(zip_path)
    for suffix in (".zip", ".citygml", ".gml"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    return base or "city"


def main():
    ap = argparse.ArgumentParser(description="Install a PLATEAU city's buildings into BeamNG.Earth")
    ap.add_argument("zip", nargs="?", help="the PLATEAU CityGML zip (omit with --url or --list)")
    ap.add_argument("--url", help="download the zip from this URL first")
    ap.add_argument("--name", help="the city's name in the manifest (default: the zip's file name)")
    ap.add_argument("--out-dir", default=DATA_DIR, help=f"the per-cell output directory (default: {DATA_DIR})")
    ap.add_argument("--no-manifest", action="store_true",
                    help="convert only: do not bump plateau_data/manifest.json's version")
    ap.add_argument("--list", action="store_true", help="list the installed cities and exit")
    args = ap.parse_args()

    if args.list:
        d = load_manifest()
        print(f"PLATEAU data version {d['version']} ({len(d['cities'])} cities) under {DATA_DIR}")
        for c in d["cities"]:
            print(f"  {c.get('name', '?'):24} {c.get('buildings', '?'):>8} buildings  "
                  f"{c.get('cells', '?'):>4} cells  {c.get('installed', '')}")
        return 0

    if not args.zip and not args.url:
        ap.error("a zip path, --url, or --list is needed")

    tmp = None
    try:
        zip_path = args.zip
        if args.url:
            fd, tmp = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            zip_path = _download(args.url, tmp)
        if not os.path.isfile(zip_path):
            ap.error(f"no such file: {zip_path}")

        print(f"converting {zip_path} ...")
        feats = conv.convert_zip(zip_path)
        if not feats:
            print("no building footprints found: is this a PLATEAU CityGML zip with udx/bldg/*.gml?",
                  file=sys.stderr)
            return 1
        cells = conv.split_by_cell(feats, args.out_dir)
        print(f"{len(feats)} buildings -> {cells} cells under {args.out_dir}")

        if args.no_manifest:
            print("(--no-manifest: the data version was not bumped)")
            return 0

        d = load_manifest()
        name = _city_name(zip_path, args.name)
        d["cities"] = [c for c in d["cities"] if c.get("name") != name]
        d["cities"].append({
            "name": name,
            "zip": os.path.basename(zip_path),
            "buildings": len(feats),
            "cells": cells,
            "installed": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        d["version"] = int(d.get("version", 1)) + 1
        save_manifest(d)

        print(f"installed '{name}': PLATEAU data version {d['version']} "
              f"(the server rebuilds the affected map cells on its next start)")
        return 0
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
