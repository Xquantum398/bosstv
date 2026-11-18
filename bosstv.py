import asyncio
import concurrent.futures
import os
import re
import tempfile
import unicodedata
from pathlib import Path

import requests
from playwright.async_api import async_playwright

# ==================================================
# AYARLAR
# ==================================================

BASE_PREFIX = "https://bosssports"
BASE_SUFFIX = ".com"

START_NUM = 1074
END_NUM = 2000

CACHE_FILE = Path("domain_cache1.txt")
OUTPUT_FILE = Path("tv247tr.m3u")

MAX_WORKERS = 50
REQUEST_TIMEOUT = 5
PAGE_TIMEOUT = 45000
WAIT_AFTER_LOAD = 6000

# ==================================================
# KANAL LİSTESİ
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
# DOMAIN KONTROLÜ
# ==================================================

def test_url_is_active(url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.head(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )

        if response.status_code < 400:
            return True

        if response.status_code in (403, 405):
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True
            )

            active = response.status_code < 400
            response.close()
            return active

        return False

    except requests.RequestException:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True
            )

            active = response.status_code < 400
            response.close()
            return active

        except requests.RequestException:
            return False


def check_single_domain_num(num):
    url = f"{BASE_PREFIX}{num}{BASE_SUFFIX}"

    if test_url_is_active(url):
        return url

    return None


def get_active_base_domain():

    if CACHE_FILE.exists():
        cached_url = CACHE_FILE.read_text(
            encoding="utf-8"
        ).strip()

        if cached_url and test_url_is_active(cached_url):
            print(f"Aktif cache domaini: {cached_url}")
            return cached_url

        print("Cache domaini çalışmıyor, yeni domain aranıyor.")

    print(
        f"Domain taraması başladı: "
        f"{START_NUM}-{END_NUM - 1}"
    )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(check_single_domain_num, num)
            for num in range(START_NUM, END_NUM)
        ]

        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()

                if result:
                    print(f"Aktif domain bulundu: {result}")

                    CACHE_FILE.write_text(
                        result,
                        encoding="utf-8"
                    )

                    return result

            except Exception as error:
                print(f"Domain kontrol hatası: {error}")

    raise RuntimeError(
        "Belirtilen aralıkta aktif domain bulunamadı!"
    )

# ==================================================
# PLAYWRIGHT İLE M3U8 TESPİTİ
# ==================================================

async def get_stream_url(page, full_url):

    stream_url = None

    def handle_request(request):

        nonlocal stream_url

        if ".m3u8" in request.url.lower() and stream_url is None:
            stream_url = request.url

            print(f"M3U8 bulundu: {stream_url}")

    page.on("request", handle_request)

    try:
        print(f"Sayfa açılıyor: {full_url}")

        await page.goto(
            full_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        await page.wait_for_timeout(WAIT_AFTER_LOAD)

    except Exception as error:
        print(f"Sayfa yükleme hatası: {error}")

    finally:
        page.remove_listener("request", handle_request)

    return stream_url

# ==================================================
# M3U DOSYASI GÜNCELLEME
# ==================================================

def update_playlist(updated_links):

    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"{OUTPUT_FILE} dosyası bulunamadı!"
        )

    if not updated_links:
        raise RuntimeError(
            "Hiçbir yeni bağlantı bulunamadı. "
            "Playlist değiştirilmedi."
        )

    normalized_links = {}
    for channel_name, stream_url in updated_links.items():
        norm_key = normalize_channel_name(channel_name)
        if norm_key:
            normalized_links[norm_key] = (channel_name, stream_url)

    with OUTPUT_FILE.open(
        "r",
        encoding="utf-8-sig"
    ) as file:

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

            # EXTINF satırından sonraki seçenekleri koru.
            while (
                i < len(lines)
                and lines[i].strip().startswith("#")
            ):
                new_lines.append(lines[i])
                i += 1

            # Eski URL satırını yeni URL ile değiştir.
            if i < len(lines) and not lines[i].strip().startswith("#"):

                orig_name, new_url = normalized_links[matched_key]
                new_lines.append(new_url + "\n")
                matched_keys.add(matched_key)
                updated_count += 1
                i += 1

            else:
                orig_name, _ = normalized_links[matched_key]
                print(
                    f"UYARI: {orig_name} için "
                    "eski URL satırı bulunamadı."
                )

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
        raise RuntimeError(
            "M3U içerisinde güncellenecek kanal bulunamadı!"
        )

    # Önce geçici dosyaya yaz, ardından atomik olarak değiştir.
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

    print(
        f"Playlist güncellendi. "
        f"Toplam güncellenen kanal: {updated_count}"
    )

# ==================================================
# ANA PROGRAM
# ==================================================

async def main():

    print("=" * 50)
    print("BOSS TV PLAYLIST GÜNCELLEYİCİ")
    print("=" * 50)

    # 1. Aktif domain bul.
    active_base_url = get_active_base_domain()

    updated_links = {}

    # 2. Tarayıcıyı başlat.
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        try:

            page = await browser.new_page()

            for channel in CHANNELS_TO_UPDATE:

                full_url = (
                    active_base_url + channel["path"]
                )

                print(
                    f"\nTaranıyor: {channel['name']}"
                )

                stream_url = await get_stream_url(
                    page,
                    full_url
                )

                if stream_url:

                    updated_links[channel["name"]] = stream_url

                    print("Bağlantı başarıyla alındı.")

                else:

                    print(
                        "Yeni bağlantı alınamadı. "
                        "Eski bağlantı korunacak."
                    )

        finally:

            await browser.close()

    # 3. Playlist'i güncelle.
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
