# chapter_scraper.py
import asyncio
import scraper  # السكرابر الموحد الجديد
from playwright_worker import scrape_chapter_with_playwright 
from typing import Optional, List, Dict, Any

# دالة مساعدة لحذف التكرار مع الحفاظ على الترتيب
def dedupe_preserve_order(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))

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

    # 1) المحاولة الأولى: استخدام الجلب السريع (Async Scraper with Cache)
    try:
        # هنا نستخدم await لأن الدالة أصبحت async في scraper.py
        fast_res = await scraper.extract_images(url, ua=ua, cf_clearance=cf)
        if fast_res.get("images"):
            result["images"] = fast_res["images"]
            result["sources"].append("fast_static")
    except Exception as e:
        result["note"] = f"Fast scrape error: {str(e)}"

    # 2) المحاولة الثانية: Playwright (إذا لم نجد صوراً وكان الخيار مفعلاً)
    if not result["images"] and playwright_fallback:
        try:
            # بما أن playwright_worker هو sync، سنشغله في thread لعدم تعطيل الـ Event Loop
            loop = asyncio.get_event_loop()
            pw_res = await loop.run_in_executor(
                None, 
                scrape_chapter_with_playwright, 
                url, cf, ua, headless, wait_after
            )
            
            if pw_res.get("images"):
                result["images"] = pw_res["images"]
                result["sources"].append("playwright")
        except Exception as e:
            result["note"] += f" | Playwright error: {str(e)}"

    result["images"] = dedupe_preserve_order(result["images"])
    result["count"] = len(result["images"])
    
    return result
