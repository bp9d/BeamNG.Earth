"""Fetch GSI's '標高タイルの詳細仕様' page and extract the decode spec."""
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
    # find the link in ichiran.html first
    st, data = fetch("https://maps.gsi.go.jp/development/ichiran.html")
    text = data.decode("utf-8", "replace")
    links = re.findall(r'href="([^"]*)"[^>]*>[^<]*標高タイルの詳細仕様', text)
    out = [f"ichiran links: {links}"]
    for href in links:
        url = href if href.startswith("http") else "https://maps.gsi.go.jp/development/" + href.lstrip("./")
        st2, d2 = fetch(url)
        out.append(f"\n=== {url} -> {st2} ({len(d2)}B) ===")
        if st2 == 200:
            t = d2.decode("utf-8", "replace")
            t = re.sub(r"<br\s*/?>", "\n", t)
            t = re.sub(r"</(td|tr|th|p|div|h[1-6])>", "\n", t)
            t = re.sub(r"<[^>]+>", " ", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n\s*\n+", "\n", t)
            out.append(t[:6000])
    with open("probes/gsi_dem_spec4_out.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("written probes/gsi_dem_spec4_out.txt")


if __name__ == "__main__":
    main()