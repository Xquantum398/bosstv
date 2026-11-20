import asyncio
import concurrent.futures
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from playwright.async_api import async_playwright

# ==================================================
# AYARLAR
# ==================================================

BASE_PREFIX = "https://bosssports"
BASE_SUFFIX = ".com"

START_NUM = 1074
END_NUM = 3000

KNOWN_DOMAINS = [
    "https://bosssports1079.com",
    "https://bosssports1111.com",
]

MATCHES_API_PATH = "/api/matches"

CACHE_FILE = Path("domain_cache1.txt")
OUTPUT_FILE = Path("tv247tr.m3u")

MAX_WORKERS = 80
REQUEST_TIMEOUT = 6
PAGE_TIMEOUT = 45000
WAIT_AFTER_LOAD = 6000
MAX_CONSECUTIVE_NET_ERRORS = 3

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ==================================================
# KANAL LİSTESİ & YEDEK BAĞLANTILAR
# ==================================================

CHANNELS_TO_UPDATE = [
    {
        "name": "BEİN SPORTS 1-BS",
        "path": "?channel=channel%3Atflix-MDJjNzUwY2JiYTUzYTZlZg"
    },
    {
        "name": "BEİN SPORTS 2-BS",
        "path": "?channel=channel%3Atflix-NjNlZmVjMzI1MGY3NzgyYg"
    },
    {
        "name": "BEİN SPORTS 3-BS",
        "path": "?channel=channel%3Atflix-MTA4MWJhNGE4MDFiMzFjZg"
    },
    {
        "name": "BEİN SPORTS 4-BS",
        "path": "?channel=channel%3Atflix-YzkwOWU3MzQ0ZjAxNmRjMA"
    },
    {
        "name": "BEİN SPORTS 5-BS",
        "path": "?channel=channel%3Atflix-Yjg5NTA1ZGE2M2YyYWZkYg"
    },
    {
        "name": "BEİN SPORTS MAX 1-BS",
        "path": "?channel=channel%3Atflix-MzY1NGU3NzgyN2FjZTFmYQ"
    },
    {
        "name": "BEİN SPORTS MAX 2-BS",
        "path": "?channel=channel%3Atflix-ZDdkZjZiNWZlNjdlMzIxMQ"
    },
    {
        "name": "BEİN SPORTS HABER-BS",
        "path": "?channel=channel%3Atflix-NTRmYzI4ZjMzMmZhZDc0Mg"
    },
    {
        "name": "S SPORT-BS",
        "path": "?channel=channel%3Atflix-NzI0NmY4MjdlOGI4YWQzNw"
    },
    {
        "name": "S SPORT 2-BS",
        "path": "?channel=channel%3Atflix-NzM1ZmIxZDU3MWI0ZWJmNA"
    },
    {
        "name": "EUROSPORT 1-BS",
        "path": "?channel=channel%3Atflix-NDVlOWE1YmNmYzc2NTI5NA"
    },
    {
        "name": "EUROSPORT 2-BS",
        "path": "?channel=channel%3Atflix-ZGQ5MDRhZjM0NGUzNmE4ZA"
    },
    {
        "name": "SPOR SMART-BS",
        "path": "?channel=channel%3Atflix-ZjRhZTVhYTY2NWViMWFhOQ"
    },
    {
        "name": "SPOR SMART 2-BS",
        "path": "?channel=channel%3Atflix-N2NhZGU3M2NjNTlkOGY0Yw"
    },
    {
        "name": "ATV-BS",
        "path": "?channel=channel%3Atflix-MDY0NDRjNTZkY2RmMWUwMg"
    }
]

FALLBACK_STREAM_LINKS = {
    "BEİN SPORTS 2-BS": (
        "https://pdg854df9gddsfg59xfcg5695df9g85s9fdgsd9f5g95d5fhg9.pokemon596.store/"
        "osldfgo9569s6gstreyhdfghsddfg/secure/"
        "63ec16c3206c36f2487d26811ad957c42434762483eb6cc9e484b164100553ef/"
        "1795208018/bein2tr.m3u8"
    )
}

# ==================================================
# KANAL ADI NORMALİZASYONU
# ==================================================

def normalize_channel_name(name: str) -> str:
    cleaned = re.sub(r"\s*-\s*BS\b.*$", "", name, flags=re.IGNORECASE)
    cleaned = cleaned.replace("İ", "I").replace("ı", "i")
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", cleaned).strip().lower()
    return cleaned

# ==================================================
# API & DOMAIN KONTROLÜ
# ==================================================

def fetch_matches_json(base_url: str):
    """Verilen domaindeki /api/matches JSON verisini döndürmeye çalışır."""
    api_url = urljoin(base_url.rstrip("/") + "/", MATCHES_API_PATH.lstrip("/"))
    headers = {
        "User-Agent": DESKTOP_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": base_url.rstrip("/") + "/",
    }

    try:
        response = requests.get(
            api_url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        if response.status_code != 200:
            return None, f"API_HTTP_{response.status_code}"

        content_type = response.headers.get("Content-Type", "").lower()
        text = response.text.strip()
        if not text:
            return None, "API_EMPTY"

        if "json" in content_type or text.startswith(("{", "[")):
            data = json.loads(text)
            return data, "API_OK"

        return None, "API_NOT_JSON"
    except requests.ConnectionError as exc:
        msg = str(exc)
        if "NameResolutionError" in msg or "Failed to resolve" in msg or "nodename nor servname" in msg:
            return None, "DNS_ERROR"
        return None, "CONN_ERROR"
    except requests.Timeout:
        return None, "TIMEOUT"
    except ValueError:
        return None, "API_JSON_DECODE_ERR"
    except requests.RequestException as exc:
        return None, f"REQ_ERR:{type(exc).__name__}"


def test_url_is_active(url: str):
    """Önce /api/matches ile doğrular, olmazsa ana sayfa üzerinden bakar."""
    data, api_reason = fetch_matches_json(url)
    if data is not None:
        return True, api_reason, data

    headers = {"User-Agent": DESKTOP_USER_AGENT}
    try:
        with requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True
        ) as response:
            if response.status_code < 400:
                return True, f"HTTP_{response.status_code}", None
            return False, f"HTTP_{response.status_code}", None
    except requests.ConnectionError as exc:
        msg = str(exc)
        if "NameResolutionError" in msg or "Failed to resolve" in msg or "nodename nor servname" in msg:
            return False, "DNS_ERROR", None
        return False, "CONN_ERROR", None
    except requests.Timeout:
        return False, "TIMEOUT", None
    except requests.RequestException as exc:
        return False, f"REQ_ERR:{type(exc).__name__}", None


def check_single_domain_num(num: int):
    url = f"{BASE_PREFIX}{num}{BASE_SUFFIX}"
    ok, reason, data = test_url_is_active(url)
    return url, ok, reason, data


def get_active_base_domain():
    candidates = []

    if CACHE_FILE.exists():
        cached_url = CACHE_FILE.read_text(encoding="utf-8").strip()
        if cached_url:
            candidates.append(cached_url)

    for domain in KNOWN_DOMAINS:
        if domain not in candidates:
            candidates.append(domain)

    for candidate in candidates:
        ok, reason, data = test_url_is_active(candidate)
        if ok:
            print(f"Aktif domain doğrulandı: {candidate} ({reason})")
            CACHE_FILE.write_text(candidate, encoding="utf-8")
            return candidate, data
        print(f"Domain yanıt vermedi ({candidate} -> {reason}).")

    print(f"Domain taraması başladı: {START_NUM}-{END_NUM - 1} (workers={MAX_WORKERS})")

    reason_counts = {}
    sample_reasons = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(check_single_domain_num, num)
            for num in range(START_NUM, END_NUM)
        ]

        for future in concurrent.futures.as_completed(futures):
            try:
                url, ok, reason, data = future.result()
                if ok:
                    print(f"Aktif domain bulundu: {url} ({reason})")
                    CACHE_FILE.write_text(url, encoding="utf-8")
                    return url, data

                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if reason not in sample_reasons:
                    sample_reasons[reason] = url
            except Exception as error:
                print(f"Domain kontrol hatası: {error}")

    summary = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
    samples = ", ".join(f"{k}={v}" for k, v in sample_reasons.items())
    raise RuntimeError(
        f"Belirtilen aralıkta aktif domain bulunamadı! "
        f"Özet: [{summary}] | Örnekler: [{samples}]"
    )


def _extract_m3u8_from_item(item: dict):
    """Tek bir maç/kanal kaydından doğrudan .m3u8 bağlantısını çıkarır."""
    for field in ("videoid", "m3u8", "stream_url", "streamUrl", "url", "link", "hls"):
        val = item.get(field)
        if isinstance(val, str) and ".m3u8" in val.lower():
            return val.strip()

    streams = item.get("streams")
    if isinstance(streams, list):
        for s in streams:
            if isinstance(s, dict):
                s_url = s.get("url")
                if isinstance(s_url, str) and ".m3u8" in s_url.lower():
                    return s_url.strip()

    return None


def enrich_channels_from_matches(matches_data, base_channels):
    """
    /api/matches JSON içindeki `data` dizisini tarayarak:
    - doğrudan .m3u8 URL'lerini (`videoid` / `streams[].url`) yakalar
    - güncel maç/kanal bilgisini eşleştirir
    """
    if not isinstance(matches_data, dict):
        return base_channels

    items = matches_data.get("data")
    if not isinstance(items, list) or not items:
        return base_channels

    target_map = {
        normalize_channel_name(ch["name"]): idx
        for idx, ch in enumerate(base_channels)
    }

    enriched = [dict(ch) for ch in base_channels]
    matched_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        text_parts = []
        for field in ("name", "title", "league", "category", "home", "away", "manual_priority_label"):
            val = item.get(field)
            if isinstance(val, str) and val.strip():
                text_parts.append(val)

        if not text_parts:
            continue

        combined_norm = normalize_channel_name(" ".join(text_parts))
        if not combined_norm:
            continue

        m3u8_url = _extract_m3u8_from_item(item)

        for norm_key, idx in sorted(target_map.items(), key=lambda x: len(x[0]), reverse=True):
            if norm_key and re.search(rf"(?:^|\s){re.escape(norm_key)}(?:\s|$)", combined_norm):
                if m3u8_url and "direct_m3u8" not in enriched[idx]:
                    enriched[idx]["direct_m3u8"] = m3u8_url
                    matched_count += 1
                break

    if matched_count > 0:
        print(f"API üzerinden {matched_count} kanal için doğrudan M3U8 eşleştirildi.")
    else:
        print("API 'data' içinde kanal adıyla doğrudan eşleşen kayıt bulunmadı; Playwright taramasına geçiliyor.")

    return enriched

# ==================================================
# PLAYWRIGHT İLE M3U8 TESPİTİ
# ==================================================

def is_fatal_net_error(error_text: str) -> bool:
    fatal_codes = (
        "ERR_NAME_NOT_RESOLVED",
        "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_RESET",
        "ERR_TIMED_OUT",
        "ERR_INTERNET_DISCONNECTED",
    )
    return any(code in error_text for code in fatal_codes)


async def trigger_player_interaction(page):
    """Oynatıcı veya iframe içindeki oynat düğmesini tetiklemeyi dener."""
    try:
        for selector in ("video", "button[aria-label*='play' i]", ".vjs-big-play-button", ".jw-icon-display"):
            loc = page.locator(selector).first
            if await loc.count() > 0:
                await loc.click(timeout=1500, force=True)
                break

        for frame in page.frames:
            if frame != page.main_frame:
                try:
                    await frame.locator("body").click(timeout=1500, force=True)
                    break
                except Exception:
                    continue
    except Exception:
        pass


async def get_stream_url(page, full_url: str):
    stream_url = None
    fatal_net_error = False

    def handle_request(request):
        nonlocal stream_url
        if ".m3u8" in request.url.lower() and stream_url is None:
            stream_url = request.url
            print(f"M3U8 bulundu: {stream_url}")

    def handle_response(response):
        nonlocal stream_url
        if ".m3u8" in response.url.lower() and stream_url is None:
            stream_url = response.url
            print(f"M3U8 (response) bulundu: {stream_url}")

    page.on("request", handle_request)
    page.on("response", handle_response)

    try:
        print(f"Sayfa açılıyor: {full_url}")

        await page.goto(
            full_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        await page.wait_for_timeout(WAIT_AFTER_LOAD // 2)

        if stream_url is None:
            await trigger_player_interaction(page)
            await page.wait_for_timeout(WAIT_AFTER_LOAD // 2)

    except Exception as error:
        error_msg = str(error)
        print(f"Sayfa yükleme hatası: {error_msg}")
        if is_fatal_net_error(error_msg):
            fatal_net_error = True

    finally:
        page.remove_listener("request", handle_request)
        page.remove_listener("response", handle_response)

    return stream_url, fatal_net_error

# ==================================================
# M3U DOSYASI GÜNCELLEME
# ==================================================

def update_playlist(updated_links: dict):
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(f"{OUTPUT_FILE} dosyası bulunamadı!")

    if not updated_links:
        raise RuntimeError(
            "Hiçbir yeni bağlantı bulunamadı. Playlist değiştirilmedi."
        )

    normalized_links = {}
    for channel_name, stream_url in updated_links.items():
        norm_key = normalize_channel_name(channel_name)
        if norm_key:
            normalized_links[norm_key] = (channel_name, stream_url)

    with OUTPUT_FILE.open("r", encoding="utf-8-sig") as file:
        lines = file.readlines()

    new_lines = []
    updated_count = 0
    matched_keys = set()
    i = 0

    while i < len(lines):
        line = lines[i]
        matched_key = None

        if line.lstrip().startswith("#EXTINF"):
            norm_line = normalize_channel_name(line)
            for norm_key in sorted(normalized_links.keys(), key=len, reverse=True):
                if re.search(rf"(?:^|\s){re.escape(norm_key)}(?:\s|$)", norm_line):
                    matched_key = norm_key
                    break

        if matched_key:
            new_lines.append(line)
            i += 1

            while i < len(lines) and lines[i].strip().startswith("#"):
                new_lines.append(lines[i])
                i += 1

            if i < len(lines) and not lines[i].strip().startswith("#"):
                _, new_url = normalized_links[matched_key]
                new_lines.append(new_url + "\n")
                matched_keys.add(matched_key)
                updated_count += 1
                i += 1
            else:
                orig_name, _ = normalized_links[matched_key]
                print(f"UYARI: {orig_name} için eski URL satırı bulunamadı.")
        else:
            new_lines.append(line)
            i += 1

    unmatched_names = [
        orig_name
        for norm_key, (orig_name, _) in normalized_links.items()
        if norm_key not in matched_keys
    ]
    if unmatched_names:
        print(
            "UYARI: M3U içinde eşleşmeyen kanallar: "
            + ", ".join(unmatched_names)
        )

    if updated_count == 0:
        raise RuntimeError("M3U içerisinde güncellenecek kanal bulunamadı!")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(OUTPUT_FILE.parent),
            delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.writelines(new_lines)

        os.replace(temp_path, OUTPUT_FILE)

    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()

    print(f"Playlist güncellendi. Toplam güncellenen kanal: {updated_count}")

# ==================================================
# ANA PROGRAM
# ==================================================

async def main():
    print("=" * 50)
    print("BOSS TV PLAYLIST GÜNCELLEYİCİ")
    print("=" * 50)

    active_base_url, matches_data = get_active_base_domain()
    channels = enrich_channels_from_matches(matches_data, CHANNELS_TO_UPDATE)

    updated_links = {}
    consecutive_net_errors = 0
    domain_dead = False

    pending_channels = []
    for ch in channels:
        if ch.get("direct_m3u8"):
            updated_links[ch["name"]] = ch["direct_m3u8"]
            print(f"\nTaranıyor: {ch['name']}\nAPI üzerinden doğrudan M3U8 alındı: {ch['direct_m3u8']}")
        else:
            pending_channels.append(ch)

    if pending_channels:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=DESKTOP_USER_AGENT,
                locale="tr-TR",
                viewport={"width": 1366, "height": 768}
            )

            try:
                page = await context.new_page()

                for channel in pending_channels:
                    print(f"\nTaranıyor: {channel['name']}")

                    raw_path = channel["path"]
                    full_url = (
                        raw_path if raw_path.startswith("http")
                        else urljoin(active_base_url.rstrip("/") + "/", raw_path.lstrip("/")) if raw_path.startswith("/")
                        else active_base_url.rstrip("/") + raw_path
                    )

                    stream_url, fatal_net_error = await get_stream_url(page, full_url)

                    if stream_url:
                        updated_links[channel["name"]] = stream_url
                        consecutive_net_errors = 0
                        print("Bağlantı başarıyla alındı.")
                    else:
                        fallback_url = FALLBACK_STREAM_LINKS.get(channel["name"])
                        if fallback_url and not fatal_net_error:
                            updated_links[channel["name"]] = fallback_url
                            print("Yeni bağlantı yakalanamadı, yedek bağlantı kullanıldı.")
                        else:
                            print("Yeni bağlantı alınamadı. Eski bağlantı korunacak.")

                        if fatal_net_error:
                            consecutive_net_errors += 1
                            await page.close()
                            page = await context.new_page()
                        else:
                            consecutive_net_errors = 0

                    if consecutive_net_errors >= MAX_CONSECUTIVE_NET_ERRORS:
                        print(
                            f"\nArt arda {consecutive_net_errors} kanalda temel ağ/DNS hatası oluştu. "
                            f"Domain ({active_base_url}) erişilemez kabul ediliyor."
                        )
                        domain_dead = True
                        break

            finally:
                await context.close()
                await browser.close()

    if domain_dead and CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
            print(f"Bozuk cache dosyası silindi: {CACHE_FILE}")
        except OSError:
            pass

    update_playlist(updated_links)
    print("\nİŞLEM BAŞARIYLA TAMAMLANDI!")

# ==================================================
# PROGRAM BAŞLANGICI
# ==================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("\nPROGRAM HATASI:")
        print(error)
        raise
