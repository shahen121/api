# chapter_extractor.py
import httpx
import json
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": "https://azoramoon.com/",
}


def fetch_html(url: str):
    try:
        with httpx.Client(headers=HEADERS, timeout=20) as client:
            r = client.get(url)
            if r.status_code != 200:
                print(f"[ERROR] {r.status_code} - {url}")
                return None
            r.encoding = "utf-8"
            return r.text
    except Exception as e:
        print("REQ ERROR:", e)
        return None


# ----------- طريقة 1: صور WP-manga -----------
def extract_wp_images(html: str):
    soup = BeautifulSoup(html, "html.parser")
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        src = src.strip()
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        if "WP-manga/data" in src:
            imgs.append(src)
    return list(dict.fromkeys(imgs))


# ----------- طريقة 2: استخراج من JSON داخل __NEXT_DATA__ -----------
def extract_next_data_images(html: str):
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return []

    try:
        data = json.loads(script.string)
    except Exception:
        return []

    found = []

    def search(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("images", "pages") and isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and item.startswith("http"):
                            found.append(item)
                search(v)
        elif isinstance(obj, list):
            for x in obj:
                search(x)

    search(data)

    # فلترة الصور الحقيقية للفصل
    cleaned = []
    for src in found:
        low = src.lower()
        if "chapter" in low and low.endswith((".jpg", ".png", ".jpeg", ".webp")):
            cleaned.append(src)

    return list(dict.fromkeys(cleaned))


# ----------- البحث عبر الطريقتين -----------
def extract_images(url: str):
    html = fetch_html(url)
    if not html:
        return {"url": url, "images": [], "count": 0}

    images = extract_wp_images(html)

    if images:
        return {"url": url, "images": images, "count": len(images)}

    # fallback
    images2 = extract_next_data_images(html)
    return {"url": url, "images": images2, "count": len(images2)}


# ----------- تشغيل على فصول متعددة -----------
if __name__ == "__main__":
    for ch in range(291, 296):
        url = f"https://azoramoon.com/series/nano-machine-s/chapter-{ch}"
        print(f"\n📌 {url}")

        result = extract_images(url)
        print(f"✔ الصور المستخرجة: {result['count']}")
        for i, src in enumerate(result["images"], 1):
            print(f"  {i:02d} {src}")
