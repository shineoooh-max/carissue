import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from google import genai

# 1. 최신 공식 Interactions API 설정
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is missing.")

client = genai.Client(api_key=API_KEY)

SITE_URL = "https://carissue.koo1000.com"
POSTS_DIR = "posts"
INDEX_PATH = "index.html"
SITEMAP_PATH = "sitemap.xml"
HISTORY_FILE = "published_links.txt"
ADSENSE_ID = "ca-pub-3677274092490514"

# 2. 검증된 4대 공식 피드 배분 (국내 2 + 글로벌 3 = 총 5건)
FEEDS = [
    {
        "name": "모터그래프",
        "category": "국내",
        "url": "https://www.motorgraph.com/rss/allArticle.xml",
        "target_count": 1
    },
    {
        "name": "오토헤럴드",
        "category": "국내",
        "url": "http://www.autoherald.co.kr/rss/allArticle.xml",
        "target_count": 1
    },
    {
        "name": "Motor1",
        "category": "글로벌",
        "url": "https://www.motor1.com/rss/news/all/",
        "target_count": 2
    },
    {
        "name": "Carscoops",
        "category": "글로벌",
        "url": "https://www.carscoops.com/feed/",
        "target_count": 1
    }
]

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link.strip() + "\n")

def fetch_feed_items(feed_conf, history_set):
    items = []
    target = feed_conf["target_count"]
    print(f"\n[{feed_conf['name']}] 피드 수집 시작 ({feed_conf['category']} - 목표: {target}건)")
    
    try:
        req = urllib.request.Request(
            feed_conf["url"],
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        raw_data = urllib.request.urlopen(req, timeout=15).read()
        
        try:
            xml_text = raw_data.decode('utf-8')
        except UnicodeDecodeError:
            xml_text = raw_data.decode('cp949', errors='ignore')
            
        root = ET.fromstring(xml_text)
        entries = root.findall(".//item")
        print(f"-> 발견된 기사 수: {len(entries)}개")

        for entry in entries:
            if len(items) >= target:
                break
                
            link_el = entry.find("link")
            guid_el = entry.find("guid")
            link = ""
            if link_el is not None and link_el.text:
                link = link_el.text.strip()
            elif guid_el is not None and guid_el.text:
                link = guid_el.text.strip()
                
            if not link or link in history_set:
                continue

            title_el = entry.find("title")
            desc_el = entry.find("description")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

            image_url = ""
            enclosure = entry.find("enclosure")
            if enclosure is not None and enclosure.attrib.get("url"):
                image_url = enclosure.attrib.get("url")
            elif desc:
                img_search = re.search(r'src=["\']([^"\']+)["\']', desc)
                if img_search:
                    image_url = img_search.group(1)

            if not image_url or not image_url.startswith("http"):
                image_url = "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80"

            clean_desc = re.sub(r'<[^>]+>', '', desc).strip()

            items.append({
                "category": feed_conf["category"],
                "source": feed_conf["name"],
                "title": title,
                "link": link,
                "desc": clean_desc[:500],
                "image_url": image_url
            })
            history_set.add(link)
            print(f"-> [수집 채택] {title[:30]}...")

    except Exception as e:
        print(f"-> [수집 실패]: {e}")

    return items

def generate_article(item):
    prompt = f"""
당신은 대한민국 1위 자동차 전문 웹진 '카이슈(CARISSUE)'의 수석 자동차 전문 기자입니다.
아래 뉴스 브리핑 정보를 바탕으로 독자들의 관심과 몰입도를 극대화하는 심층 분석 기사를 작성해주세요.

[구분]: {item['category']} 자동차 이슈 ({item['source']})
[주제 헤드라인]: {item['title']}
[핵심 내용]: {item['desc']}

[기사 작성 지침]
1. 제목: 클릭을 부르는 품격 있는 뉴스 헤드라인 (따옴표 적극 활용)
2. 분량: 공백 제외 800자 내외
3. 본문 구성:
   - 도입부: 이 소식이 국내외 자동차 시장에서 뜨거운 화제가 되는 이유
   - 본문: 디자인, 기술 혁신, 성능 스펙 및 파워트레인 분석
   - 맺음말: 경쟁 모델과의 상품성 비교 및 국내 소비자 출시/구매 가이드 전망
4. 문체: 정돈되고 신뢰감 있는 언론사 전문 기사체 (~했습니다, ~기대를 모으고 있습니다)
5. 독창성: 단순 전재가 아닌 에디터의 독창적 시각과 분석 코멘터리 포함

[출력 형식 - 반드시 준수]
TITLE: [기사 제목]
CONTENT: [본문 내용 (각 문단은 빈 줄로 구분)]
"""
    # 공식 문서 규격: Interactions API + gemini-3.8-flash
    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        input=prompt
    )
    txt = interaction.output_text.strip()
    
    title = ""
    content = ""
    if "TITLE:" in txt and "CONTENT:" in txt:
        parts = txt.split("CONTENT:")
        title = parts[0].replace("TITLE:", "").strip()
        content = parts[1].strip()
    else:
        lines = [l for l in txt.split("\n") if l.strip()]
        title = lines[0].replace("#", "").strip()
        content = "\n\n".join(lines[1:]).strip()
        
    return title, content

def build_post_html(post_id, title, content, image_url, date_str, category):
    paragraphs = "".join([f"<p>{p.strip()}</p>" for p in content.split("\n\n") if p.strip()])
    
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - CARISSUE</title>
    <meta name="description" content="{title}">
    <link rel="stylesheet" href="../assets/style.css">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_ID}" crossorigin="anonymous"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background-color: #f8f9fa; color: #212529; line-height: 1.8; }}
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
        <span class="badge">{category} 자동차 이슈</span>
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

def update_site(new_posts):
    if not new_posts:
        return

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

def main():
    print(">>> 1. 4대 공식 피드 수집 시작...")
    history_set = load_history()
    collected = []
    
    for feed in FEEDS:
        items = fetch_feed_items(feed, history_set)
        collected.extend(items)
        
    print(f"\n>>> 수집 완료: 총 {len(collected)}개 기사 확보됨 (국내 {sum(1 for i in collected if i['category']=='국내')} / 글로벌 {sum(1 for i in collected if i['category']=='글로벌')})")
    if not collected:
        print("수집 대상 기사가 없습니다. 종료합니다.")
        return

    os.makedirs(POSTS_DIR, exist_ok=True)
    new_posts = []
    
    for idx, item in enumerate(collected):
        print(f"\n[{idx+1}/{len(collected)}] 기사 생성 중: [{item['source']}] {item['title'][:25]}...")
        try:
            t, c = generate_article(item)
            timestamp = int(time.time()) + idx
            post_id = f"post_{timestamp}_{idx}"
            date_str = time.strftime("%Y-%m-%d %H:%M")
            
            html = build_post_html(post_id, t, c, item['image_url'], date_str, item['category'])
            with open(os.path.join(POSTS_DIR, f"{post_id}.html"), "w", encoding="utf-8") as f:
                f.write(html)
                
            save_history(item['link'])
            new_posts.append({
                "id": post_id,
                "title": t,
                "image_url": item['image_url'],
                "date_str": date_str,
                "category": item['category']
            })
            print(f"-> 생성 완료: {t}")
            time.sleep(3)
        except Exception as e:
            print(f"-> [작성 실패]: {e}")

    print("\n>>> 2. index.html 및 sitemap.xml 갱신...")
    update_site(new_posts)
    print(f">>> 성공: 총 {len(new_posts)}건 신규 기사 발행 완료!")

if __name__ == "__main__":
    main()
