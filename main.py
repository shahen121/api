import asyncio
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import uvicorn
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import tempfile, os, shutil, requests

# --- تحديث الاستيراد ليستخدم Playwright async ---
from series_scraper import fetch_series_list, extract_series_profile
from playwright_worker import scrape_chapter_with_playwright

app = FastAPI(title="AzoraMoon Full Scraper")

executor = ThreadPoolExecutor(max_workers=3)

@app.get("/ping")
def ping():
    return {"status": "ok"}

# ---------------------------------------------------------------------
# 🔹 GET /series/list  (Async + Playwright)
# ---------------------------------------------------------------------
@app.get("/series/list")
async def series_list(
    page_url: Optional[str] = Query(None, description="Optional full series page URL. Defaults to /series"),
    headless: bool = Query(True, description="Run Playwright headless"),
    wait_after: int = Query(1, description="Seconds to wait after load")
):
    url = page_url or "https://azoramoon.com/series"
    try:
        result = await fetch_series_list(url=url, headless=headless, wait_after=wait_after)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------
# 🔹 GET /series/profile
# ---------------------------------------------------------------------
@app.get("/series/profile")
def series_profile(url: str = Query(..., description="Full series URL (example https://azoramoon.com/series/nano-machine-s)")):
    try:
        profile = extract_series_profile(url)
        return JSONResponse(profile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------
# 🔹 GET /scrape/playwright (chapter images via Playwright)
# ---------------------------------------------------------------------
@app.get("/scrape/playwright")
async def scrape_playwright(
    url: str = Query(..., description="Chapter URL to scrape"),
    cf: Optional[str] = Query(None, description="cf_clearance cookie"),
    ua: Optional[str] = Query(None, description="User-Agent override"),
    headless: bool = Query(True, description="Run headless mode"),
    wait_after: float = Query(1.0, description="Seconds to wait after JS load")
):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            executor,
            scrape_chapter_with_playwright,
            url, cf, ua, headless, wait_after
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------
# 🔹 GET /scrape/playwright/download (ZIP output)
# ---------------------------------------------------------------------
@app.get("/scrape/playwright/download")
async def scrape_and_download_zip(
    url: str = Query(...),
    cf: Optional[str] = Query(None),
    ua: Optional[str] = Query(None),
    headless: bool = Query(True),
    wait_after: float = Query(1.0)
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, scrape_chapter_with_playwright, url, cf, ua, headless, wait_after)

    images = result.get("images") or []
    if not images:
        return JSONResponse({"url": url, "images": [], "note": "No images found"}, status_code=200)

    tmpdir = tempfile.mkdtemp(prefix="azoramoon_")
    try:
        headers = {"User-Agent": ua} if ua else {"User-Agent": "Mozilla/5.0"}

        # download images
        for idx, img_url in enumerate(images, start=1):
            ext = os.path.splitext(img_url)[1].split("?")[0] or ".jpg"
            filename = f"{idx:03d}{ext}"
            outpath = os.path.join(tmpdir, filename)
            try:
                r = requests.get(img_url, headers=headers, stream=True, timeout=30)
                if r.status_code == 200:
                    with open(outpath, "wb") as fh:
                        shutil.copyfileobj(r.raw, fh)
            except:
                pass

        # zip folder
        zip_base = tempfile.mktemp(suffix=".zip")
        shutil.make_archive(zip_base.replace(".zip", ""), "zip", tmpdir)
        zip_path = zip_base if zip_base.endswith(".zip") else zip_base + ".zip"

        return FileResponse(zip_path, filename="chapter_images.zip", media_type="application/zip")

    finally:
        pass  # ترك الملفات مؤقتًا للنظام

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
