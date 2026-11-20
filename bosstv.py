import json
from pathlib import Path
from urllib.parse import urlsplit
import requests

API_URL = "https://bosssports1079.com/api/matches"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://bosssports1079.com/",
}


def get_referrer_from_api_url(api_url: str) -> str:
    parsed = urlsplit(api_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return "https://bosssports1079.com/"


def extract_m3u8_from_item(item: dict) -> list[str]:
    found = []

    for field in ("videoid", "m3u8", "stream_url", "streamUrl", "url", "link", "hls"):
        val = item.get(field)
        if isinstance(val, str) and ".m3u8" in val.lower():
            found.append(val.strip())

    streams = item.get("streams")
    if isinstance(streams, list):
        for s in streams:
            if isinstance(s, dict):
                s_url = s.get("url")
                if isinstance(s_url, str) and ".m3u8" in s_url.lower():
                    found.append(s_url.strip())

    return list(dict.fromkeys(found))


def main(api_url: str = API_URL, out_m3u: Path = Path("matches.m3u")):
    referrer = get_referrer_from_api_url(api_url)
    headers = {**HEADERS, "Referer": referrer}

    resp = requests.get(api_url, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    items = payload.get("data", []) if isinstance(payload, dict) else []
    m3u_lines = ["#EXTM3U\n"]
    total_links = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        links = extract_m3u8_from_item(item)
        if not links:
            continue

        home = (item.get("home") or "").strip()
        away = (item.get("away") or "").strip()
        league = (item.get("league") or item.get("category") or "").strip()
        title = f"{home} vs {away}".strip(" vs") or item.get("id", "Stream")
        if league:
            title = f"[{league}] {title}"

        for idx, link in enumerate(links, start=1):
            suffix = f" ({idx})" if len(links) > 1 else ""
            m3u_lines.append(f"#EXTINF:-1,{title}{suffix}\n")
            m3u_lines.append(f"#EXTVLCOPT:http-referrer={referrer}\n")
            m3u_lines.append(f"{link}\n")
            total_links += 1
            print(f"{title}{suffix}")
            print(f"#EXTVLCOPT:http-referrer={referrer}")
            print(f"{link}\n")

    out_m3u.write_text("".join(m3u_lines), encoding="utf-8")
    print(f"Toplam {total_links} bağlantı '{out_m3u}' dosyasına kaydedildi.")


if __name__ == "__main__":
    main()
