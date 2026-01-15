import json
import time
import os
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
    allowed = ("wp-manga/data", "storage.azoramoon.com", "/upload/", "chapter_")
    blocked = ("wsrv.nl", "/_next/static", "like.", "love.", "default-avatar", "icon", "emoji", "reaction")
    if any(b in low for b in blocked):
        return False
    return any(a in low for a in allowed)

def scrape_chapter_with_playwright(url: str, cf_clearance: str = None, ua: str = None, headless: bool = True, wait_after: float = 1.0):
    results = {"url": url, "images": [], "sources": [], "count": 0}

    # التأكد من المسار
    local_browsers_path = os.path.join(os.getcwd(), "playwright-browsers")
    if os.path.exists(local_browsers_path):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = local_browsers_path

    try:
        with sync_playwright() as p:
            # 1. إعدادات تقليل الذاكرة القصوى
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",  # هام جداً للسيرفرات المحدودة
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--single-process" # قد يساعد في تقليل العمليات
                ]
            )
            
            context_args = {}
            if ua:
                context_args["user_agent"] = ua
            context = browser.new_context(**context_args)

            # 2. حظر تحميل الموارد الثقيلة لتوفير الرام
            # سنمنع المتصفح من تحميل الصور والخطوط والميديا، نحن نحتاج الـ HTML فقط
            def block_heavy_resources(route):
                if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                    route.abort()
                else:
                    route.continue_()

            # تطبيق الحظر على كل الصفحات
            # ملاحظة: إذا كان الموقع يعتمد على تحميل الصور لظهور الروابط في الـ DOM، قد نحتاج لإلغاء حظر "image"
            # لكن في الغالب الروابط تكون موجودة في الكود (src) حتى لو لم يتم التحميل
            
            # في حالتك: AzoraMoon قد يحتاج لتحميل السكربتات، لذا لن نحظر السكربتات، فقط الصور
            page = context.new_page()
            page.route("**/*", block_heavy_resources)

            if cf_clearance:
                parsed = urlparse(url)
                domain = parsed.hostname
                cookie = {"name": "cf_clearance", "value": cf_clearance, "domain": domain, "path": "/", "httpOnly": False, "secure": True}
                context.add_cookies([cookie])

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000) # استخدام domcontentloaded أسرع وأخف
            except Exception:
                pass

            time.sleep(wait_after)

            # محاولة بسيطة للتمرير (بدون تحميل الصور فعلياً لأننا حظرناها، لكن لتفعيل السكربتات)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)
            except:
                pass

            # 1) استخراج من DOM
            dom_imgs = page.eval_on_selector_all("img", "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '')")
            dom_imgs = [normalize_url(s, url) for s in dom_imgs if s]
            
            if dom_imgs:
                results["images"].extend(dom_imgs)
                results["sources"].append("dom_img")

            # 2) محاولة JSON (خفيفة ولا تستهلك رام)
            try:
                next_data = page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); return s ? s.textContent : null }")
                if next_data:
                    obj = json.loads(next_data)
                    found = []
                    deep_search_for_images(obj, found)
                    for f in found:
                        results["images"].append(normalize_url(f, url))
            except:
                pass

            # تنظيف وإغلاق سريع
            context.close()
            browser.close()

            # فلترة
            filtered = []
            seen = set()
            for f in results["images"]:
                if f not in seen and _looks_like_chapter_image(f):
                    seen.add(f)
                    filtered.append(f)
            
            results["images"] = list(filtered)
            results["count"] = len(filtered)

    except Exception as e:
        results["error"] = f"LowMemoryMode Error: {str(e)}"

    return results
