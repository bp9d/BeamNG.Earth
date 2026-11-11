# PLATEAU データ活用ガイド（BeamNG.Earth 日本プロバイダ）

このドキュメントは、PLATEAU（国土交通省 Project PLATEAU）の 3D 都市モデルを BeamNG.Earth の
日本向けデータソースとして活用するための**調査結果・利用可能情報・実装計画**をまとめたものです。
実装エージェントは、コードを書く前にここを参照してください。

- 対象: 日本国内のタイル（GSI 標高を使う地域）
- 現状: PLATEAU は**建物（`udx/bldg`）のみ**取り込み済み。道路ネットワーク（`udx/tran`）は未対応。
- 目的:
  1. GSI 裸地 DTM では取れない**構造物の高さ**（橋のデッキ、トンネル床面）を PLATEAU から補い、
     トンネル坑口の急坂・立体交差の沈下を直す。
  2. PLATEAU の**車線情報**を使い、車線数・幅・方向・歩道をより正確に描画する。
  3. 交差点・幅・地物など、その他の利用可能データを洗い出す。

---

## 1. PLATEAU データの全体像

### 1.1 配布形式

PLATEAU の各都市の「3D都市モデル」は **CityGML 2.0**（i-UR 1.4 拡張）の zip で配布されます。
zip の中は `udx/<パッケージ>/` に分かれています。

| パッケージ | 内容 | BeamNG.Earth での利用 |
|---|---|---|
| `bldg` | 建物（フットプリント・高さ・階数・屋根形状） | **利用中**（[`plateau_layer.py`](EJapan/plateau_layer.py:1)） |
| `tran` | 交通（道路・車線・歩道・交差点・鉄道） | **本ドキュメントの主対象** |
| `dem` | 数値標高モデル（地形メッシュ） | 地形補正の候補（GSI と比較） |
| `luse` | 土地利用 | 都市判定・地表種別の補助 |
| `frn` | 都市設備（標識・街灯・ベンチ等） | 標識・街灯の候補 |
| `veg` | 植生（樹木） | 樹木配置の候補 |
| `uro` | 都市計画情報 | 補助 |
| `brid` / `tunnel` | 橋梁・トンネル（都市による） | 構造物高さの直接ソース候補 |

> **重要**: PLATEAU は**都市ごとのデータ**で全国カバレッジではありません。`tran` が入っていない都市、
> 古い年度でスキーマが異なる都市もあります。必ず「データがあるセルだけ使う」フォールバック設計にします。

### 1.2 座標系

- 2024 年版の多くは **EPSG:6697（JGD2011 地理座標、lat/lon 度）**、`srsDimension=3`。
  各点は `lat lon height` の順（CityGML の `gml:posList`）。
- 一部の都市・年度は**平面直角座標系**（EPSG:6670 系）の場合があります。変換が必要。
- 既存の [`plateau_converter.py`](EJapan/plateau_converter.py:20) は EPSG:6697 前提で、
  `_poslist_to_ring()` が `lat lon height` を読み `(lon, lat)` に落としています。
  **高さ（3 次元目）を捨てている**点が、道路高さ補正では問題になります。

### 1.3 既存の取り込み経路

- 変換: [`plateau_converter.py`](EJapan/plateau_converter.py:120) の `convert_zip()` が
  `udx/bldg/*.gml` のみを読み、`_building_feature()` で GeoJSON 化。
- 分割: [`split_by_cell()`](EJapan/plateau_converter.py:156) が z14 セル単位で
  `EJapan/plateau_data/<z>/<x>/<y>.json.gz` に書き出し。
- 実行時: [`plateau_layer.py`](EJapan/plateau_layer.py:1) の
  `load_and_merge_plateau_buildings()` が [`mapdata.py`](server/mapdata.py:771) から呼ばれ、
  Overture の建物とマージ。
- バージョン: [`install_city.py`](EJapan/install_city.py:1) が `manifest.json` の version を上げ、
  [`mapdata.versions()`](server/mapdata.py:364) 経由でキャッシュを再生成。

**道路ネットワークも同じ経路（変換 → per-cell 出力 → 実行時ロード → versions で再生成）に乗せます。**

---

## 2. tran（交通）データの詳細

### 2.1 CityGML 標準の交通クラス

PLATEAU の `tran` は CityGML Transportation モジュールに準拠します。主な要素:

| 要素 | 意味 | 主な属性・子要素 |
|---|---|---|
| `tran:Road` | 道路（交通領域の集合） | `gml:name`, `tran:function`（道路種別）, `tran:width`, `tran:lod1MultiSurface` など |
| `tran:TrafficArea` | 交通領域（車道・歩道などの面） | `tran:function`（車道 / 歩道 / 自転車道 / 路面電車 など）, `tran:width`, `tran:lod1/2/3MultiSurface` |
| `tran:AuxiliaryTrafficArea` | 補助交通領域（中央分離帯・植栽帯など） | `tran:function`, `tran:width`, 面ジオメトリ |
| `tran:Intersection` | 交差点（PLATEAU 拡張） | 交差点の面・接続道路 |
| `tran:Railway` / `tran:Track` | 鉄道・軌道 | 線形ジオメトリ |

- `tran:function` の値（例）: `車道`, `歩道`, `自転車道`, `路面電車`, `その他`。
  日本語文字列なので、変換時に正規化したコード（`road` / `sidewalk` / `cycleway` / `tram`）へ落とす。
- `tran:width` はメートル。車線幅・道路幅の直接ソースになる。
- ジオメトリは `gml:MultiSurface` の `gml:Polygon` → `gml:exterior` → `gml:LinearRing` →
  `gml:posList`。**3 次元（lat lon height）なら面の高さがそのまま入っている**。
  これが GSI 裸地 DTM に無い「橋のデッキ面」「トンネル床面」の高さです。

### 2.2 PLATEAU RoadNetwork 拡張（車線・交差点）

PLATEAU SDK for Unity の RoadNetwork 機能は、`tran` データから**道路ネットワーク**を構築します。
マニュアル（[RoadNetwork](https://project-plateau.github.io/PLATEAU-SDK-for-Unity/manual/RoadNetwork.html)）が
扱う概念:

- **RoadNetwork**: 道路ネットワーク全体
- **Road**: 道路リンク（始点・終点ノードを持つ区間）
- **Lane**: 車線。幅・進行方向・車線種別を持つ
- **Intersection**: 交差点。接続する道路と車線の関係

> **要確認**: 車線・交差点が CityGML のどの要素名（`tran:` 拡張か `uro:` 拡張か、別 GML か）で
> 格納されているかは、都市・年度で異なる可能性があります。**実装前に §2.3 のプローブで実データを
> 確認してください。** 本ドキュメントでは「あれば使う」設計にします。

### 2.3 実データ確認プローブ

以下を `EJapan/probes/plateau_tran_probe.py` として保存し、インストール済み zip に対して実行します
（Architect モードでは `.py` を作れないため、ここに収録。Code モードで切り出してください）。

```python
#!/usr/bin/env python3
"""Inspect a PLATEAU CityGML zip's transportation (tran) data.

    python EJapan/probes/plateau_tran_probe.py EJapan/plateau/<city>.zip
    python EJapan/probes/plateau_tran_probe.py EJapan/plateau/<city>.zip --gml udx/tran/12345_tran.gml

Prints: which udx packages exist; which tran GML files exist; which CityGML /
PLATEAU element names appear (tran:Road, tran:TrafficArea, tran:AuxiliaryTrafficArea,
tran:Intersection, lane / RoadNetwork extensions); the attributes each carries;
the coordinate dimensionality (2D vs 3D: does the data carry heights?); samples.
Standard library only; writes no files.
"""
import argparse
import collections
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "gml": "http://www.opengis.net/gml",
    "core": "http://www.opengis.net/citygml/2.0",
    "tran": "http://www.opengis.net/citygml/transportation/2.0",
    "uro": "http://www.opengis.net/citygml/urbanobject/2.0",
    "gen": "http://www.opengis.net/citygml/generics/2.0",
    "dem": "http://www.opengis.net/citygml/relief/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "luse": "http://www.opengis.net/citygml/landuse/2.0",
    "frn": "http://www.opengis.net/citygml/cityfurniture/2.0",
    "veg": "http://www.opengis.net/citygml/vegetation/2.0",
}


def _local(tag):
    if tag.startswith("{"):
        uri, _, name = tag[1:].partition("}")
        for prefix, ns in NS.items():
            if uri == ns:
                return f"{prefix}:{name}"
        return name
    return tag


def _packages(names):
    out = collections.defaultdict(list)
    for n in names:
        parts = n.replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[0] == "udx":
            out[parts[1]].append(n)
        elif n.lower().endswith((".gml", ".xml")):
            out["(other)"].append(n)
    return out


def _poslist_dims(text):
    vals = text.split()
    n = len(vals)
    if n == 0:
        return 0, 0
    for dims in (3, 2):
        if n % dims == 0:
            return n // dims, dims
    return n, 1


def _report_gml(z, name, max_samples=3):
    try:
        root = ET.fromstring(z.read(name))
    except ET.ParseError as e:
        print(f"  !! parse error: {e}")
        return
    tags = collections.Counter()
    attrs = collections.defaultdict(collections.Counter)
    dims = collections.Counter()
    samples = collections.defaultdict(list)
    for el in root.iter():
        t = _local(el.tag)
        tags[t] += 1
        for k, v in el.attrib.items():
            attrs[t][_local(k)] += 1
        if t in ("gml:posList", "gml:pos") and el.text:
            if t == "gml:posList":
                n, d = _poslist_dims(el.text)
                dims[d] += 1
            else:
                dims[len(el.text.split())] += 1
        if t in ("tran:function", "tran:width", "gml:name", "core:creationDate",
                 "uro:lane", "tran:Intersection", "tran:Road", "tran:TrafficArea",
                 "tran:AuxiliaryTrafficArea") and len(samples[t]) < max_samples:
            txt = (el.text or "").strip()
            if txt:
                samples[t].append(txt)
    print(f"  elements ({len(tags)} kinds):")
    for t, c in tags.most_common():
        if t.startswith(("tran:", "uro:", "gen:", "core:", "gml:")) or "lane" in t.lower() \
                or "intersection" in t.lower() or "road" in t.lower():
            print(f"    {t:40} {c}")
    print(f"  coordinate dimensions: {dict(dims)}  (3 = lat/lon/height, 2 = lat/lon)")
    for t, vals in samples.items():
        print(f"  sample {t}: {vals}")
    for t in ("tran:Road", "tran:TrafficArea", "tran:AuxiliaryTrafficArea", "tran:Intersection"):
        if attrs.get(t):
            print(f"  attributes of {t}: {dict(attrs[t])}")


def main():
    ap = argparse.ArgumentParser(description="Inspect a PLATEAU zip's tran data")
    ap.add_argument("zip")
    ap.add_argument("--gml")
    ap.add_argument("--max-files", type=int, default=3)
    args = ap.parse_args()
    if not os.path.isfile(args.zip):
        ap.error(f"no such file: {args.zip}")
    with zipfile.ZipFile(args.zip) as z:
        names = z.namelist()
        pkgs = _packages(names)
        print(f"{args.zip}: {len(names)} members")
        print("packages:")
        for p in sorted(pkgs):
            gmls = [n for n in pkgs[p] if n.lower().endswith(".gml")]
            print(f"  {p:10} {len(pkgs[p]):5} members, {len(gmls):4} .gml")
        tran = [n for n in pkgs.get("tran", []) if n.lower().endswith(".gml")]
        if not tran:
            print("\nNO udx/tran/*.gml: this city has no transportation data.")
            return 0
        print(f"\ntran GML files: {len(tran)}")
        for n in tran[:10]:
            print(f"  {n}  ({z.getinfo(n).file_size / 1e6:.1f} MB)")
        if len(tran) > 10:
            print(f"  ... and {len(tran) - 10} more")
        todo = [args.gml] if args.gml else tran[:max(1, args.max_files)]
        for n in todo:
            if n not in names:
                print(f"\n!! not in the zip: {n}")
                continue
            print(f"\n--- {n} ---")
            _report_gml(z, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**確認すべき項目**:

1. `udx/tran/*.gml` が存在するか（都市による）。
2. `gml:posList` が 3 次元か（高さを持つか）。→ 高さ補正の可否。
3. `tran:TrafficArea` の `tran:function` に `車道` / `歩道` があるか。→ 車道面・歩道面の分離。
4. `tran:width` があるか。→ 幅の直接ソース。
5. 車線・交差点の要素名（`tran:Intersection`、`uro:*lane*` など）。→ 車線描画の可否。
6. 座標系（EPSG:6697 か平面直角か）。

---

## 3. BeamNG.Earth で利用できる情報

| PLATEAU の情報 | 用途 | 対応する既存モジュール | 優先度 |
|---|---|---|---|
| `TrafficArea` の 3D 面（車道） | **道路面の高さ**（橋・トンネル・通常区間） | [`grading.py`](server/grading.py:1), [`carriageways.py`](server/carriageways.py:1), [`crossings.py`](server/crossings.py:1) | **高** |
| `TrafficArea` の `tran:width` | 道路幅・車線幅 | [`roads.py`](server/roads.py:2027) `road_specs`, [`roadwidth.py`](server/roadwidth.py:1) | 高 |
| `TrafficArea` の `tran:function` | 車道 / 歩道 / 自転車道の区別 | [`sidewalks.py`](server/sidewalks.py:1), [`roads.py`](server/roads.py:1) | 高 |
| `AuxiliaryTrafficArea` | 歩道・中央分離帯・植栽帯 | [`sidewalks.py`](server/sidewalks.py:1), [`medians.py`](server/medians.py:1) | 中 |
| 車線（Lane）の幅・方向・種別 | **車線描画**（車線数・境界・進行方向） | [`roadlanes.py`](server/roadlanes.py:1), [`markings.py`](server/markings.py:120), [`roadmesh.py`](server/roadmesh.py:1) | 高 |
| `Intersection` | 交差点形状・停止線・横断歩道 | [`junctions.py`](server/junctions.py:1), [`markings.py`](server/markings.py:315) | 中 |
| `Road` の `tran:function` | 道路種別（高速 / 国道 / 県道…） | [`roads.py`](server/roads.py:1) の class 補正 | 中 |
| `dem`（地形メッシュ） | 高解像度地形（GSI との比較・補完） | [`dem.py`](server/dem.py:305) `_japan` | 低〜中 |
| `frn`（都市設備） | 標識・街灯・ベンチ | [`signs.py`](server/signs.py:1), [`furniture.py`](server/furniture.py:1) | 低 |
| `veg`（植生） | 樹木 | [`trees.py`](server/trees.py:1) | 低 |
| `luse`（土地利用） | 都市判定・地表 | [`covermap.py`](server/covermap.py:1) | 低 |

### 3.1 高さ補正の考え方（最重要）

現状の問題:

- GSI 標高は**裸地 DTM**。橋のデッキ面・トンネル上の地面・トンネル床面が含まれない。
- [`grading.py`](server/grading.py:1) は DEM を読んで道路プロファイルを作るため、構造物の上下が混ざる。
- [`crossings.py`](server/crossings.py:1) の立体交差ソルバは「トンネル計画が上の道路を引っ張る」問題には効いたが、
  **坑口そのものの高さ**（GSI 裸地 DTM と実際のトンネル床面の差）は解決していない。

PLATEAU の `TrafficArea` 3D 面は、まさにこの「実際の道路面の高さ」を持ちます。これを
**道路プロファイルの信頼できる高さ（trusted height）**として使います。

- 通常区間: `TrafficArea` の面高さを DEM より優先。
- 橋: デッキ面の高さを [`BridgeProfiles`](server/roads.py:5762) のピンに使う。
- トンネル: 坑口付近の床面高さを [`TunnelProfiles`](server/roads.py:6471) のポータル高さに使う。
- 立体交差: [`crossings.solve()`](server/crossings.py:94) の `deck` / `low` に PLATEAU 高さを渡す。

**地形（terrain）には適用しない**こと。橋の下の地面をデッキ高さに上げてはいけません。
あくまで「道路計画の高さ」に使います。

### 3.2 車線描画の考え方

現状は OSM の `lanes` / `turn:lanes` / `width` から車線を推定しています
（[`roadlanes.py`](server/roadlanes.py:1), [`markings.lane_plan()`](server/markings.py:120)）。
PLATEAU の車線情報があれば、以下を上書き・補強できます。

- 車線数（`lanes`）
- 車線幅（`tran:width` / Lane の幅）
- 進行方向（一方通行か、上下線の分離）
- 車線境界の位置（正確なオフセット）
- 歩道・自転車道の有無と幅

ただし PLATEAU の道路と Overture の道路は**ジオメトリが一致しない**ため、
「近傍・重なりでマッチング → 一致した道路だけ上書き」という設計にします。

---

## 4. 既存アーキテクチャとの対応

### 4.1 データの流れ（現状）

```
PLATEAU zip
  └─ plateau_converter.py (udx/bldg のみ)
       └─ plateau_data/<z>/<x>/<y>.json.gz
            └─ plateau_layer.py (建物)
                 └─ mapdata.py _decoded_layer (buildings)
                      └─ buildings.py
```

### 4.2 データの流れ（追加後）

```
PLATEAU zip
  ├─ plateau_converter.py (udx/bldg)  ── 既存
  └─ plateau_converter.py (udx/tran)  ── 追加
       └─ plateau_data/<z>/<x>/<y>.roads.json.gz
            └─ plateau_roads.py (新規: 高さ・車線・幅・歩道)
                 ├─ grading.py / carriageways.py / crossings.py  (高さ補正)
                 ├─ roads.py / roadlanes.py / markings.py        (幅・車線)
                 └─ sidewalks.py / medians.py                    (歩道・分離帯)
```

### 4.3 キャッシュとバージョン

- [`mapdata.versions()`](server/mapdata.py:364) に `plateau` の version が入っています。
  `tran` の変換を追加したら **`manifest.json` の version を上げる**（[`install_city.py`](EJapan/install_city.py:1)）。
- 道路計画のキャッシュキーは [`plancache.py`](server/plancache.py:92) が持つ。
  PLATEAU 高さを使うようになったら、キーに PLATEAU の有無・version を含める。

---

## 5. 実装計画

### Phase 0: 調査と変換パイプライン

**目的**: `udx/tran` を per-cell の軽量データに変換する。

1. `EJapan/probes/plateau_tran_probe.py` を作成し、インストール済み zip で実行。
   §2.3 の確認項目を埋める。
2. [`plateau_converter.py`](EJapan/plateau_converter.py:120) に `convert_tran_zip(zip_path)` を追加。
   - `udx/tran/*.gml` を読む。
   - `tran:Road` / `tran:TrafficArea` / `tran:AuxiliaryTrafficArea` / `tran:Intersection` を抽出。
   - 3D 座標（lat, lon, height）を保持。
   - `tran:function` を正規化コードへ（`road` / `sidewalk` / `cycleway` / `tram` / `other`）。
   - 車線・交差点要素があれば抽出。
3. `split_tran_by_cell()` を追加し、`plateau_data/<z>/<x>/<y>.roads.json.gz` に書き出す。
   出力スキーマ（案）:

   ```json
   {
     "roads": [
       {"id": "...", "class": "motorway", "width": 12.0,
        "line": [[lon, lat, z], ...]}
     ],
     "surfaces": [
       {"id": "...", "road_id": "...", "function": "road", "width": 12.0,
        "polygon": [[lon, lat, z], ...]}
     ],
     "lanes": [
       {"id": "...", "road_id": "...", "width": 3.5, "direction": "forward",
        "type": "through", "line": [[lon, lat, z], ...]}
     ],
     "intersections": [
       {"id": "...", "polygon": [[lon, lat, z], ...], "roads": ["..."]}
     ]
   }
   ```

4. [`install_city.py`](EJapan/install_city.py:1) を拡張し、`tran` も変換・manifest 更新。
5. 変換結果の統計（道路数・面数・車線数・3D か）を manifest に記録。

**完了条件**: 福岡・宗像の zip から `roads.json.gz` が生成され、プローブで 3D 座標と
`tran:function` が確認できる。

### Phase 1: 高さ補正（最優先）

**目的**: トンネル坑口の急坂・立体交差の沈下を、PLATEAU 道路面の高さで直す。

1. `EJapan/plateau_roads.py` を新規作成。
   - `has_data(key)` / `load(key)`（per-cell、キャッシュ付き）。
   - `height_at(lat, lon)` → 道路面の補間高さ（`TrafficArea` の 3D 面から）。
   - `profile(line)` → ポリラインに沿った高さ配列。
   - `surface_kind(lat, lon)` → `road` / `sidewalk` / `cycleway`。
   - `match(feats, i)` → Overture 道路フィーチャとのマッチング（近傍・重なり）。
2. [`grading.py`](server/grading.py:1) の道路プロファイル生成に、PLATEAU 高さのフックを追加。
   - `_Planner` の DEM サンプリング箇所で、PLATEAU 面があればその高さを優先。
   - 端では DEM へフェザリング（急な段差を避ける）。
   - **地形には適用しない**（道路計画のみ）。
3. [`roads.py`](server/roads.py:5762) `BridgeProfiles` のデッキ高さに PLATEAU 面高さをピンとして渡す。
4. [`roads.py`](server/roads.py:6471) `TunnelProfiles` のポータル床面高さに PLATEAU 面高さを渡す。
5. [`crossings.py`](server/crossings.py:94) `solve()` の `deck` / `low` に PLATEAU 高さを渡す。
6. [`plancache.py`](server/plancache.py:92) のキーに PLATEAU の有無・version を追加。

**完了条件**: 岡垣周辺（33.82544 N, 130.60710 E）で、トンネル坑口の前後が滑らかにつながり、
立体交差の道路が沈まない。PLATEAU データが無いセルは従来通り。

### Phase 2: 車線・幅・歩道

**目的**: PLATEAU の車線・幅・歩道情報で描画を補強する。

1. [`roadlanes.py`](server/roadlanes.py:1) に PLATEAU 車線の証拠を追加。
   - `match()` で一致した道路だけ、車線数・幅・方向を上書き。
   - OSM タグより PLATEAU を優先するかは設定で切替（`BNE_PLATEAU_LANES`）。
2. [`markings.lane_plan()`](server/markings.py:120) に PLATEAU の車線境界オフセットを渡せるようにする。
3. [`roads.road_specs()`](server/roads.py:2027) の幅に `tran:width` を反映。
4. [`sidewalks.py`](server/sidewalks.py:1) に `AuxiliaryTrafficArea`（歩道）の幅・有無を反映。
5. [`medians.py`](server/medians.py:1) に中央分離帯の情報を反映（あれば）。

**完了条件**: PLATEAU 収録都市で、車線数・幅・歩道が OSM 推定より正確になる。
未収録地域は従来通り。

### Phase 3: 交差点・その他

1. `Intersection` から交差点形状・停止線・横断歩道を補強
   （[`junctions.py`](server/junctions.py:1), [`markings.py`](server/markings.py:315)）。
2. `Road` の `tran:function` で道路種別を補正（[`roads.py`](server/roads.py:1) の class）。
3. 余力があれば `frn`（標識・街灯）、`veg`（樹木）、`dem`（地形）を検討。

### Phase 4: テスト・検証

1. 変換テスト: `EJapan/tests/test_plateau_tran.py`
   - サンプル GML → `roads.json.gz` のスキーマ。
   - 3D 座標の保持。
   - `tran:function` の正規化。
2. 高さ補正テスト: `server/tests/test_grading.py` に追加。
   - PLATEAU 高さがある道路で、プロファイルが PLATEAU 面に一致する。
   - 地形は変わらない。
   - データが無い場合は従来通り。
3. 車線テスト: `server/tests/test_roadlanes.py`（新規 or 既存）。
   - PLATEAU 車線が OSM より優先される。
4. 回帰: 岡垣のトンネル坑口・立体交差。
5. ベンチマーク: 福岡・宗像で道路タイル生成時間を計測。

---

## 6. 具体的な変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `EJapan/probes/plateau_tran_probe.py` | 新規（§2.3 のプローブ） |
| `EJapan/plateau_converter.py` | `convert_tran_zip()`, `split_tran_by_cell()` 追加 |
| `EJapan/install_city.py` | `tran` 変換と manifest 記録 |
| `EJapan/plateau_roads.py` | 新規（高さ・車線・幅・歩道の実行時ロード） |
| `EJapan/plateau_layer.py` | 変更なし（建物） |
| `server/grading.py` | 道路プロファイルに PLATEAU 高さフック |
| `server/carriageways.py` | チェーン解法に PLATEAU 高さを反映 |
| `server/crossings.py` | `solve()` に PLATEAU 高さを渡す |
| `server/roads.py` | `BridgeProfiles` / `TunnelProfiles` のピン、`road_specs` の幅 |
| `server/roadlanes.py` | PLATEAU 車線の証拠 |
| `server/markings.py` | `lane_plan()` に PLATEAU 車線境界 |
| `server/sidewalks.py` | `AuxiliaryTrafficArea` の歩道 |
| `server/medians.py` | 中央分離帯 |
| `server/plancache.py` | キャッシュキーに PLATEAU version |
| `server/mapdata.py` | `versions()` に `tran` version（既存の `plateau` を拡張） |
| `server/credits.py` | PLATEAU のクレジット（既存） |
| `CHANGELOG.md` | 変更履歴 |

---

## 7. リスク・制約

| リスク | 影響 | 対策 |
|---|---|---|
| PLATEAU は都市単位で全国未収録 | 多くの地域で使えない | データがあるセルだけ適用。無ければ GSI/Overture にフォールバック |
| `tran` が無い都市・年度がある | 道路ネットワークが使えない | プローブで確認。無ければ Phase 1 をスキップ |
| スキーマが都市・年度で異なる | 変換が壊れる | 要素名・名前空間を柔軟に。プローブで実データ確認 |
| 座標系が EPSG:6697 でない場合 | 位置ずれ | 平面直角座標系の変換を実装（`pyproj` は使わず自前 or 既存 `geodesy`） |
| PLATEAU と Overture の道路が一致しない | 誤った上書き | 近傍・重なり・方向でマッチング。閾値を保守的に |
| データ量が大きい | 変換・ロードが遅い | per-cell 分割、必要な面だけ、キャッシュ |
| 高さを地形に適用してしまう | 橋の下が盛り上がる | **道路計画のみ**に適用。地形は DEM のまま |
| ライセンス・クレジット | 利用条件違反 | PLATEAU のクレジット表示（既存 [`credits.py`](server/credits.py:109)） |
| パフォーマンス | 道路タイル生成が遅くなる | セル単位ロード、ワーカープロセスで共有、ベンチマーク |

---

## 8. 参考リンク

- PLATEAU 公式: <https://www.mlit.go.jp/plateau/>
- PLATEAU 学習コンテンツ（道路）: <https://www.mlit.go.jp/plateau/learning/tpc03-1/>
- PLATEAU SDK for Unity — RoadNetwork:
  <https://project-plateau.github.io/PLATEAU-SDK-for-Unity/manual/RoadNetwork.html>
- PLATEAU オープンデータ: <https://www.mlit.go.jp/plateau/opendata/>
- 既存の日本プロバイダ計画: [`EJapan/EJ_PLAN.md`](EJapan/EJ_PLAN.md:1)
- 既存の建物取り込み: [`EJapan/plateau_layer.py`](EJapan/plateau_layer.py:1)

---

## 9. 実装エージェントへの指示

1. **最初に §2.3 のプローブを実行**し、実データのスキーマを確認する。
   - `udx/tran` の有無、3D 座標、`tran:function`、車線・交差点要素。
2. 確認結果をこのドキュメントの §2.1 / §2.2 に追記してから実装に入る。
3. **Phase 1（高さ補正）を最優先**。これがユーザー報告（トンネル坑口の急坂・立体交差の沈下）に直結する。
4. 高さは**道路計画のみ**に使い、地形には使わない。
5. データが無いセルは必ず従来動作にフォールバックする。
6. 各 Phase の完了条件を満たしたら、テストと CHANGELOG を更新する。
