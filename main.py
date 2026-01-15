import asyncio
import os
import shutil
import tempfile
import subprocess
import sys
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

app = FastAPI(title="AzoraMoon Scraper API - Stable Version")

# استخدام ThreadPoolExecutor للعمليات التي تستهلك المعالج مثل الضغط
executor = ThreadPoolExecutor(max_workers=5)

def init_playwright():
    """
    تهيئة Playwright بمسار محلي (User-space) لتجنب مشاكل الصلاحيات.
    يقوم هذا الكود بتحديد مسار التثبيت داخل مجلد المشروع وتشغيل التثبيت بدون dependecies للنظام.
    """
    print("🤖 Checking Playwright environment...")
    try:
        # 1. تحديد مسار محلي لتخزين المتصفح داخل مجلد المشروع
        local_browser_path = os.path.join(os.getcwd(), "playwright-browsers")
        
        # ضبط متغير البيئة ليستخدمه Playwright عند التشغيل
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = local_browser_path
        
        print(f"📂 Setting Playwright path to: {local_browser_path}")

        # 2. تشغيل أمر التثبيت (تمت إزالة --with-deps لتجنب طلب sudo)
        # نقوم بتثبيت chromium فقط لتوفير المساحة
        subprocess.run([
            sys.executable, "-m", "playwright", "install", "chromium"
        ], check=True)
        
        print("✅ Playwright installation completed successfully!")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during Playwright installation: {e}")
    except Exception as e:
        print(f"⚠️ Unexpected error in Playwright setup: {e}")

@app.on_event("startup")
async def startup_event():
    # تشغيل التحقق عند بدء تشغيل السيرفر
    init_playwright()

@app.get("/ping")
async def ping():
    return {"status": "ok", "environment": "production"}

# --- قائمة السلاسل ---
@app.get("/series/list")
async def series_list(page_url: Optional[str] = Query(None)):
    url = page_url or "https://azoramoon.com/series"
    result = await fetch_series_list(url)
    return JSONResponse(result)

# --- الملف الشخصي للسلسلة ---
@app.get("/series/profile")
async def series_profile(url: str = Query(...)):
    # تشغيل الوظيفة المتزامنة في executor لتجنب حظر الـ Event Loop
    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(executor, extract_series_profile, url)
    
    # ترتيب الفصول
    if "chapters" in profile:
        profile["chapters"].sort(
            key=lambda c: parse_chapter_number(c.get("title"), c.get("url")) or 0, 
            reverse=True
        )
    return JSONResponse(profile)

# --- محتوى الفصل (الصور) ---
@app.get("/chapter/content")
async def chapter_content(
    url: str = Query(...),
    cf: Optional[str] = Query(None),
    ua: Optional[str] = Query(None),
    playwright_fallback: bool = Query(True)
):
    try:
        result = await extract_chapter_content(url, cf, ua, playwright_fallback)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- تحميل الصور ZIP ---
@app.get("/chapter/download")
async def chapter_download(url: str = Query(...), cf: Optional[str] = Query(None), ua: Optional[str] = Query(None)):
    result = await extract_chapter_content(url, cf, ua)
    images = result.get("images", [])
    
    if not images:
        return JSONResponse({"error": "No images found"}, status_code=404)

    tmpdir = tempfile.mkdtemp()
    
    # تحميل الصور بشكل Async
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        for i, img_url in enumerate(images):
            filename = f"{i:03d}.jpg"
            path = os.path.join(tmpdir, filename)
            tasks.append(client.get(img_url))
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for i, resp in enumerate(responses):
            if isinstance(resp, httpx.Response) and resp.status_code == 200:
                with open(os.path.join(tmpdir, f"{i:03d}.jpg"), "wb") as f:
                    f.write(resp.content)

    # إنشاء ملف ZIP
    def make_zip():
        zip_file = tempfile.mktemp(suffix=".zip")
        shutil.make_archive(zip_file.replace(".zip", ""), 'zip', tmpdir)
        return zip_file if zip_file.endswith(".zip") else zip_file + ".zip"

    zip_path = await asyncio.get_event_loop().run_in_executor(executor, make_zip)
    return FileResponse(zip_path, filename="chapter.zip")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
