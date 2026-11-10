# BeamNG.Earth Japan Provider Extension - Implementation Plan (EJ_PLAN)

日本国内のタイルに対して、デフォルトのグローバルデータソースの代わりに **GSI（国土地理院）のシームレス写真・標高タイル** と **PLATEAU 3D 都市モデル** を適用する実装計画。

実装方式は**データソース追加方式**（ポルトガル独自オルソ `pt_dgt2021`/`pt_dgt2018` の先例に倣う）。プラグイン機構は不要。

---

## 1. 現行アーキテクチャの要点

- **地域別オルソ**: [`imagery_regional.py`](server/imagery_regional.py:33) の `REGIONAL` dict にエントリを追加 → [`imagery.py`](server/imagery.py:189) が `Source` 化し `DEFAULT_CHAIN` に自動で組み込む（xyz 系は `max_zoom=17, min_zoom=REGIONAL_XYZ_MIN_ZOOM=16`、WMS export 系は `lazy=True` で z15 親を 1024px 取得）
- **地域別標高**: [`dem.py`](server/dem.py:264) の `_canada()` → `hrdem.py` / `lidarbc.py` と同様の地域フックを追加
- **netfetch ポリシー**: [`netfetch.py`](server/netfetch.py:291) の `_regional_policies()` が `REGIONAL` から自動導出（xyz: rate=6.0, burst=20, max_conc=4, daily_budget=20000 / export: rate=1.0, max_conc=1, daily_budget=4000）→ **追加設定不要**
- **worker プロセス**: 1.8 以降、全 worker（block / photo / far tile / road / far building）が自前の `Dem` / `Imagery` を構築するが、`REGIONAL` はモジュール読み込み時に登録されるため全プロセスに届く
- **add-ons 機能（1.9.0-beta）**: ゲーム MOD / コンパニオンプログラムの GitHub からのインストール・管理であり、サーバー側のデータソース拡張とは目的が異なる。**データソース拡張に add-ons は使わない**

---

## 2. GSI タイルの仕様（実測で確定）

### 2.1 座標系: Web Mercator (EPSG:3857)

GSI の全タイル（seamlessphoto / dem*_png）は **Web Mercator の XYZ タイル**。実測で確定（[`EJapan/probes/gsi_bruteforce.py`](EJapan/probes/gsi_bruteforce.py:1)）:

```
seamlessphoto z16  x=58211  (window 5x5 = 25 tiles)
  WEB_MERCATOR  y= 25806  -> 25/25 are 200
  EPSG4326      y= 19776  ->  0/25 are 200
```

→ **座標変換は不要**。既存の [`imagery_regional.py`](server/imagery_regional.py:121) の japan エントリ（xyz タイプ）は正しく動作している。

### 2.2 標高タイル: `dem*_png` サービス

旧 `dem5a`/`dem5b`/`dem10b` の PNG 形式は **2025-03-31 で廃止**。現行は `*_png` 形式（GSI タイル一覧ページで確認、[`EJapan/probes/gsi_dem_spec3_out.txt`](EJapan/probes/gsi_dem_spec3_out.txt:3)）:

| サービス | URL | メッシュ | ズーム |
|---|---|---|---|
| DEM1A | `https://cyberjapandata.gsi.go.jp/xyz/dem1a_png/{z}/{x}/{y}.png` | 1 m | 1〜17 |
| DEM5A | `https://cyberjapandata.gsi.go.jp/xyz/dem5a_png/{z}/{x}/{y}.png` | 5 m | 1〜15 |
| DEM5B | `https://cyberjapandata.gsi.go.jp/xyz/dem5b_png/{z}/{x}/{y}.png` | 5 m | 1〜15 |
| DEM5C | `https://cyberjapandata.gsi.go.jp/xyz/dem5c_png/{z}/{x}/{y}.png` | 5 m | 1〜15 |
| DEM10B | `https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png` | 10 m | 1〜14 |

- タイルサイズ: 256 px、**Web Mercator の XYZ タイル**
- テキスト形式（`dem5a`/`dem5b`/`dem` の `.txt`）は令和6年10月より更新停止
- データソース: 基盤地図情報数値標高モデルを線形的に平滑化

**デコード式（符号付き 24bit、公式仕様）**:

```
x = 2^16*R + 2^8*G + B
x < 2^23  →  h = x * 0.01          # 正の標高 (0 〜 83886.07 m)
x = 2^23  →  NA（無効値）
x > 2^23  →  h = (x - 2^24) * 0.01  # 負の標高（海抜下）
無効値: (R, G, B) = (128, 0, 0)
```

**BeamNG.Earth 側の DEM グリッドとの差異**: 両方 Web Mercator なので**座標変換は不要**。**リサンプリング（256→512 px）+ デコード**の 2 段階のみ。

**1.8 以降の注意**: 地形ラティスが 2 m から **1 m** に変わった（[`heightmap.py`](server/heightmap.py:37): `SIZE=1024, SQUARE=1.0`。far field の近傍タイルは [`FAR_SQUARE = 2.0`](server/heightmap.py:39) のまま）。dem の 512px グリッド上、GSI 5m メッシュは 35°N で z15 が ~2 m/px、z13 が ~8 m/px 相当。近傍地形は z16（`FINE_ZOOM`）で読むが GSI DEM5A は z15 までなので、**z15 親からのアップサンプル**が必要（dem.py の AWS z16 扱いと同様）。

### 2.3 PLATEAU

- PLATEAU CityGML は建物フットプリント + 高さ情報（`measuredHeight`, `roofType` 等）を持つ
- **統合方法**: オフライン前処理で CityGML → Overture 互換のフットプリント + 高さ属性に変換し、`mapdata.py` の buildings レイヤーに**高さ情報を注入**（`plan()` の既存ロジックを活用、deterministic generation を維持）
- 案 C: 3dmr.eu ベイク経路（[`threedmr.py`](server/threedmr.py:1)）を模した静的アセット化 — ランドマーク限定
- **注意**: PLATEAU は都市ごとにデータが分かれており全国カバレッジではない。データソースとしての追加（地域限定）は許容されるが、建物生成ロジックの分岐は避ける
- **注意（1.8）**: `buildings.plan()` は road worker プロセス内で実行される（[`blockworker.roads_tile`](server/blockworker.py:157)）。マージした buildings レイヤーを worker 各自の `mapdata` インスタンスに通す設計が必要

---

## 3. 実装計画

### Phase 0: GSI シームレス写真のズーム調整（`imagery_regional.py` + `imagery.py` + `netfetch.py`）

- **対象**: [`imagery_regional.py`](server/imagery_regional.py:121) の japan エントリ
- **作業**:
  1. `REGIONAL` のエントリ構造を **5 タプル → 6 タプル** `(url, attribution, bounds, kind, leaf_off, max_zoom)` に拡張（既存エントリは末尾に `17` を追加、japan だけ `18`）。`REGIONAL` は [`imagery.py`](server/imagery.py:189) の `Source` 生成と [`netfetch.py`](server/netfetch.py:295) の `_regional_policies()` の両方で unpack されるため、**両方の unpack を更新**する（`credits.py` の `IMAGERY.update({n: v[1] ...})` は `v[1]` 参照なので影響なし）
  2. `imagery.py` の `Source` 生成で `max_zoom=_max_zoom or 17` を使用（xyz 系のみ。export 系は従来通り 17）
  3. `min_zoom` は `REGIONAL_XYZ_MIN_ZOOM (16)` のまま（far ring の z16 挙動との整合。z15 開始は他地域との整合を確認してから）
- **検証**: 福岡（33.59, 130.40）・東京で z16〜z18 の写真が正しい位置に表示されるか。far ring（z16）とベース写真が worker プロセスでも正しくレンダリングされること

### Phase 1: GSI 標高プロバイダー（`EJapan/gsidem.py` + dem.py の地域フック）

- **方針**: [`hrdem.py`](server/hrdem.py:108) の `Hrdem` クラスと同様の「dem.py のグリッドでタイルを返す」モジュールとして実装
- **作業**:
  1. `EJapan/gsidem.py` を新規作成
     - `GsiDem` クラス: `tile(z, x, y) -> (heights float32 [512, 512], valid bool [512, 512])`
     - 内部処理: Web Mercator タイル（**座標変換不要**）→ 256px タイル取得 → **符号付き 24bit デコード**（§2.2）→ 512px へリサンプリング（`dem._resize` 相当）
     - フォールバック: `dem5a_png` → `dem_png`（DEM10B）→ なし（Mapterhorn にフォールバック）
     - z16 は GSI DEM5A が z15 までなので、**z15 親タイルを 2x アップサンプル**して供給（`dem._from_ancestor` 相当）
     - `covers(z, x, y)`: 日本 BBox `(24.0, 122.9, 45.6, 146.0)` でタイル単位判定（`hrdem.covers` と同様）
     - **ネットワークは必ず `netfetch.Fetcher` 経由**（モジュール固有の `urllib` 呼び出し禁止。`hrdem.py` と同様に `__init__` で fetcher を受け取り、`register_chain` で GSI ホストを登録）
  2. `dem.py` に地域プロバイダーフック `_japan()` を追加（`_canada()` と同様、デフォルト: 何もしない。`hrdem`/`lidarbc` と同様に `GsiDem` を `__init__` で生成）
     - `_make_tile`（[`dem.py`](server/dem.py:808)）を `return self._japan(key, self._canada(key, self._make_tile0(key)))` に変更（カナダと日本は重ならないのでチェーンでよい）
     - `_japan()` のロジック: `a is None or z < GLOBAL_ZOOM` なら return → `gsidem.covers()` で判定 → `gsidem.tile()` を取得 → `a[ok] = h[ok]` で上書き → `self.gsi_served.add(key)` で記録
  3. ズーム: z13 以上で適用（35°N で z15 ~2 m/px、z13 ~8 m/px 相当。近傍の z16 は z15 親のアップサンプルで供給）
  4. クレジット: `credits.py` に `dem:gsi` を追加
     - `ELEVATION` dict に `"gsi": "..."`（GSI の帰属表示）を追加
     - `SHORT` dict に `"dem:gsi": "GSI"` を追加
     - `_ids()`（[`credits.py`](server/credits.py:280)）に `if k in getattr(dem, "gsi_served", ()): ids.add("dem:gsi")` を追加（`hrdem_served`/`lidarbc_served` と同様）
- **注意**: GSI 標高は**地形モデル（DTM）相当**（建物・樹木なし）。Mapterhorn の `ground_filter` と同様の扱いでよい

### Phase 2: GSI シームレス写真の改善（Phase 0 の続き）

- **作業**:
  1. Phase 0 のズーム調整を確定（z18 の有効性を検証）
  2. `min_zoom` の調整: z15 開始も候補（GSI は z15 でも高解像度）だが、他地域との far ring 挙動（z16）との整合を確認
  3. netfetch ポリシー: **設定不要** — `_regional_policies()` が自動導出。ただし daily_budget=20000 は **DEM5A と共有**されるので、写真 + 標高の 1 日合計が 2 万以内に収まることを確認（収まらない場合は `BNE_*` 等で DEM 側の適用ズームを絞る）
- **検証**: 福岡・東京の都市部で z16〜z18 の写真が正しく表示されるか（z15 は適用判断後）

### Phase 3: PLATEAU 3D 都市モデルのプリベイク（`EJapan/plateau_converter.py`）

- **方針**: オフライン前処理で CityGML → 軽量フットプリント + 高さ属性に変換
- **作業**:
  1. `EJapan/plateau_converter.py` を新規作成
     - 入力: PLATEAU CityGML（`bldg/*.gml`）
     - 出力: GeoJSON（フットプリント + `height`, `num_floors`, `roof_type` 属性）
     - 処理: GML パース（`xml.etree` または `lxml`）→ 座標変換（JGD2011 / 平面直角座標系 → WGS84）→ 建物抽出 → 簡略化
  2. 変換結果を `mapdata.py` の buildings レイヤーに統合する方法を設計
    - 案 A: Overture の buildings レイヤーに高さ情報をマージ（推奨。`plan()` が road worker プロセスで動く点に注意）
    - 案 B: 別レイヤー `plateau_buildings` として追加（`OPTIONAL_LAYERS` 方式）
    - 案 C: 3dmr.eu ベイク経路を模した静的アセット化 — ランドマーク限定
  3. 対象エリアの選定: **福岡市**（33.59, 130.40）から開始し、首都圏へ拡大
- **注意**: PLATEAU データは都市ごとにライセンス・更新時期が異なる。クレジット表示と利用規約の確認が必要

### Phase 4: 検証とチューニング

- **作業**:
  1. **福岡市周辺**（33.59, 130.40）で標高の起伏（山と海面）が正しく描画されるか確認
  2. GSI 写真が正しい位置に表示されるか（Web Mercator なので座標変換の検証は不要。ズーム調整の検証のみ）
  3. サスペンション挙動とコリジョンの整合性テスト
  4. ベンチマーク: [`tools/benchmark.py`](tools/benchmark.py) に福岡のプレースを追加
  5. クレジット表示の確認（GSI, PLATEAU）

---

## 4. リスクと考慮事項

| リスク | 影響 | 対策 |
|---|---|---|
| GSI の利用規約（過剰リクエスト禁止） | アカウント停止・アクセス制限 | netfetch ポリシー（自動導出の `rate=6.0` 等）を厳守。キャッシュを活用 |
| GSI ホストの daily_budget 20000 が写真 + DEM 共用 | 初回訪問で `BudgetExceeded` が頻発 | 1 日合計を 2 万以内に抑える。prefetch / predownload（`Dem.predownload`, `prewarm.py`）で散らす |
| DEM のズーム整合 | 遠景と近景で標高が不連続 | Mapterhorn との境界でフェザリング（`hrdem.py` の `feather()` を流用） |
| PLATEAU データのライセンス | クレジット表示義務 | 都市ごとのライセンス確認とクレジット表示 |
| 日本国外での誤適用 | 世界の他地域が劣化 | BBox 判定を厳密に（`covers()` でタイル単位判定） |
| 標高デコードの nodata 誤判定 | 海岸線が海面に沈む/浮く | 無効値 `(128, 0, 0)` と `x = 2^23` を正しく判定し、`fill_holes()` で補間 |
| GSI 標高タイルのサービス変更 | URL が 404 になる | `dem5a_png` → `dem_png` のフォールバック + 404 マーカーで Mapterhorn にフォールバック |

---

## 5. ファイル変更一覧（見積もり）

### オリジナルソースへの変更（データソース追加のみ）

| ファイル | 変更種別 | 内容 | 行数見積 |
|---|---|---|---|
| `server/imagery_regional.py` | 修正 | `REGIONAL` のエントリ構造を 6 タプル化（全エントリに `max_zoom` 追加、japan は 18） | ~35 行 |
| `server/imagery.py` | 修正 | `Source` 生成ロジックの unpack 更新（`max_zoom=_max_zoom or 17`） | ~3 行 |
| `server/netfetch.py` | 修正 | `_regional_policies()` の unpack 更新（6 タプル対応） | ~2 行 |
| `server/dem.py` | 修正 | 地域プロバイダーフック `_japan()` 追加 + `_make_tile` のチェーン + `GsiDem` 生成 + `gsi_served` | ~15 行 |
| `server/credits.py` | 修正 | `ELEVATION`/`SHORT` に `dem:gsi` 追加 + `_ids()` に `gsi_served` 参照 | ~4 行 |

### プラグイン側（`EJapan/` 新規）

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `EJapan/gsidem.py` | 新規 | GSI 標高プロバイダー（`dem5a_png` → `dem_png` フォールバック、符号付き 24bit デコード、z16 は z15 親のアップサンプル） |
| `EJapan/plateau_converter.py` | 新規 | PLATEAU CityGML → GeoJSON 変換 |
| `EJapan/tests/` | 新規 | デコード・BBox・フォールバックのテスト |

### 開発環境（Phase 0 着手前に修正推奨）

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `EJapan/launcher_debug.py` | 書き換え済み | ゲームのみを Lua デバッグモード（`-lua-debug on -lua-debug-port 21110`）で起動する薄いスクリプトに書き換え（`launcher.start_game` + `BNGE_GAME_ARGS` を再利用）。サーバは VS Code の「Python Server Launch (earthd)」で起動する |
| `.vscode/launch.json` | 修正済み | 「Python Server Launch (earthd)」が `server/earthd.py` を直接起動（ブレークポイント可）。「BeamNG Lua Attach」（ポート 21110）と compounds「Debug BeamNG & Python」も設定 |
| `.vscode/tasks.json` | 新規 | 「Launch BeamNG (Lua debug)」タスクで `EJapan/launcher_debug.py` を実行（VS Code からゲームを Lua デバッグモードで起動） |

---

## 6. 結論

- **GSI タイルは Web Mercator (EPSG:3857)** — 座標変換は不要。既存の japan エントリ（シームレス写真）は正しく動作しており、ズーム調整のみでよい
- **GSI 標高タイルは `dem*_png` サービス**（旧 `dem5a` 等は廃止）— URL とデコード式（符号付き 24bit）を新仕様に合わせる
- **実装はデータソース追加方式** — `imagery_regional.REGIONAL` への追加 + `dem.py` の `_japan()` フックで実現。プラグイン機構も add-ons も不要
- **Phase 0 は「~2 行」ではなく `REGIONAL` の 6 タプル化を含む**（`imagery.py` / `netfetch.py` の unpack 更新が必要）
- **Phase 1 は credits 連携を含む**（`ELEVATION`/`SHORT` の `dem:gsi` + `_ids()` の `gsi_served` 参照）
- **開発環境の修正が先行必要**: `EJapan/launcher_debug.py` はゲームを Lua デバッグモードで起動する薄いスクリプトに書き換え済み。`.vscode/launch.json` は `server/earthd.py` を直接起動する「Python Server Launch (earthd)」に修正済み。`.vscode/tasks.json` にゲーム起動タスク「Launch BeamNG (Lua debug)」を追加済み

実装フェーズは Phase 0（GSI 写真のズーム調整）→ Phase 1（GSI 標高 `dem5a_png`）→ Phase 2（GSI 写真改善）→ Phase 3（PLATEAU）→ Phase 4（検証）の順。まず**開発環境の修正**（launcher_debug.py / launch.json）と Phase 0 から着手し、福岡で動作確認後に Phase 1 へ進むことを推奨する。