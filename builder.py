import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import google.generativeai as genai

# 1. 환경 변수 및 설정
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is missing.")

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

SITE_URL = "https://carissue.koo1000.com"
POSTS_DIR = "posts"
INDEX_PATH = "index.html"
SITEMAP_PATH = "sitemap.xml"

# 애드센스 클라이언트 ID
ADSENSE_ID = "ca-pub-3677274092490514"

# 2. 해외 최신 자동차 뉴스 RSS 피드 수집 (Motor1 등)
RSS_FEED_URL = "https://www.motor1.com/rss/news/all/"

def get_latest_news():
    req = urllib.request.Request(RSS_FEED_URL, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req, timeout=10).read()
    root = ET.fromstring(html)
    
    for item in root.findall('.//item'):
        title = item.find('title').text
        link = item.find('link').text
        description = item.find('description').text if item.find('description') is not None else ""
        
        # 이미지 태그 추출 (enclosure 또는 description 내부 img)
        image_url = ""
        enclosure = item.find('enclosure')
        if enclosure is not None and 'image' in enclosure.attrib.get('type', ''):
            image_url = enclosure.attrib.get('url', '')
        if not image_url and description:
            img_match = re.search(r'<img[^>]+src="([^">]+)"', description)
            if img_match:
                image_url = img_match.group(1)
                
        # 기본 대체 이미지
        if not image_url:
            image_url = "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80"
            
        clean_desc = re.sub(r'<[^>]+>', '', description).strip()
        return title, link, clean_desc, image_url
    return None, None, None, None

def generate_article(title, desc):
    prompt = f"""
당신은 대한민국 1위 프리미엄 자동차 전문 웹진 '카이슈(CARISSUE)'의 전문 에디터입니다.
아래 해외 자동차 뉴스 원문을 바탕으로 전문적이고 몰입감 있는 한국어 기사를 작성해주세요.

[원문 정보]
제목: {title}
요약: {desc}

[작성 조건]
1. 제목: 클릭을 유도하되 품격 있는 국문 헤드라인 (따옴표 활용, 예: "압도적 성능"... 800마력 신형 전기 슈퍼카 공개)
2. 본문 분량: 공백 제외 700자~1,000자 내외
3. 구성:
   - 도입부: 핵심 이슈 및 글로벌 자동차 업계의 주목 포인트
   - 본문: 파워트레인 스펙, 익스테리어/인테리어 디자인 및 혁신 기술 분석
   - 맺음말: 시장 경쟁 모델과의 비교 및 국내 출시 전망/시사점
4. 문체: 정중하고 신뢰감 있는 신문사 전문 기사체 (~했습니다, ~전망됩니다)
5. 출력 형식:
TITLE: [생성된 제목]
CONTENT: [본문 내용 (문단별로 줄바꿈 구분)]
"""
    response = model.generate_content(prompt)
    text = response.text.strip()
    
    article_title = ""
    article_content = ""
    
    if "TITLE:" in text and "CONTENT:" in text:
        parts = text.split("CONTENT:")
        article_title = parts[0].replace("TITLE:", "").strip()
        article_content = parts[1].strip()
    else:
        lines = text.split("\n")
        article_title = lines[0].replace("#", "").strip()
        article_content = "\n".join(lines[1:]).strip()
        
    return article_title, article_content

def build_post_html(post_id, title, content, image_url, date_str):
    paragraphs = "".join([f"<p>{p.strip()}</p>" for p in content.split("\n") if p.strip()])
    
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - CARISSUE</title>
    <meta name="description" content="{title}">
    <link rel="stylesheet" href="../assets/style.css">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_ID}" crossorigin="anonymous"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 0; background-color: #f8f9fa; color: #212529; line-height: 1.8; }}
        header {{ background: #fff; border-bottom: 1px solid #eaeaea; text-align: center; padding: 15px 0; }}
        header img {{ height: 38px; }}
        .article-container {{ max-width: 760px; margin: 40px auto; background: #fff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); }}
        h1 {{ font-size: 26px; line-height: 1.4; margin-bottom: 15px; color: #111; word-break: keep-all; }}
        .meta {{ font-size: 13px; color: #888; margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
        .featured-img {{ width: 100%; border-radius: 8px; margin-bottom: 30px; object-fit: cover; max-height: 450px; }}
        .article-body p {{ font-size: 16px; margin-bottom: 20px; word-break: keep-all; }}
        footer {{ text-align: center; padding: 40px; font-size: 13px; color: #888; border-top: 1px solid #eee; margin-top: 60px; }}
    </style>
</head>
<body>
    <header>
        <a href="../"><img src="../assets/logo.png" alt="CARISSUE"></a>
    </header>

    <div class="article-container">
        <h1>{title}</h1>
        <div class="meta">발행일: {date_str} | 카이슈 편집국</div>
        
        <img src="{image_url}" alt="{title}" class="featured-img">
        
        <div class="article-body">
            {paragraphs}
        </div>
    </div>

    <footer>
        &copy; CARISSUE. All rights reserved.
    </footer>
</body>
</html>"""
    return html

def update_index_and_sitemap(post_id, title, image_url, date_str):
    # 1. index.html 읽기
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
        
    # 기존 기사 목록 그리드 찾기
    grid = soup.find('div', class_=re.compile(r'grid', re.I))
    if not grid:
        # grid 클래스를 못 찾을 경우 기사 카드 부모 태그 탐색
        sample_card = soup.find('a', href=re.compile(r'posts/'))
        if sample_card:
            grid = sample_card.parent

    if grid:
        # 새 기사 카드 태그 생성
        new_card_html = f"""
        <a href="posts/{post_id}.html" class="post-card" style="text-decoration: none; color: inherit;">
            <div style="overflow: hidden; border-radius: 8px; margin-bottom: 12px; height: 180px; background: #eee;">
                <img src="{image_url}" alt="{title}" style="width: 100%; height: 100%; object-fit: cover;">
            </div>
            <span style="display: inline-block; font-size: 11px; font-weight: 700; color: #0066cc; margin-bottom: 6px;">CARISSUE NOW</span>
            <h3 style="font-size: 15px; font-weight: 700; line-height: 1.4; margin: 0 0 8px 0; color: #111;">{title}</h3>
            <span style="font-size: 11px; color: #999;">{date_str}</span>
        </a>
        """
        new_card_soup = BeautifulSoup(new_card_html, 'html.parser')
        grid.insert(0, new_card_soup)
        
        with open(INDEX_PATH, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
    # 2. sitemap.xml 업데이트
    post_url = f"{SITE_URL}/posts/{post_id}.html"
    sitemap_entry = f"  <url>\n    <loc>{post_url}</loc>\n    <lastmod>{date_str[:10]}</lastmod>\n    <priority>0.8</priority>\n  </url>\n</urlset>"
    
    if os.path.exists(SITEMAP_PATH):
        with open(SITEMAP_PATH, 'r', encoding='utf-8') as f:
            sitemap_content = f.read()
        if "</urlset>" in sitemap_content:
            sitemap_content = sitemap_content.replace("</urlset>", sitemap_entry)
            with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
                f.write(sitemap_content)
    else:
        new_sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}/</loc>
    <priority>1.0</priority>
  </url>
{sitemap_entry}"""
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(new_sitemap)

def main():
    print("1. 최신 뉴스 RSS 수집 시작...")
    orig_title, orig_link, orig_desc, image_url = get_latest_news()
    if not orig_title:
        print("수집할 뉴스를 찾지 못했습니다.")
        return
        
    print(f"2. 수집된 뉴스: {orig_title}")
    
    # 중복 체크 방지용 ID 생성
    timestamp = int(time.time())
    post_id = f"post_{timestamp}"
    date_str = time.strftime("%Y-%m-%d %H:%M")
    
    print("3. Gemini 1.5 Flash 기사 작성 요청...")
    title, content = generate_article(orig_title, orig_desc)
    print(f"   작성 완료 제목: {title}")
    
    print("4. posts/ 기사 HTML 파일 생성...")
    os.makedirs(POSTS_DIR, exist_ok=True)
    post_html = build_post_html(post_id, title, content, image_url, date_str)
    
    with open(os.path.join(POSTS_DIR, f"{post_id}.html"), 'w', encoding='utf-8') as f:
        f.write(post_html)
        
    print("5. index.html 최상단 카드 삽입 및 sitemap 갱신...")
    update_index_and_sitemap(post_id, title, image_url, date_str)
    print("성공적으로 모든 배포 데이터가 갱신되었습니다.")

if __name__ == "__main__":
    main()
