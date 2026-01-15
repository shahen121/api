import httpx
import asyncio
import time
from bs4 import BeautifulSoup
from urllib.parse import unquote_plus
from typing import Optional, Dict, Any, Tuple

# الإعدادات الافتراضية
DEFAULT_TIMEOUT = 25
BASE_HOST = "https://azoramoon.com"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# نظام الكاش (مأخوذ من منطق utils.py)
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 180  # 3 دقائق

# ----------------------------
# أدوات مساعدة (Helpers)
# ----------------------------

def _make_cache_key(url: str, cookies: Optional[Dict] = None, headers: Optional[Dict] = None) -> str:
    key = url
    if cookies and "cf_clearance" in cookies:
        key += f"::cf={cookies['cf_clearance']}"
    if headers and "User-Agent" in headers:
        key += f"::ua={headers['User-Agent']}"
    return key

def _normalize_header_value(v: Optional[str]) -> str:
    if not v: return ""
    try:
        v = unquote_plus(v)
    except: pass
    return str(v).strip().strip('"').strip("'")

# ----------------------------
# وظيفة الجلب الأساسية (Async + Cache)
# ----------------------------



async def fetch_html(
    url: str,
    headers: Optional[Dict] = None,
    cookies: Optional[Dict] = None,
    ttl: int = CACHE_TTL,
    timeout: int = DEFAULT_TIMEOUT
) -> Tuple[bool, Any]:
    """
    تجلب HTML بشكل غير متزامن مع دعم الكاش.
    تعيد: (الحالة، المحتوى_أو_الخطأ)
    """
    now = time.time()
    cache_key = _make_cache_key(url, cookies, headers)
    
    # التحقق من الكاش أولاً
    entry = _CACHE.get(cache_key)
    if entry and now - entry["ts"] < ttl:
        return True, entry["html"]

    # إعداد الهيدرز
    final_headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": BASE_HOST + "/",
    }
    if headers:
        for k, v in headers.items():
            final_headers[k] = _normalize_header_value(v)

    try:
        async with httpx.AsyncClient(headers=final_headers, cookies=cookies, timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                return False, {"error": f"Status {response.status_code}", "url": url}
            
            html = response.text
            # تخزين في الكاش
            _CACHE[cache_key] = {"ts": now, "html": html}
            return True, html
            
    except Exception as e:
        return False, {"error": str(e), "url": url}

# ----------------------------
# دالة استخراج الصور (التي يستخدمها chapter_scraper)
# ----------------------------

async def extract_images(url: str, ua: Optional[str] = None, cf_clearance: Optional[str] = None):
    # تحضير الكوكيز إذا وجدت
    cookies = {}
    if cf_clearance:
        cookies["cf_clearance"] = _normalize_header_value(cf_clearance)
    
    headers = {"User-Agent": ua} if ua else None
    
    success, result = await fetch_html(url, headers=headers, cookies=cookies)
    
    if not success:
        return {"error": result.get("error"), "images": [], "count": 0}

    # منطق BeautifulSoup لاستخراج الصور (مبسط)
    soup = BeautifulSoup(result, "html.parser")
    images = []
    
    # البحث عن الصور في الأماكن المعتادة (wp-manga أو lazy load)
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if src.startswith("//"): src = "https:" + src
        if any(x in src for x in ["wp-manga/data", "storage", "chapter"]):
            images.append(src)
            
    return {
        "url": url,
        "images": list(dict.fromkeys(images)), # حذف التكرار
        "count": len(images)
    }
