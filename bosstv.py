import asyncio
import concurrent.futures
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

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
