# main.py
import asyncio
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import uvicorn
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor
import tempfile, os, shutil, requests

# existing scrapers / workers
from series_scraper import extract_series_list, extract_series_profile
from playwright_worker import scrape_chapter_with_playwright
from chapter_scraper import extract_chapter_content, parse_chapter_number  # new file

app = FastAPI(title="AzoraMoon Full Scraper")

executor = ThreadPoolExecutor(max_workers=3)

@app.get("/ping")
def ping():
    return {"status": "ok"}

# --------------- list of series ---------------
@app.get("/series/list")
def series_list(page_url: Optional[str] = Query(None, description="Optional full series page URL. If omitted uses default /series")):
    url = page_url or "https://azoramoon.com/series"
    items = extract_series_list(url)
    return JSONResponse({"count": len(items), "items": items})

# --------------- series profile + chapters ---------------
@app.get("/series/profile")
def series_profile(url: str = Query(..., description="Full series URL (example https://azoramoon.com/series/nano-machine-s)")):
    profile = extract_series_profile(url)
    # try to normalize & sort chapters by numeric chapter number
    try:
        chapters = profile.get("chapters") or []
        def chap_key(c):
            # try parse number from the provided 'number' field, otherwise from title/url
            n = c.get("number")
            if n is not None:
                try:
                    return float(n)
                except:
                    pass
            # fallback uses parse_chapter_number heuristic
            return parse_chapter_number(c.get("title",""), c.get("url","")) or 1e9
        chapters_sorted = sorted(chapters, key=chap_key)
        profile["chapters"] = chapters_sorted
    except Exception:
        # leave profile unchanged on failure
        pass
    return JSONResponse(profile)

# --------------- chapter images (smart) ---------------
@app.get("/chapter/content")
async def chapter_content(
    url: str = Query(..., description="Chapter URL to scrape"),
    cf: Optional[str] = Query(None, description="cf_clearance cookie (optional)"),
    ua: Optional[str] = Query(None, description="User-Agent (optional)"),
    playwright_fallback: bool = Query(True, description="If True try Playwright when simple scrape returns no images"),
    headless: bool = Query(True, description="Playwright headless"),
    wait_after: float = Query(1.0, description="seconds to wait after load to allow lazy images")
):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            executor,
            extract_chapter_content,
            url, cf, ua, playwright_fallback, headless, wait_after
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(result)

# --------------- chapter download zip ---------------
@app.get("/chapter/download")
async def chapter_download(
    url: str = Query(...),
    cf: Optional[str] = Query(None),
    ua: Optional[str] = Query(None),
    playwright_fallback: bool = Query(True),
    headless: bool = Query(True),
    wait_after: float = Query(1.0)
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, extract_chapter_content, url, cf, ua, playwright_fallback, headless, wait_after)
    images = result.get("images") or []
    if not images:
        return JSONResponse({"url": url, "images": [], "note": "No images found"}, status_code=200)

    tmpdir = tempfile.mkdtemp(prefix="azoramoon_")
    try:
        headers = {"User-Agent": ua} if ua else {"User-Agent": "Mozilla/5.0"}
        for idx, img_url in enumerate(images, start=1):
            # try to get extension from url
            ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
            # sanitize extension
            if len(ext) > 8 or not ext.startswith("."):
                ext = ".jpg"
            filename = f"{idx:03d}{ext}"
            outpath = os.path.join(tmpdir, filename)
            try:
                with requests.get(img_url, headers=headers, stream=True, timeout=30) as r:
                    if r.status_code == 200:
                        with open(outpath, "wb") as fh:
                            shutil.copyfileobj(r.raw, fh)
            except Exception:
                # skip failing images
                pass

        # make zip
        zip_base = tempfile.mktemp(suffix=".zip")
        shutil.make_archive(zip_base.replace(".zip",""), 'zip', tmpdir)
        zip_path = zip_base if zip_base.endswith(".zip") else zip_base + ".zip"
        return FileResponse(zip_path, filename="chapter_images.zip", media_type="application/zip")
    finally:
        # keep files for a moment (or implement cleanup)
        pass

# --------------- Playwright endpoint retained for backwards compatibility ---------------
@app.get("/scrape/playwright")
async def scrape_playwright(
    url: str = Query(..., description="Chapter URL to scrape"),
    cf: Optional[str] = Query(None, description="cf_clearance cookie (optional)"),
    ua: Optional[str] = Query(None, description="User-Agent (optional)"),
    headless: bool = Query(True, description="Run headless? default true"),
    wait_after: float = Query(1.0, description="seconds to wait after load to allow lazy images")
):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            executor,
            scrape_chapter_with_playwright,
            url, cf, ua, headless, wait_after
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(result)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
