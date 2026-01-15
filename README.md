# Manga / Manhwa Scraper API

FastAPI backend for scraping manga & manhwa chapters from azoramoon.com

## Features
- Series list scraper
- Series info (profile)
- Chapters list
- Chapter images (static + Playwright for JS)
- Cloudflare compatible
- Ready for mobile apps

## Install

```bash
git clone https://github.com/YOUR_USERNAME/manga-api.git
cd api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install
