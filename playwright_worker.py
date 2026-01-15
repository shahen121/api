# playwright_worker.py
import json
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

def deep_search_for_images(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            deep_search_for_images(v, out)
    elif isinstance(obj, list):
        for it in obj:
            deep_search_for_images(it, out)
    elif isinstance(obj, str):
        u = obj
        if u.startswith("http") and u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            out.append(u)

def normalize_url(u, base_url):
    if not u:
        return u
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}" + u
    return u

def _looks_like_chapter_image(u: str) -> bool:
    if not u:
        return False
    low = u.lower()
    # قبول روابط storage, wp-manga, upload, chapter_ — ورفض روابط معالجة/thumbnail الخارجية (مثلاً wsrv.nl)
    allowed = ("wp-manga/data", "storage.azoramoon.com", "/upload/", "chapter_")
    blocked = ("wsrv.nl", "/_next/static", "like.", "love.", "default-avatar", "icon", "emoji", "reaction")
    if any(b in low for b in blocked):
        return False
    return any(a in low for a in allowed)

def scrape_chapter_with_playwright(url: str, cf_clearance: str = None, ua: str = None, headless: bool = True, wait_after: float = 1.0):
    """
    Blocking function (sync). Returns dict:
    { "url": url, "images": [...], "sources": [...], "count": N, "error": ...? }
    """
    results = {"url": url, "images": [], "sources": [], "count": 0}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, args=["--no-sandbox"])
            context_args = {}
            if ua:
                context_args["user_agent"] = ua
            context = browser.new_context(**context_args)

            # set cf_clearance cookie if provided
            if cf_clearance:
                parsed = urlparse(url)
                domain = parsed.hostname
                cookie = {"name": "cf_clearance", "value": cf_clearance, "domain": domain, "path": "/", "httpOnly": False, "secure": True}
                context.add_cookies([cookie])

            page = context.new_page()

            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception:
                # محاولة ثانية بمهلة أطول
                page.goto(url, wait_until="networkidle", timeout=120000)

            time.sleep(wait_after)

            # محاولة تمرير بسيط لتحميل lazy images
            try:
                page.evaluate(
                    """() => {
                        const step = Math.max(document.documentElement.clientHeight || 800, 800);
                        let pos = 0;
                        for (let i=0;i<8;i++){
                            window.scrollTo(0, pos);
                            pos += step;
                        }
                        return true;
                    }"""
                )
                time.sleep(0.6)
            except Exception:
                pass

            # 1) imgs من DOM
            dom_imgs = page.eval_on_selector_all("img", "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '')")
            dom_imgs = [normalize_url(s, url) for s in dom_imgs if s]
            dom_imgs = list(dict.fromkeys(dom_imgs))
            if dom_imgs:
                results["images"].extend(dom_imgs)
                results["sources"].append("dom_img")

            # 2) __NEXT_DATA__
            try:
                next_data = page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); return s ? s.textContent : null }")
                if next_data:
                    try:
                        obj = json.loads(next_data)
                        found = []
                        deep_search_for_images(obj, found)
                        for f in found:
                            f = normalize_url(f, url)
                            if f not in results["images"]:
                                results["images"].append(f)
                        if found:
                            results["sources"].append("next_data")
                    except Exception:
                        pass
            except Exception:
                pass

            # 3) _next/data/{buildId}{path}.json
            try:
                buildId = page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); if(!s) return null; try{ const j = JSON.parse(s.textContent); return j.buildId || null }catch(e){return null} }")
                if buildId:
                    path = urlparse(url).path
                    next_json = f"{urlparse(url).scheme}://{urlparse(url).netloc}/_next/data/{buildId}{path}.json"
                    try:
                        res = page.request.get(next_json, timeout=60000)
                        if res.ok:
                            j = res.json()
                            found2 = []
                            deep_search_for_images(j, found2)
                            for f in found2:
                                f = normalize_url(f, url)
                                if f not in results["images"]:
                                    results["images"].append(f)
                            if found2:
                                results["sources"].append("next_json")
                    except Exception:
                        pass
            except Exception:
                pass

            # فلترة نهائية
            filtered = []
            for f in results["images"]:
                if _looks_like_chapter_image(f):
                    filtered.append(f)

            filtered = list(dict.fromkeys(filtered))
            results["images"] = filtered
            results["count"] = len(filtered)

            context.close()
            browser.close()
    except Exception as e:
        results["error"] = str(e)

    return results
