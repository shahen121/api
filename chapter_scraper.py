# chapter_scraper.py
import asyncio
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
import scraper  # السكرابر الموحد الجديد
from playwright_worker import scrape_chapter_with_playwright 

# تعبيرات نمطية للبحث عن رقم الفصل
CHAPTER_RE_LIST = [
    re.compile(r'chapter[\s\-_\/:]*([0-9]+(?:\.[0-9]+)?)', re.I),
    re.compile(r'(^|\D)(\d+(?:\.\d+)?)(?:$|\D)', re.I),
]

# --- دالة تحليل رقم الفصل (هذه هي الدالة التي كانت مفقودة) ---
def parse_chapter_number(title: Optional[str], url: Optional[str]) -> Optional[float]:
    def try_find(s: str):
        if not s: return None
        for rx in CHAPTER_RE_LIST:
            m = rx.search(s)
            if m:
                for g in m.groups()[::-1]:
                    if g:
                        try: return float(g)
                        except: pass
        return None

    num = try_find(title or "")
    if num is not None: return num
    if url:
        return try_find(urlparse(url).path)
    return None

def dedupe_preserve_order(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))

# --- دالة جلب المحتوى (Async) ---
async def extract_chapter_content(
    url: str,
    cf: Optional[str] = None,
    ua: Optional[str] = None,
    playwright_fallback: bool = True,
    headless: bool = True,
    wait_after: float = 1.0
) -> Dict[str, Any]:
    
    result = {
        "url": url,
        "images": [],
        "count": 0,
        "sources": [],
        "note": ""
    }

    try:
        fast_res = await scraper.extract_images(url, ua=ua, cf_clearance=cf)
        if fast_res.get("images"):
            result["images"] = fast_res["images"]
            result["sources"].append("fast_static")
    except Exception as e:
        result["note"] = f"Fast error: {str(e)}"

    if not result["images"] and playwright_fallback:
        try:
            loop = asyncio.get_event_loop()
            pw_res = await loop.run_in_executor(
                None, scrape_chapter_with_playwright, 
                url, cf, ua, headless, wait_after
            )
            if pw_res.get("images"):
                result["images"] = pw_res["images"]
                result["sources"].append("playwright")
        except Exception as e:
            result["note"] += f" | PW error: {str(e)}"

    result["images"] = dedupe_preserve_order(result["images"])
    result["count"] = len(result["images"])
    # استخراج رقم الفصل ليكون متاحاً في النتيجة
    result["number"] = parse_chapter_number(None, url)
    
    return result
