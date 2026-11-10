"""Extract the GSI elevation-tile spec from the official tile list page (ichiran.html).

Writes UTF-8 output to a file to avoid console encoding issues.
"""
import re
import sys
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch(url):
    time.sleep(0.3)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(3_000_000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return repr(e), b""


def main():
    out = []
    st, data = fetch("https://maps.gsi.go.jp/development/ichiran.html")
    out.append(f"status: {st} bytes: {len(data)}")
    if st != 200:
        print("\n".join(out))
        return
    text = data.decode("utf-8", "replace")
    # The elevation tile section: find "標高タイル" or "標高・地形の起伏" heading
    for key in ("標高タイル", "標高・地形の起伏", "dem_png", "dem5a_png", "標高"):
        idx = text.find(key)
        if idx >= 0:
            s = max(0, idx - 300)
            e = min(len(text), idx + 1500)
            chunk = re.sub(r"<[^>]+>", " ", text[s:e])
            chunk = re.sub(r"\s+", " ", chunk).strip()
            out.append(f"\n=== {key} (at {idx}) ===")
            out.append(chunk[:1200])
            break
    # Also list every /xyz/ path that mentions dem
    paths = sorted(set(re.findall(r"/xyz/[A-Za-z0-9_]+", text)))
    dem = [p for p in paths if "dem" in p or "rel" in p or "elev" in p]
    out.append("\n=== dem-ish paths on the page ===")
    out.append(", ".join(dem) if dem else "none")
    with open("probes/gsi_dem_spec_out.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("written probes/gsi_dem_spec_out.txt")


if __name__ == "__main__":
    main()