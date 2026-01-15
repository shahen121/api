# utils.py
import time
import os
from typing import Optional, Dict
import requests
from urllib.parse import urlparse

# افتراضي User-Agent (يمكن تغييره عبر env: AZ_USER_AGENT)
DEFAULT_UA = os.getenv("AZ_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)

# كاش بسيط في الذاكرة
_CACHE: Dict[str, Dict] = {}
CACHE_TTL = int(os.getenv("AZ_CACHE_TTL", 60 * 3))  # 3 دقائق افتراضياً

def _make_cache_key(url: str, cookies: Optional[Dict[str,str]], headers: Optional[Dict[str,str]]):
    key = url
    # لو في cf_clearance ضعه في المفتاح (لأن HTML يختلف حسبه)
    if cookies and "cf_clearance" in cookies:
        key += f"::cf={cookies['cf_clearance']}"
    # لو UA مرفوع
    if headers and "User-Agent" in headers:
        key += f"::ua={headers['User-Agent']}"
    return key

def parse_cookie_string(cookie_str: str) -> Dict[str,str]:
    """
    تحويل سلسلة كوكيز مثل "cf_clearance=XXX; other=Y" إلى dict
    """
    cookies = {}
    if not cookie_str:
        return cookies
    parts = cookie_str.split(";")
    for p in parts:
        if "=" in p:
            k,v = p.strip().split("=",1)
            cookies[k] = v
    return cookies

def cached_fetch(url: str, ttl: int = CACHE_TTL, headers: Optional[Dict[str,str]] = None,
                 cookies: Optional[Dict[str,str]] = None, timeout: int = 15) -> str:
    """
    يجلب الصفحة ويخزنها في كاش بسيط. يدعم تمرير cookies و headers.
    """
    now = time.time()
    cache_key = _make_cache_key(url, cookies, headers)
    entry = _CACHE.get(cache_key)
    if entry and now - entry["ts"] < ttl:
        return entry["html"]

    sess = requests.Session()
    # إعداد الهيدرز الأساسية
    sess.headers.update({"User-Agent": DEFAULT_UA, "Accept": "*/*", "Accept-Language":"en-US,en;q=0.9"})
    if headers:
        sess.headers.update(headers)

    if cookies:
        # يمكن تمرير dict أو string
        if isinstance(cookies, str):
            cookies = parse_cookie_string(cookies)
        sess.cookies.update(cookies)

    r = sess.get(url, timeout=timeout)
    r.raise_for_status()
    html = r.text
    _CACHE[cache_key] = {"ts": now, "html": html}
    # وقفة قصيرة لتقليل احتمالية الحظر عند سلسلة طلبات
    time.sleep(0.25)
    return html
