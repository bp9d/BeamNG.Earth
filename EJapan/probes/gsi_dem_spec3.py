"""Extract the GSI dem_png / dem5a_png spec blocks from ichiran.html."""
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


def block_around(text, needle, before=200, after=2500):
    idx = text.find(needle)
    if idx < 0:
        return f"(not found: {needle})"
    chunk = text[idx - before:idx + after]
    chunk = re.sub(r"<br\s*/?>", "\n", chunk)
    chunk = re.sub(r"</(td|tr|th|p|div|h[1-6])>", "\n", chunk)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = re.sub(r"[ \t]+", " ", chunk)
    chunk = re.sub(r"\n\s*\n+", "\n", chunk)
    return chunk.strip()


def main():
    st, data = fetch("https://maps.gsi.go.jp/development/ichiran.html")
    if st != 200:
        print("status", st)
        return
    text = data.decode("utf-8", "replace")
    out = []
    for needle in ("/xyz/dem_png", "/xyz/dem5a_png", "/xyz/dem5b_png", "/xyz/dem5c_png",
                   "/xyz/dem1a_png", "/xyz/demgm_png", "/xyz/dem"):
        out.append(f"\n{'='*70}\n### {needle}\n{'='*70}")
        out.append(block_around(text, needle))
    with open("probes/gsi_dem_spec3_out.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("written probes/gsi_dem_spec3_out.txt")


if __name__ == "__main__":
    main()