# playwright_scraper.py
import argparse
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


def run(url, cf_clearance=None, ua=None, headless=True, wait_after=1.0, out_file=None):
    results = {"url": url, "images": [], "sources": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = browser.new_context()
        # set UA if provided
        if ua:
            context = browser.new_context(user_agent=ua)
        # add cf_clearance cookie if provided
        if cf_clearance:
            parsed = urlparse(url)
            domain = parsed.hostname
            cookie = {"name": "cf_clearance", "value": cf_clearance, "domain": domain, "path": "/", "httpOnly": False, "secure": True}
            context.add_cookies([cookie])

        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            # try a second time with longer timeout
            try:
                page.goto(url, wait_until="networkidle", timeout=120000)
            except Exception as e2:
                results["error"] = f"goto_error: {e} | {e2}"
                browser.close()
                return results

        # optional short wait to let lazy-load finish (images load after some scroll)
        time.sleep(wait_after)

        # try to scroll slowly to trigger lazy loading
        try:
            page.evaluate(
                """() => {
                    const step = Math.max(document.documentElement.clientHeight || 800, 800);
                    let pos = 0;
                    for (let i=0;i<6;i++){
                        window.scrollTo(0, pos);
                        pos += step;
                    }
                    return true;
                }"""
            )
            time.sleep(0.7)
        except Exception:
            pass

        # 1) collect img.src and data-src from DOM
        dom_imgs = page.eval_on_selector_all("img", "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '')")
        dom_imgs = [s for s in dom_imgs if s]
        # normalize protocol-relative and relative paths
        normalized = []
        for s in dom_imgs:
            if s.startswith("//"):
                s = "https:" + s
            elif s.startswith("/"):
                s = f"{urlparse(url).scheme}://{urlparse(url).netloc}" + s
            normalized.append(s)
        normalized = list(dict.fromkeys(normalized))
        results["images"].extend(normalized)
        if normalized:
            results["sources"].append("dom_img")

        # 2) try to read __NEXT_DATA__ script
        try:
            next_data = page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); return s ? s.textContent : null }")
            if next_data:
                try:
                    obj = json.loads(next_data)
                    found = []
                    deep_search_for_images(obj, found)
                    # normalize duplicates & add
                    for f in found:
                        if f.startswith("//"):
                            f = "https:" + f
                        if f not in results["images"]:
                            results["images"].append(f)
                    if found:
                        results["sources"].append("next_data")
                except Exception:
                    pass
        except Exception:
            pass

        # 3) try to fetch _next/data/{buildId}{path}.json if present in __NEXT_DATA__ or link tag
        try:
            buildId = page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); if(!s) return null; try{ const j = JSON.parse(s.textContent); return j.buildId || null }catch(e){return null} }")
            if buildId:
                path = urlparse(url).path
                next_json = f"{urlparse(url).scheme}://{urlparse(url).netloc}/_next/data/{buildId}{path}.json"
                # fetch via page (to use same context/cookies)
                try:
                    res = page.request.get(next_json, timeout=60000)
                    if res.ok:
                        j = res.json()
                        found2 = []
                        deep_search_for_images(j, found2)
                        for f in found2:
                            if f.startswith("//"):
                                f = "https:" + f
                            if f not in results["images"]:
                                results["images"].append(f)
                        if found2:
                            results["sources"].append("next_json")
                except Exception:
                    pass
        except Exception:
            pass

        # 4) final filter: accept images that look like chapter images
        filtered = []
        for f in results["images"]:
            low = f.lower()
            if "wp-manga/data" in low or "storage.azoramoon.com" in low or "/upload/" in low or "chapter_" in low:
                filtered.append(f)
        filtered = list(dict.fromkeys(filtered))
        results["images"] = filtered
        results["count"] = len(filtered)

        if out_file:
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=2)

        browser.close()
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="chapter URL")
    parser.add_argument("--cf", help="cf_clearance cookie value (optional)")
    parser.add_argument("--ua", help="User-Agent (optional)")
    parser.add_argument("--headless", action="store_true", help="run headless (default: visible). Use --headless to enable headless.")
    parser.add_argument("--out", help="output JSON file path (optional)")
    args = parser.parse_args()

    # default: headful (visible). If you prefer headless, pass --headless
    headless_flag = bool(args.headless)

    res = run(args.url, cf_clearance=args.cf, ua=args.ua, headless=headless_flag, wait_after=1.0, out_file=args.out)
    print(json.dumps(res, ensure_ascii=False, indent=2))
