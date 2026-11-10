"""Extract the GSI '標高タイル（基盤地図情報数値標高モデル）' spec section from ichiran.html."""
import re
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
    st, data = fetch("https://maps.gsi.go.jp/development/ichiran.html")
    if st != 200:
        print("status", st)
        return
    text = data.decode("utf-8", "replace")
    out = []
    # The section after the heading "標高タイル（基盤地図情報数値標高モデル）"
    key = "標高タイル（基盤地図情報数値標高モデル）"
    idx = text.find(key)
    if idx < 0:
        key = "標高タイル（基盤地図情報数値標高モデル"
        idx = text.find(key)
    out.append(f"heading at {idx}")
    if idx >= 0:
        chunk = text[idx:idx + 6000]
        # strip tags but keep table structure readable
        chunk = re.sub(r"<br\s*/?>", "\n", chunk)
        chunk = re.sub(r"</(td|tr|th|p|div|h[1-6])>", "\n", chunk)
        chunk = re.sub(r"<[^>]+>", " ", chunk)
        chunk = re.sub(r"[ \t]+", " ", chunk)
        chunk = re.sub(r"\n\s*\n+", "\n", chunk)
        out.append(chunk[:5000])
    with open("probes/gsi_dem_spec2_out.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("written probes/gsi_dem_spec2_out.txt")


if __name__ == "__main__":
    main()