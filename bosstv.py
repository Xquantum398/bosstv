import json
from pathlib import Path
from urllib.parse import urlsplit
import requests

API_URL = "https://bosssports1079.com/api/matches"
OUTPUT_M3U = Path("all_matches.m3u")

VLC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/158.0.0.0 Safari/537.36"
)


def get_referrer(api_url: str) -> str:
    parsed = urlsplit(api_url.strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return "https://bosssports1079.com/"


def collect_links_from_record(item: dict) -> list[tuple[str, str]]:
    """Kayıttaki videoid, streams ve diğer olası yayın alanlarından (etiket, url) listesi döndürür."""
    results: list[tuple[str, str]] = []

    videoid = item.get("videoid")
    if isinstance(videoid, str) and videoid.strip().startswith(("http://", "https://")):
        results.append(("videoid", videoid.strip()))

    streams = item.get("streams")
    if isinstance(streams, list):
        for idx, s in enumerate(streams, start=1):
            if isinstance(s, dict):
                s_url = s.get("url")
                s_name = (s.get("name") or s.get("id") or f"Stream {idx}").strip()
                if isinstance(s_url, str) and s_url.strip().startswith(("http://", "https://")):
                    results.append((s_name, s_url.strip()))

    # Farklı bir alan adı altında .m3u8 gelirse yakala
    for key, val in item.items():
        if key in ("videoid", "streams"):
            continue
        if isinstance(val, str) and ".m3u8" in val.lower() and val.strip().startswith(("http://", "https://")):
            results.append((key, val.strip()))

    # Sırayı koruyarak aynı URL tekrarlarını kaldır
    seen = set()
    unique_results = []
    for label, url in results:
        if url not in seen:
            seen.add(url)
            unique_results.append((label, url))

    return unique_results


def build_title(item: dict) -> str:
    home = (item.get("home") or "").strip()
    away = (item.get("away") or "").strip()
    league = (item.get("league") or "").strip()
    category = (item.get("category") or "").strip()
    match_id = str(item.get("id") or "").strip()

    teams = f"{home} vs {away}".strip(" vs")
    prefix = league or category
    if teams and prefix:
        return f"[{prefix}] {teams}"
    return teams or prefix or f"Match {match_id or 'Unknown'}"


def main(api_url: str = API_URL, out_path: Path = OUTPUT_M3U, deduplicate_urls: bool = False):
    referrer = get_referrer(api_url)
    headers = {
        "User-Agent": VLC_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": referrer,
    }

    resp = requests.get(api_url, headers=headers, timeout=20)
    resp.raise_for_status()
    payload = resp.json()

    items = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        raise ValueError("API yanıtında 'data' listesi bulunamadı.")

    m3u_lines = ["#EXTM3U\n"]
    global_seen_urls = set()
    total_exported = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        title = build_title(item)
        source = (item.get("source") or "").strip()
        links = collect_links_from_record(item)

        for label, url in links:
            if deduplicate_urls and url in global_seen_urls:
                continue
            global_seen_urls.add(url)

            display_title = title
            if len(links) > 1 or source:
                extras = [x for x in (source, label if len(links) > 1 else "") if x]
                if extras:
                    display_title = f"{title} ({' | '.join(extras)})"

            block = (
                f"#EXTINF:-1,{display_title}\n"
                f"#EXTVLCOPT:http-user-agent={VLC_USER_AGENT}\n"
                f"#EXTVLCOPT:http-referrer={referrer}\n"
                f"{url}\n"
            )
            m3u_lines.append(block)
            print(block.strip())
            total_exported += 1

    out_path.write_text("".join(m3u_lines), encoding="utf-8")
    print(f"\nToplam {total_exported} link '{out_path}' dosyasına yazdırıldı.")


if __name__ == "__main__":
    # API'deki erosmac ve erosmac-backup dahil tüm kayıtları almak için False bırakın;
    # yalnızca farklı URL'leri tutmak isterseniz True yapabilirsiniz.
    main(deduplicate_urls=False)
