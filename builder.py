import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import google.generativeai as genai

# 1. 환경 설정
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is missing.")

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

SITE_URL = "https://carissue.koo1000.com"
POSTS_DIR = "posts"
INDEX_PATH = "index.html"
SITEMAP_PATH = "sitemap.xml"
HISTORY_FILE = "published_links.txt"

ADSENSE_ID = "ca-pub-3677274092490514"

# 2. 국내 및 해외 자동차 공식 RSS 피드
SOURCES = [
    # 국내 소스 (현대/기아 공식 미디어룸, 국내 자동차 포털 피드)
    {"name": "국내", "url": "https://www.autodaily.co.kr/rss/allArticle.xml"},
    {"name": "국내", "url": "http://www.autoherald.co.kr/rss/allArticle.xml"},
    # 해외 소스 (모터1, 카스쿱스)
    {"name": "글로벌", "url": "https://www.motor1.com/rss/news/all/"},
    {"name": "글로벌", "url": "https://www.carscoops.com/feed/"}
]

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link.strip() + "\n")

def fetch_articles_from_rss(rss_url, category, history_set, max_items=2):
    items_to_process = []
    try:
        req = urllib.request.Request(
            rss_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        html = urllib.request.urlopen(req, timeout=12).read()
        root = ET.fromstring(html)
        
        for item in root.findall('.//item'):
            if len(items_to_process) >= max_items:
                break
            
            link = item.find('link').text if item.find('link') is not None else ""
            if not link or link in history_set:
                continue
                
            title = item.find('title').text if item.find('title') is not None else ""
            desc = item.find('description').text if item.find('description') is not None else ""
            
            # 대표 이미지 추출
            image_url = ""
            enclosure = item.find('enclosure')
            if enclosure is not None and 'image' in enclosure.attrib.get('type', ''):
                image_url = enclosure.attrib.get('url', '')
            if not image_url and desc:
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc)
                if img_match:
                    image_url = img_match.group(1)
            
            # 이미지 없을 경우 기본 자동차 이미지
            if not image_url or not image_url.startswith("http"):
                image_url = "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80"
                
            clean_desc = re.sub(r'<[^>]+>', '', desc).strip()
            
            items_to_process.append({
                "category": category,
                "title": title.strip(),
                "link": link.strip(),
                "desc": clean_desc,
                "image_url": image_url
            })
    except Exception as e:
        print(f"[{rss_url}] 수집 중 예외 발생: {e}")
        
    return items_to_process

def generate_article(item):
    prompt = f"""
당신은 대한민국 대표 자동차 전문 웹진 '카이슈(CARISSUE)'의 수석 자동차 전문 기자입니다.
아래 뉴스 원문을 바탕으로 독자들의 몰입도를 극대화할 수 있는 심층 분석 기사를 작성해주세요.

[기사 분류]: {item['category']} 이슈
[원문 제목]: {item['title']}
[원문 내용]: {item['desc']}

[기사 작성 가이드라인]
1. 제목: 
   - 클릭을 유도하되 품격 있는 신문 헤드라인 형태 (따옴표 활용)
   - 예: "이 가격에 이 성능?"... 800마력 신형 전기 슈퍼카 마침내 공개
2. 본문 분량: 
   - 공백 제외 700자~1,000자 내외의 충실한 분량
3. 구성:
   - 서론: 해당 신차 또는 자동차 업계 이슈의 핵심 포인트와 시장의 관심사
   - 본론: 파워트레인 스펙, 디자인 특징, 혁신 첨단 사양(인포테인먼트/ADAS) 및 플랫폼 분석
   - 결론: 경쟁 모델과의 상품성 비교, 국내 출시 일정/예상 가격 및 소비자 평가 전망
4. 문체:
   - 신뢰감 있고 정돈된 언론사 전문 기사체 (~했습니다, ~기대를 모으고 있습니다)
5. 단순 번역이나 복사가 아닌, 카이슈 에디터 관점의 독창적인 코멘터리를 덧붙일 것

[출력 형식 - 반드시 준수]
TITLE: [생성된 기사 제목]
CONTENT: [본문 내용 (각 문단은 줄바꿈 2번으로 구분)]
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
        lines = [l for l in text.split("\n") if l.strip()]
        article_title = lines[0].replace("#", "").strip()
        article_content = "\n\n".join(lines[1:]).strip()
        
    return article_title, article_content

def build_post_html(post_id, title, content, image_url, date_str, category):
    paragraphs = "".join([f"<p>{p.strip()}</p>" for p in content.split("\n\n") if p.strip()])
    
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
        .badge {{ display: inline-block; background: #0066cc; color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; margin-bottom: 10px; }}
        .meta {{ font-size: 13px; color: #888; margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
        .featured-img {{ width: 100%; border-radius: 8px; margin-bottom: 30px; object-fit: cover; max-height: 480px; }}
        .article-body p {{ font-size: 16px; margin-bottom: 20px; word-break: keep-all; }}
        footer {{ text-align: center; padding: 40px; font-size: 13px; color: #888; border-top: 1px solid #eee; margin-top: 60px; }}
    </style>
</head>
<body>
    <header>
        <a href="../"><img src="../assets/logo.png" alt="CARISSUE"></a>
    </header>

    <div class="article-container">
        <span class="badge">{category} 이슈</span>
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

def update_index_and_sitemap(new_posts):
    if not new_posts:
        return

    # 1. index.html 업데이트
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
        
    grid = soup.find('div', class_=re.compile(r'grid', re.I))
    if not grid:
        sample_card = soup.find('a', href=re.compile(r'posts/'))
        if sample_card:
            grid = sample_card.parent

    if grid:
        for post in reversed(new_posts):
            card_html = f"""
            <a href="posts/{post['id']}.html" class="post-card" style="text-decoration: none; color: inherit;">
                <div style="overflow: hidden; border-radius: 8px; margin-bottom: 12px; height: 180px; background: #eee;">
                    <img src="{post['image_url']}" alt="{post['title']}" style="width: 100%; height: 100%; object-fit: cover;">
                </div>
                <span style="display: inline-block; font-size: 11px; font-weight: 700; color: #0066cc; margin-bottom: 6px;">CARISSUE {post['category']}</span>
                <h3 style="font-size: 15px; font-weight: 700; line-height: 1.4; margin: 0 0 8px 0; color: #111;">{post['title']}</h3>
                <span style="font-size: 11px; color: #999;">{post['date_str']}</span>
            </a>
            """
            card_soup = BeautifulSoup(card_html, 'html.parser')
            grid.insert(0, card_soup)
            
        with open(INDEX_PATH, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
    # 2. sitemap.xml 업데이트
    sitemap_entries = ""
    for post in new_posts:
        sitemap_entries += f"  <url>\n    <loc>{SITE_URL}/posts/{post['id']}.html</loc>\n    <lastmod>{post['date_str'][:10]}</lastmod>\n    <priority>0.8</priority>\n  </url>\n"
        
    if os.path.exists(SITEMAP_PATH):
        with open(SITEMAP_PATH, 'r', encoding='utf-8') as f:
            sitemap_content = f.read()
        if "</urlset>" in sitemap_content:
            sitemap_content = sitemap_content.replace("</urlset>", sitemap_entries + "</urlset>")
            with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
                f.write(sitemap_content)
    else:
        new_sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}/</loc>
    <priority>1.0</priority>
  </url>
{sitemap_entries}</urlset>"""
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(new_sitemap)

def main():
    print(">>> 1. 기사 수집 파이프라인 가동...")
    history_set = load_history()
    
    # 국내 2개, 글로벌 3개 수집 (총 5개)
    collected = []
    
    # 국내 기사 2개 수집
    for src in SOURCES[:2]:
        if len([x for x in collected if x['category'] == '국내']) >= 2:
            break
        items = fetch_articles_from_rss(src['url'], '국내', history_set, max_items=2)
        for it in items:
            if len([x for x in collected if x['category'] == '국내']) < 2:
                collected.append(it)
                history_set.add(it['link'])

    # 글로벌 외신 3개 수집
    for src in SOURCES[2:]:
        if len([x for x in collected if x['category'] == '글로벌']) >= 3:
            break
        items = fetch_articles_from_rss(src['url'], '글로벌', history_set, max_items=3)
        for it in items:
            if len([x for x in collected if x['category'] == '글로벌']) < 3:
                collected.append(it)
                history_set.add(it['link'])
                
    print(f">>> 총 {len(collected)}개 기사 후보 선정 (국내 {len([x for x in collected if x['category']=='국내'])}개, 글로벌 {len([x for x in collected if x['category']=='글로벌'])}개)")
    
    if not collected:
        print("수집할 새로운 기사가 없습니다.")
        return

    os.makedirs(POSTS_DIR, exist_ok=True)
    new_published_posts = []
    
    for idx, item in enumerate(collected):
        print(f"\n[{idx+1}/{len(collected)}] 기사 생성 중: {item['title'][:30]}...")
        try:
            gen_title, gen_content = generate_article(item)
            
            timestamp = int(time.time()) + idx
            post_id = f"post_{timestamp}_{idx}"
            date_str = time.strftime("%Y-%m-%d %H:%M")
            
            # HTML 생성 및 저장
            post_html = build_post_html(post_id, gen_title, gen_content, item['image_url'], date_str, item['category'])
            with open(os.path.join(POSTS_DIR, f"{post_id}.html"), 'w', encoding='utf-8') as f:
                f.write(post_html)
                
            save_history(item['link'])
            
            new_published_posts.append({
                "id": post_id,
                "title": gen_title,
                "image_url": item['image_url'],
                "date_str": date_str,
                "category": item['category']
            })
            
            time.sleep(3) # API 쿼터 및 요청 간격 보호
        except Exception as e:
            print(f"기사 작성 실패 건너뜀: {e}")

    print("\n>>> 2. index.html 및 sitemap.xml 일괄 갱신...")
    update_index_and_sitemap(new_published_posts)
    print(f">>> {len(new_published_posts)}개 신규 기사 발행 완료!")

if __name__ == "__main__":
    main()
