# series_scraper.py
"""
Series scraper for AzoraMoon.

- fetch_series_list(...)  -> async function (returns list of series via Playwright)
- extract_series_profile(...) -> sync wrapper that returns series profile using Playwright
"""

import time
import asyncio
import re
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# small in-memory cache
_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 60

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _normalize_str(x):
    if not x:
        return ""
    return str(x).strip()

# -------------------- internal: run playwright and return evaluated items --------------------
async def _run_playwright_extract(url: str, headless: bool = True, wait_after: float = 1.0, ua: Optional[str] = None, timeout: int = 30000):
    ua = ua or DEFAULT_UA
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page(user_agent=ua)
            await page.set_extra_http_headers({"Referer": "https://azoramoon.com/"})
            await page.goto(url, wait_until="networkidle", timeout=timeout)
            if wait_after:
                await page.wait_for_timeout(int(wait_after * 1000))

            # Evaluate JS on page to collect candidate series links
            items = await page.evaluate(
                """() => {
                    const out = [];
                    const seen = new Set();
                    // first try to find clear anchors that look like series tiles
                    const anchors = Array.from(document.querySelectorAll('a[href*="/series/"]'));
                    for (const a of anchors) {
                        try {
                            const href = a.href;
                            if (!href.includes('/series/') || href.match(/\\/series\\/?$/)) continue;
                            if (seen.has(href)) continue;
                            seen.add(href);

                            // try get title from common places
                            let title = '';
                            const titleEl = a.querySelector('h1,h2,h3,h4,.title,.name') || a.querySelector('span, p');
                            if (titleEl) title = (titleEl.innerText || titleEl.textContent || '').trim();

                            // try get image
                            let img = '';
                            const imgEl = a.querySelector('img');
                            if (imgEl && imgEl.src) img = imgEl.src;
                            else {
                                // fallback to background-image style
                                const bg = a.querySelector('[style*=\"background-image\"]') || a;
                                const style = bg && bg.style ? bg.style.backgroundImage : '';
                                if (style && style.includes('url')) {
                                    img = style.replace(/url\\(|\\)|\\"|\\'/g, '').trim();
                                }
                            }

                            const p = a.querySelector('p, .desc, .subtitle, .summary');
                            const summary = p ? (p.innerText || p.textContent || '').trim() : '';

                            out.push({title: title || '', url: href, cover: img || '', summary});
                        } catch(e) {}
                    }

                    // fallback scan if nothing found
                    if (out.length === 0) {
                        const cards = Array.from(document.querySelectorAll('div.grid a, section a, .card a'));
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

# exposed async function (used by main /series/list)
async def fetch_series_list(url: str = "https://azoramoon.com/series", headless: bool = True, wait_after: float = 1.0, ua: Optional[str] = None, cache_ttl: int = CACHE_TTL) -> Dict[str, Any]:
    cache_key = f"series_list::{url}"
    now = time.time()
    if cache_key in _cache:
        item = _cache[cache_key]
        if now - item["ts"] < cache_ttl:
            return {"url": url, "count": len(item["data"]), "items": item["data"], "cached": True}

    data = await _run_playwright_extract(url, headless=headless, wait_after=wait_after, ua=ua)
    if isinstance(data, dict) and data.get("error"):
        return {"url": url, "count": 0, "items": [], "error": data}

    items: List[Dict[str, str]] = []
    seen_urls = set()
    for it in data:
        try:
            href = it.get("url") or ""
            title = _normalize_str(it.get("title"))
            cover = _normalize_str(it.get("cover"))
            if not href:
                continue
            if href.startswith("/"):
                href = "https://azoramoon.com" + href
            if href in seen_urls:
                continue
            seen_urls.add(href)
            items.append({"title": title, "url": href, "cover": cover})
        except Exception:
            continue

    _cache[cache_key] = {"ts": now, "data": items}
    return {"url": url, "count": len(items), "items": items, "cached": False}

# -------------------- profile extraction (Playwright) --------------------
async def _run_playwright_profile(url: str, headless: bool = True, wait_after: float = 1.0, ua: Optional[str] = None, timeout: int = 30000) -> Dict[str, Any]:
    ua = ua or DEFAULT_UA
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page(user_agent=ua)
            await page.set_extra_http_headers({"Referer": "https://azoramoon.com/"})
            await page.goto(url, wait_until="networkidle", timeout=timeout)
            if wait_after:
                await page.wait_for_timeout(int(wait_after * 1000))

            # Parse visible DOM and fallback to __NEXT_DATA__ JSON if present
            data = await page.evaluate(
                """() => {
                    const out = { title: '', cover: '', description: '', author: '', genres: [], status: '', chapters: [] };
                    // title
                    const h1 = document.querySelector('h1') || document.querySelector('.title');
                    out.title = h1 ? (h1.innerText || h1.textContent || '').trim() : '';

                    // cover
                    const coverImg = document.querySelector('img[src*="storage.azoramoon.com"], .series-cover img, .cover img') || document.querySelector('img');
                    out.cover = coverImg && coverImg.src ? coverImg.src : '';

                    // description
                    const desc = document.querySelector('.description, .desc, .summary, .series-description') || document.querySelector('meta[name="description"]');
                    if (desc) {
                        out.description = desc.innerHTML ? desc.innerHTML.trim() : (desc.content || desc.innerText || desc.textContent || '').trim();
                    }

                    // metadata (author/genres/status)
                    const metaCandidates = Array.from(document.querySelectorAll('li, dd, .meta > div, .info > div, .attributes div, .meta-item, .series-meta'));
                    for (const el of metaCandidates) {
                        try {
                            const txt = (el.innerText || el.textContent || '').trim();
                            if (!txt) continue;
                            const lower = txt.toLowerCase();
                            if (lower.includes('author') || lower.includes('الكاتب') || lower.includes('المؤلف')) {
                                out.author = txt.replace(/author|الكاتب|المؤلف/ig, '').trim();
                            } else if (lower.includes('genre') || lower.includes('genres') || lower.includes('النوع')) {
                                // collect child anchors/spans as genres if present
                                const kids = Array.from(el.querySelectorAll('a,span')) || [];
                                if (kids.length) {
                                    out.genres = kids.map(k => (k.innerText||k.textContent||'').trim()).filter(Boolean);
                                } else {
                                    out.genres = txt.replace(/genre|genres|النوع/ig,'').split(/,|·|•/).map(s=>s.trim()).filter(Boolean);
                                }
                            } else if (lower.includes('status') || lower.includes('الحالة')) {
                                out.status = txt.replace(/status|الحالة/ig,'').trim();
                            }
                        } catch(e){}
                    }

                    // chapters: anchors containing '/chapter'
                    const anchors = Array.from(document.querySelectorAll('a[href*="/chapter"]'));
                    const seen = new Set();
                    for (const a of anchors) {
                        try {
                            const href = a.href;
                            if (!href || seen.has(href)) continue;
                            seen.add(href);
                            const text = (a.innerText || a.textContent || '').trim();
                            out.chapters.push({ title: text || '', url: href });
                        } catch(e){}
                    }

                    // fallback: __NEXT_DATA__ JSON inspection
                    const script = document.getElementById('__NEXT_DATA__');
                    if (script && script.innerText) {
                        try {
                            const j = JSON.parse(script.innerText);
                            function deepSearch(obj) {
                                if (!obj || typeof obj !== 'object') return null;
                                if (obj.title && (obj.pages || obj.chapters)) return obj;
                                for (const k in obj) {
                                    try {
                                        const v = obj[k];
                                        const r = deepSearch(v);
                                        if (r) return r;
                                    } catch(e){}
                                }
                                return null;
                            }
                            const found = deepSearch(j);
                            if (found) {
                                out.title = out.title || (found.title || '');
                                if (found.cover) out.cover = out.cover || found.cover;
                                const pages = found.pages || found.chapters || [];
                                if (Array.isArray(pages) && pages.length) {
                                    out.chapters = out.chapters.concat(pages.map((p,i)=>({title: p.title || ('Chapter '+(i+1)), url: p.url || p.page || ''})));
                                }
                            }
                        } catch(e){}
                    }

                    return out;
                }"""
            )

            # normalize chapters: try to extract numeric chapter numbers using Python-side regex later
            await browser.close()
            return data

    except PlaywrightTimeoutError as e:
        return {"error": "timeout", "detail": str(e)}
    except Exception as e:
        return {"error": "playwright_error", "detail": str(e)}

# public sync wrapper (safe to import and call from sync code)
def extract_series_profile(url: str, headless: bool = True, wait_after: float = 1.0, ua: Optional[str] = None) -> Dict[str, Any]:
    """
    Synchronous wrapper that launches an asyncio run to extract series profile.
    Returns dict with fields: url, title, cover, description, author, genres, status, chapters
    """
    cache_key = f"series_profile::{url}"
    now = time.time()
    if cache_key in _cache:
        item = _cache[cache_key]
        if now - item["ts"] < CACHE_TTL:
            return {"url": url, **item["data"], "cached": True}

    try:
        data = asyncio.run(_run_playwright_profile(url, headless=headless, wait_after=wait_after, ua=ua))
    except Exception as e:
        return {"url": url, "error": "run_error", "detail": str(e)}

    if isinstance(data, dict) and data.get("error"):
        return {"url": url, "error": data}

    profile = {
        "title": _normalize_str(data.get("title")),
        "cover": _normalize_str(data.get("cover")),
        "description": _normalize_str(data.get("description")),
        "author": _normalize_str(data.get("author")),
        "genres": data.get("genres") or [],
        "status": _normalize_str(data.get("status")),
        "chapters": []
    }

    # Python-side regex extraction for chapter number (fixes previous JS-regex-in-Python bug)
    chapter_re = re.compile(r'chapter\s*([0-9]+(?:\.[0-9]+)?)', re.I)
    chapter_re_alt = re.compile(r'chapter[-/]*([0-9]+(?:\.[0-9]+)?)', re.I)

    for ch in data.get("chapters", []) or []:
        try:
            title = _normalize_str(ch.get("title"))
            u = _normalize_str(ch.get("url"))
            num = None
            # prefer extracting from title first
            m = chapter_re.search(title) if title else None
            if not m and u:
                m = chapter_re_alt.search(u)
            if m:
                val = m.group(1)
                try:
                    num = float(val) if '.' in val else int(val)
                except Exception:
                    num = None
            profile["chapters"].append({"title": title, "url": u, "number": num})
        except Exception:
            continue

    # sort chapters by number when numbers available (ascending)
    try:
        if any(ch.get("number") is not None for ch in profile["chapters"]):
            profile["chapters"] = sorted(profile["chapters"], key=lambda x: (x.get("number") is None, x.get("number") if x.get("number") is not None else 0))
    except Exception:
        pass

    _cache[cache_key] = {"ts": now, "data": profile}
    return {"url": url, **profile}
