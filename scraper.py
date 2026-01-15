# scraper.py
import httpx
from bs4 import BeautifulSoup
from urllib.parse import unquote_plus

DEFAULT_TIMEOUT = 25
BASE_HOST = "https://azoramoon.com"


# ----------------------------
# Helpers
# ----------------------------

def _normalize_header_value(v: str | None) -> str | None:
    if v is None:
        return None
    try:
        v = unquote_plus(v)
    except Exception:
        pass
    return v.strip().strip('"').strip("'")


def _safe_headers(headers: dict | None) -> dict | None:
    if not headers:
        return None
    out = {}
    for k, v in headers.items():
        if v is None:
            continue
        if not isinstance(v, str):
            v = str(v)
        out[k] = _normalize_header_value(v)
    return out or None


# ----------------------------
# HTTP Fetch
# ----------------------------

def fetch_html(
    url: str,
    headers: dict | None = None,
    cookies: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
):
    """
    Returns:
      (True, html_text)
      (False, {error info})
    """
    try:
        with httpx.Client(
            headers=_safe_headers(headers),
            cookies=cookies or None,
            timeout=timeout,
            http2=True,
            follow_redirects=True,
        ) as client:
            resp = client.get(url)

            # Force UTF-8
            try:
                resp.encoding = "utf-8"
            except Exception:
                pass

            if resp.status_code != 200:
                return False, {
                    "error": "bad_status",
                    "status_code": resp.status_code,
                    "body_snippet": (resp.text or "")[:1500],
                }

            return True, resp.text

    except httpx.RequestError as e:
        return False, {"error": "request_error", "detail": str(e)}
    except Exception as e:
        return False, {"error": "unknown_error", "detail": str(e)}


# ----------------------------
# Image Extraction
# ----------------------------

def _is_ui_or_icon(url: str) -> bool:
    bad = [
        "_next/static",
        "default-avatar",
        "like.",
        "love.",
        "laugh.",
        "wow.",
        "cry.",
        "angry.",
        "emoji",
        "icon",
        "reaction",
    ]
    u = url.lower()
    return any(x in u for x in bad)


def _looks_like_chapter_image(url: str) -> bool:
    u = url.lower()
    return (
        "storage.azoramoon.com" in u
        or "/upload/" in u
        or "chapter_" in u
    ) and u.endswith((".jpg", ".jpeg", ".png", ".webp"))


def extract_images_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    images: list[str] = []

    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src") or ""
        src = src.strip()
        if not src:
            continue

        # normalize URL
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = BASE_HOST + src

        if _is_ui_or_icon(src):
            continue

        if _looks_like_chapter_image(src):
            images.append(src)

    # remove duplicates (keep order)
    return list(dict.fromkeys(images))


# ----------------------------
# Public API
# ----------------------------

def extract_images(
    url: str,
    ua: str | None = None,
    cf_clearance: str | None = None,
    cookie_header: str | None = None,
):
    """
    Main function used by FastAPI

    Success:
      {
        "url": "...",
        "images": [...],
        "count": N
      }

    Failure:
      {
        "error": "...",
        "debug": {...}
      }
    """

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE_HOST + "/",
        "Upgrade-Insecure-Requests": "1",
    }

    if ua:
        headers["User-Agent"] = _normalize_header_value(ua)

    cookies: dict[str, str] = {}

    # cookie header: "k=v; k2=v2"
    if cookie_header:
        try:
            for part in cookie_header.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()
        except Exception:
            pass

    # cf_clearance
    if cf_clearance:
        if cf_clearance.startswith("cf_clearance="):
            k, v = cf_clearance.split("=", 1)
            cookies[k] = v
        else:
            cookies["cf_clearance"] = cf_clearance

    ok, result = fetch_html(url, headers=headers, cookies=cookies)
    if not ok:
        return {"error": "fetch_failed", "debug": result}

    html = result
    images = extract_images_from_html(html)

    return {
        "url": url,
        "images": images,
        "count": len(images),
    }
