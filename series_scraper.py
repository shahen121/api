# series_scraper.py
import re
import time
import json
import os
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

BASE_HOST = "https://azoramoon.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CACHE_DIR = ".cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_TTL = 60 * 60  # 1 hour default


def _cache_path(key: str) -> str:
    safe = key.replace("://", "_").replace("/", "_").replace("?", "_")
    return os.path.join(CACHE_DIR, f"{safe}.json")


def cache_get(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not os.path.exists(p):
        return None
    mtime = os.path.getmtime(p)
    if time.time() - mtime > CACHE_TTL:
        try:
            os.remove(p)
        except:
            pass
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def cache_set(key: str, value: dict):
    p = _cache_path(key)
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
    except Exception:
        pass


def fetch_html(url: str, use_cache: bool = True, timeout: int = 20) -> Optional[str]:
    """Simple fetcher with optional cache."""
    key = f"html::{url}"
    if use_cache:
        cached = cache_get(key)
        if cached and "html" in cached:
            return cached["html"]

    try:
        with httpx.Client(headers=HEADERS, timeout=timeout) as client:
            r = client.get(url)
            r.raise_for_status()
            r.encoding = "utf-8"
            html = r.text
            if use_cache:
                cache_set(key, {"html": html})
            return html
    except Exception:
        return None


# --- helpers to parse chapter number from url/text
CHAPTER_NUM_RE = re.compile(r'chapter[-/ ]?(\d+(?:\.\d+)?)', re.I)


def parse_chapter_number_from_url(url: str) -> Optional[float]:
    m = CHAPTER_NUM_RE.search(url)
    if m:
        try:
            return float(m.group(1))
        except:
            return None
    return None


# ---------------------------
# Series list (paging simple)
# ---------------------------
def extract_series_list(page_url: str = f"{BASE_HOST}/series", use_cache: bool = True) -> List[Dict]:
    """
    Scrape the main series listing page and return a list of {title, url, cover}
    Works as a best-effort (site layout may change).
    """
    html = fetch_html(page_url, use_cache=use_cache)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = []
    # find anchors that point to /series/...
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/series/") and href.count("/") >= 2:
            full = urljoin(BASE_HOST, href)
            title = a.get("title") or a.get_text(strip=True) or None
            # try to find img inside
            img = a.find("img")
            cover = None
            if img and img.get("src"):
                src = img.get("src")
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urljoin(BASE_HOST, src)
                cover = src
            # avoid duplicates
            if full and not any(c['url'] == full for c in cards):
                cards.append({"title": title or full, "url": full, "cover": cover})
    return cards


# ---------------------------
# Series profile + chapters
# ---------------------------
def extract_series_profile(series_url: str, use_cache: bool = True) -> Dict:
    """
    Returns a dict:
    {
      "title": "...",
      "url": "...",
      "cover": "...",
      "description": "...",
      "author": "...",
      "genres": [...],
      "status": "...",
      "chapters": [
         {"title":"Chapter 1","url":"...","number":1.0}
      ]
    }
    """
    key = f"profile::{series_url}"
    if use_cache:
        cached = cache_get(key)
        if cached:
            return cached

    html = fetch_html(series_url, use_cache=use_cache)
    if not html:
        return {"url": series_url, "error": "failed_fetch"}

    soup = BeautifulSoup(html, "html.parser")

    # try __NEXT_DATA__ JSON first for reliable data
    profile = {"url": series_url, "title": None, "cover": None, "description": None, "author": None, "genres": [], "status": None, "chapters": []}

    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            data = json.loads(script.string)
            # deep-search for common keys
            def deep(d):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k.lower() in ("title", "name") and not profile["title"]:
                            if isinstance(v, str):
                                profile["title"] = v
                        if k.lower() in ("description", "summary") and not profile["description"]:
                            if isinstance(v, str):
                                profile["description"] = v
                        if k.lower() in ("cover", "image", "thumbnail") and not profile["cover"]:
                            if isinstance(v, str) and v.startswith("http"):
                                profile["cover"] = v
                        if k.lower() in ("chapters", "pages", "items"):
                            if isinstance(v, list):
                                for it in v:
                                    if isinstance(it, dict):
                                        u = it.get("url") or it.get("link") or it.get("slug")
                                        t = it.get("title") or it.get("name")
                                        if u and not u.startswith("http"):
                                            u = urljoin(BASE_HOST, u)
                                        if u:
                                            num = parse_chapter_number_from_url(u) or None
                                            profile["chapters"].append({"title": t or u, "url": u, "number": num})
                        deep(v)
                elif isinstance(d, list):
                    for x in d:
                        deep(x)
            deep(data)
        except Exception:
            pass

    # Fallback parsing from DOM
    if not profile["title"]:
        h1 = soup.find(["h1","h2"])
        if h1:
            profile["title"] = h1.get_text(strip=True)

    # cover: look for meta og:image
    if not profile["cover"]:
        m = soup.find("meta", property="og:image")
        if m and m.get("content"):
            profile["cover"] = m["content"]

    # description
    if not profile["description"]:
        p = soup.find("meta", {"name": "description"})
        if p and p.get("content"):
            profile["description"] = p.get("content")

    # attempt to gather chapters links from DOM
    # find anchors with /series/.../chapter-...
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/series/") and "chapter" in href.lower():
            full = urljoin(BASE_HOST, href)
            if full not in seen:
                seen.add(full)
                title = a.get_text(strip=True) or full
                num = parse_chapter_number_from_url(full)
                profile["chapters"].append({"title": title, "url": full, "number": num})

    # ensure chapters unique & sorted (ascending by number if available, else by url)
    unique = {}
    for ch in profile["chapters"]:
        unique[ch["url"]] = ch
    chapters = list(unique.values())

    # sort: if numbers exist sort by number ascending, otherwise by url
    def _sort_key(item):
        n = item.get("number")
        return (0 if n is None else 1, n if n is not None else item.get("url"))
    # prefer numeric sort when possible — but we want ascending (1..n)
    try:
        # if at least one has number, sort by number ascending with None at end
        if any(c.get("number") is not None for c in chapters):
            chapters.sort(key=lambda x: (float(x["number"]) if x.get("number") is not None else 1e9))
        else:
            chapters.sort(key=lambda x: x.get("url"))
    except Exception:
        chapters.sort(key=lambda x: x.get("url"))

    profile["chapters"] = chapters
    cache_set(key, profile)
    return profile
