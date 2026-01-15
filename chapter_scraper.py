# chapter_scraper.py
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
import scraper  # assumes your scraper.py has extract_images(url, ua, cf_clearance, cookie_header)
from playwright_worker import scrape_chapter_with_playwright  # your existing worker

CHAPTER_RE_LIST = [
    re.compile(r'chapter[\s\-_\/:]*([0-9]+(?:\.[0-9]+)?)', re.I),
    re.compile(r'(^|\D)(\d+(?:\.\d+)?)(?:$|\D)', re.I),  # fallback to any number group
]

def parse_chapter_number(title: Optional[str], url: Optional[str]) -> Optional[float]:
    """
    Try to extract a numeric chapter number (float) from title, then from url.
    Returns None if not found.
    """
    def try_find(s: str):
        if not s:
            return None
        for rx in CHAPTER_RE_LIST:
            m = rx.search(s)
            if m:
                # capture group might be at different indexes depending on pattern
                for g in m.groups()[::-1]:
                    if g:
                        try:
                            return float(g)
                        except:
                            pass
        return None

    # try title
    num = try_find(title or "")
    if num is not None:
        return num

    # try url path
    if url:
        parsed = urlparse(url)
        path = parsed.path or ""
        # try direct /chapter-295 or /chapter/295 patterns
        num = try_find(path)
        if num is not None:
            return num

    return None

def dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    res = []
    for x in items:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res

def is_valid_image_url(u: str) -> bool:
    if not u:
        return False
    u = u.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if ext in u:
            return True
    # some proxied urls (wsrv.nl?url=...) still contain image url inside
    if "storage.azoramoon.com" in u or "wp-manga" in u or "manga" in u:
        return True
    return False

def extract_chapter_content(
    url: str,
    cf: Optional[str] = None,
    ua: Optional[str] = None,
    prefer_playwright: bool = False,
    headless: bool = True,
    wait_after: float = 1.0,
) -> Dict[str, Any]:
    """
    Return JSON-like dict:
    {
      "url": url,
      "title": "<extracted title or empty>",
      "number": 295.0 or null,
      "images": [ordered urls],
      "count": N,
      "sources": ["dom_img","playwright",...],
      "note": "..."
    }
    """
    result: Dict[str, Any] = {"url": url, "title": None, "number": None, "images": [], "count": 0, "sources": [], "note": None}

    # 1) Try the simple scraper (fast)
    try:
        # scraper.extract_images returns {"url":..., "images": [...], "count": N} or error dict
        fast = scraper.extract_images(url, ua=ua, cf_clearance=cf)
        if isinstance(fast, dict) and fast.get("images"):
            images = [i for i in fast.get("images") if is_valid_image_url(i)]
            images = dedupe_preserve_order(images)
            if images:
                result["images"] = images
                result["count"] = len(images)
                result["sources"].append("dom_img")
    except Exception as e:
        # swallow but record
        result["note"] = f"fast_scrape_error: {e}"

    # 2) If no images found or prefer_playwright, fallback to Playwright worker
    if (not result["images"]) or prefer_playwright:
        try:
            pw = scrape_chapter_with_playwright(url, cf, ua, headless, wait_after)
            # playwright worker returns same shape {"url":..., "images":[...], "sources": [...], "count": N}
            if isinstance(pw, dict):
                pw_images = pw.get("images") or []
                pw_images = [i for i in pw_images if is_valid_image_url(i)]
                # keep existing images first (if any), then append new unique ones
                combined = result["images"] + [i for i in pw_images if i not in result["images"]]
                combined = dedupe_preserve_order(combined)
                if combined:
                    result["images"] = combined
                    result["count"] = len(combined)
                    # merge sources
                    for s in pw.get("sources", ["playwright"]):
                        if s not in result["sources"]:
                            result["sources"].append(s)
        except Exception as e:
            # record the playwright error into note
            note = result.get("note") or ""
            result["note"] = (note + " | " if note else "") + f"playwright_error: {e}"

    # 3) Try to get a title and chapter number heuristically from the page or url
    # We prefer to use the page's title if available from fast or pw dict (some workers may include)
    # Try some fallback heuristics:
    title_guess = None
    try:
        # if scraper returned debug/html text? It usually returns images only.
        # Try extracting from url path last segment as fallback
        path = url.rstrip("/").split("/")[-1]
        if path:
            # replace dashes and underscores
            title_guess = path.replace("-", " ").replace("_", " ")
    except Exception:
        title_guess = None

    result["title"] = title_guess
    # parse chapter number from title then url
    result["number"] = parse_chapter_number(result["title"], url)

    # final tidying
    result["images"] = dedupe_preserve_order(result["images"])
    result["count"] = len(result["images"])

    if result["count"] == 0 and not result.get("note"):
        result["note"] = "No images found (page might require additional JS interactions or be protected)."

    return result
