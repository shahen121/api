# series_scraper.py
import time
import asyncio
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# بسيط in-memory cache (TTL بالثواني)
_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 60  # ثانية — غيّر حسب حاجتك

# user-agent افتراضي (تقدر تمرر غيره)
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

async def _run_playwright_extract(url: str, headless: bool = True, wait_after: float = 1.0, ua: Optional[str] = None, timeout: int = 30000):
    ua = ua or DEFAULT_UA
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page(user_agent=ua)
            # بعض المواقع تحتاج ريفيرر
            await page.set_extra_http_headers({"Referer": "https://azoramoon.com/"})
            await page.goto(url, wait_until="networkidle", timeout=timeout)
            # انتظر شوية للسماح للـ JS بتحميل القوائم lazy
            if wait_after:
                await page.wait_for_timeout(int(wait_after * 1000))

            # Evaluate داخل الصفحة لجمع الروابط و البيانات
            items = await page.evaluate(
                """() => {
                    const out = [];
                    const seen = new Set();

                    // نبحث عن أي رابط يؤدي الى /series/ مع تجاهل روابط نافبار العامة
                    const anchors = Array.from(document.querySelectorAll('a[href*="/series/"]'));
                    for (const a of anchors) {
                        try {
                            const href = a.href;
                            if (!href.includes('/series/') || href.match(/\\/series\\/?$/)) continue;
                            if (seen.has(href)) continue;
                            seen.add(href);

                            // عنوان محتمل
                            const titleEl = a.querySelector('h3, h4, .title, .name') || a.querySelector('span, p');
                            const title = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : (a.getAttribute('title') || a.textContent || '').trim();

                            // صورة محتملة
                            let img = '';
                            const imgEl = a.querySelector('img');
                            if (imgEl && imgEl.src) img = imgEl.src;
                            else {
                                // محاولة التقاط background-image
                                const bg = a.querySelector('[style*="background"], .card, .cover') || a;
                                const style = bg && bg.style ? bg.style.backgroundImage : '';
                                if (style && style.includes('url')) {
                                    img = style.replace(/url\\(|\\)|"|'/g, '').trim();
                                }
                            }

                            // إستخراج نص مختصر (fallback)
                            let summary = '';
                            const p = a.querySelector('p, .desc, .subtitle');
                            if (p) summary = (p.innerText || p.textContent || '').trim();

                            out.push({title: title || '', url: href, cover: img || '', summary});
                        } catch(e) {
                            // تجاهل عنصر اذا فيه خطأ
                        }
                    }

                    // لو ما لقينا أي عنصر، نحاول جلب من داخل العناصر المربوطة بالقائمة الرئيسية
                    if (out.length === 0) {
                        const cards = Array.from(document.querySelectorAll('div.grid a, section a'));
                        for (const a of cards) {
                            try {
                                const href = a.href;
                                if (!href || !href.includes('/series/') || href.match(/\\/series\\/?$/)) continue;
                                if (seen.has(href)) continue;
                                seen.add(href);
                                const title = (a.getAttribute('title') || a.innerText || '').trim();
                                const img = a.querySelector('img')?.src || '';
                                out.push({title, url: href, cover: img});
                            } catch(e){}
                        }
                    }
                    return out;
                }"""
            )
            await browser.close()
            return items
    except PlaywrightTimeoutError as e:
        return {"error": "timeout", "detail": str(e)}
    except Exception as e:
        return {"error": "playwright_error", "detail": str(e)}


async def fetch_series_list(url: str = "https://azoramoon.com/series", headless: bool = True, wait_after: float = 1.0, ua: Optional[str] = None, cache_ttl: int = CACHE_TTL) -> Dict[str, Any]:
    cache_key = f"series_list::{url}"
    now = time.time()
    # تحقق من الكاش
    if cache_key in _cache:
        item = _cache[cache_key]
        if now - item["ts"] < cache_ttl:
            return {"url": url, "count": len(item["data"]), "items": item["data"], "cached": True}

    # نفذ Playwright واخرج العناصر
    data = await _run_playwright_extract(url, headless=headless, wait_after=wait_after, ua=ua)

    # لو حصلنا على خطأ من Playwright، أعيده كما هو
    if isinstance(data, dict) and data.get("error"):
        return {"url": url, "images": [], "items": [], "count": 0, "error": data}

    # تنظيف وتهيئة العناصر
    items: List[Dict[str, str]] = []
    seen_urls = set()
    for it in data:
        try:
            href = it.get("url") or ""
            title = (it.get("title") or "").strip()
            cover = (it.get("cover") or "").strip()
            if not href:
                continue
            # تأكد من أن الرابط كامل http(s)
            if href.startswith("/"):
                href = "https://azoramoon.com" + href
            if href in seen_urls:
                continue
            seen_urls.add(href)
            items.append({"title": title, "url": href, "cover": cover})
        except Exception:
            continue

    # خزّن في الكاش
    _cache[cache_key] = {"ts": now, "data": items}
    return {"url": url, "count": len(items), "items": items, "cached": False}
