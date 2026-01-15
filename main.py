import asyncio
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

# استيراد الوظائف من الملفات المحلية
from chapter_scraper import extract_chapter_content, parse_chapter_number
from playwright_worker import scrape_chapter_with_playwright
from series_scraper import extract_series_profile, fetch_series_list

app = FastAPI(title="AzoraMoon Full Scraper (Unified Async)")

# تم الاحتفاظ بـ ThreadPoolExecutor لعمليات ضغط الملفات (Zipping) لأنها تستهلك المعالج
executor = ThreadPoolExecutor(max_workers=5)

@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "Server is running smoothly"}

# --------------- قائمة السلاسل (Series List) ---------------
@app.get("/series/list")
async def series_list(
    page_url: Optional[str] = Query(None, description="رابط صفحة السلسلة (اختياري)")
):
    url = page_url or "https://azoramoon.com/series"
    # fetch_series_list هي دالة async في الأصل
    result = await fetch_series_list(url)
    items = result.get("items", [])
    return JSONResponse({"count": len(items), "items": items})

# --------------- الملف الشخصي للسلسلة (Series Profile) ---------------
@app.get("/series/profile")
def series_profile(
    url: str = Query(..., description="رابط السلسلة بالكامل")
):
    # هذه الدالة حالياً هي Wrapper متزامن (Sync) في ملف series_scraper
    profile = extract_series_profile(url)
    
    # ترتيب الفصول رقمياً لضمان تجربة مستخدم أفضل
    try:
        chapters = profile.get("chapters") or []
        def chap_key(c):
            n = c.get("number")
            if n is not None:
                try:
                    return float(n)
                except:
                    pass
            return parse_chapter_number(c.get("title", ""), c.get("url", "")) or 1e9
            
        profile["chapters"] = sorted(chapters, key=chap_key)
    except Exception:
        pass
        
    return JSONResponse(profile)

# --------------- محتوى الفصل (Chapter Content) ---------------
@app.get("/chapter/content")
async def chapter_content(
    url: str = Query(..., description="رابط الفصل لجلب الصور"),
    cf: Optional[str] = Query(None, description="cf_clearance cookie"),
    ua: Optional[str] = Query(None, description="User-Agent"),
    playwright_fallback: bool = Query(True, description="استخدام Playwright كحل احتياطي"),
    headless: bool = Query(True),
    wait_after: float = Query(1.0)
):
    try:
        # استدعاء مباشر بـ await بفضل التعديلات في chapter_scraper
        result = await extract_chapter_content(
            url, cf, ua, playwright_fallback, headless, wait_after
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --------------- تحميل الصور كملف ZIP ---------------
@app.get("/chapter/download")
async def chapter_download(
    url: str = Query(...),
    cf: Optional[str] = Query(None),
    ua: Optional[str] = Query(None)
):
    # 1. جلب روابط الصور
    result = await extract_chapter_content(url, cf, ua)
    images = result.get("images") or []
    
    if not images:
        return JSONResponse({"error": "No images found"}, status_code=404)

    tmpdir = tempfile.mkdtemp(prefix="azora_dl_")
    headers = {"User-Agent": ua or "Mozilla/5.0"}

    # 2. تحميل الصور بشكل غير متزامن (Async Download)
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for idx, img_url in enumerate(images, start=1):
            try:
                # معالجة الامتداد
                ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                if len(ext) > 5: ext = ".jpg"
                
                filename = f"{idx:03d}{ext}"
                outpath = os.path.join(tmpdir, filename)
                
                resp = await client.get(img_url)
                if resp.status_code == 200:
                    with open(outpath, "wb") as f:
                        f.write(resp.content)
            except Exception:
                continue

    # 3. إنشاء ملف ZIP (في Thread منفصل لعدم تجميد السيرفر)
    def create_zip(source_dir):
        zip_base = tempfile.mktemp(suffix=".zip")
        shutil.make_archive(zip_base.replace(".zip", ""), 'zip', source_dir)
        return zip_base if zip_base.endswith(".zip") else zip_base + ".zip"

    loop = asyncio.get_event_loop()
    zip_path = await loop.run_in_executor(executor, create_zip, tmpdir)

    return FileResponse(
        zip_path, 
        filename=f"chapter_{result.get('number', 'images')}.zip", 
        media_type="application/zip"
    )

# --------------- Playwright المباشر (للتوافق) ---------------
@app.get("/scrape/playwright")
async def scrape_playwright(
    url: str = Query(...),
    cf: Optional[str] = Query(None),
    ua: Optional[str] = Query(None),
    headless: bool = Query(True),
    wait_after: float = Query(1.0)
):
    loop = asyncio.get_event_loop()
    try:
        # تشغيل الوظيفة المتزامنة في Executor
        result = await loop.run_in_executor(
            executor,
            scrape_chapter_with_playwright,
            url, cf, ua, headless, wait_after
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # تشغيل uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
