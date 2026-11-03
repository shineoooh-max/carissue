import os
import re
import time
import json
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from google import genai

# ==========================================
# 1. Gemini Interactions API 설정
# ==========================================
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is missing.")

client = genai.Client(api_key=API_KEY)

SITE_URL = "https://carissue.koo1000.com"
POSTS_DIR = "posts"
INDEX_PATH = "index.html"
SITEMAP_PATH = "sitemap.xml"
HISTORY_FILE = "published_links.txt"

# ==========================================
# 2. 확정된 애드센스 계정 및 고유 슬롯 ID (불변)
# ==========================================
ADSENSE_CLIENT = "ca-pub-4793184080983542"
AD_SLOT_IN_ARTICLE = "4181249863"  # 본문 글 사이 중간광고 (인아티클)
AD_SLOT_SIDEBAR = "5924062639"     # 우측 고정 사이드바 광고
AD_SLOT_BOTTOM = "9203364457"      # 본문 최하단 반응형 디스플레이 광고

# ==========================================
# 3. 4대 공식 피드 배분 (5건)
# ==========================================
FEEDS = [
    {"name": "모터그래프", "category": "국내", "url": "https://www.motorgraph.com/rss/allArticle.xml", "target_count": 1},
    {"name": "오토헤럴드", "category": "국내", "url": "http://www.autoherald.co.kr/rss/allArticle.xml", "target_count": 1},
    {"name": "Motor1", "category": "글로벌", "url": "https://www.motor1.com/rss/news/all/", "target_count": 2},
    {"name": "Carscoops", "category": "글로벌", "url": "https://www.carscoops.com/feed/", "target_count": 1}
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
    print(f"\n[{feed_conf['name']}] 피드 수집 ({feed_conf['category']} - 목표: {target}건)")
    
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

            # ----------------------------------------------------
            # [이미지 다중 추출: 1장 ~ 최대 5장]
            # ----------------------------------------------------
            images = []
            enclosure = entry.find("enclosure")
            if enclosure is not None and enclosure.attrib.get("url"):
                images.append(enclosure.attrib.get("url"))

            if desc:
                found_imgs = re.findall(r'src=["\']([^"\']+)["\']', desc)
                for img_src in found_imgs:
                    if img_src.startswith("http") and not any(ext in img_src.lower() for ext in ['logo', 'icon', 'advert', 'tracker']):
                        if img_src not in images:
                            images.append(img_src)
            
            # 원문 페이지 크롤링으로 고해상도 차량 이미지 추가 수집 (최대 5장 채우기)
            if len(images) < 3:
                try:
                    sub_req = urllib.request.Request(link, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                    sub_html = urllib.request.urlopen(sub_req, timeout=5).read().decode('utf-8', errors='ignore')
                    sub_soup = BeautifulSoup(sub_html, 'html.parser')
                    for page_img in sub_soup.find_all('img'):
                        src = page_img.get('src') or page_img.get('data-src')
                        if src and src.startswith('http') and not any(bad in src.lower() for bad in ['logo', 'icon', 'banner', 'avatar', 'ad']):
                            if src not in images:
                                images.append(src)
                        if len(images) >= 5:
                            break
                except Exception:
                    pass

            images = images[:5]
            if not images:
                images = ["https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80"]

            clean_desc = re.sub(r'<[^>]+>', '', desc).strip()

            items.append({
                "category": feed_conf["category"],
                "source": feed_conf["name"],
                "title": title,
                "link": link,
                "desc": clean_desc[:500],
                "images": images,
                "image_url": images[0] # 대표 썸네일
            })
            history_set.add(link)
            print(f"-> [채택] {title[:30]}... (이미지 {len(images)}장 확보)")
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
4. 문체: 정돈되고 신뢰감 있는 언론사 전문 기사체 (~했습니다, ~전망됩니다)
5. 독창성: 단순 전재가 아닌 에디터의 독창적 시각과 분석 코멘터리 포함

[출력 형식 - 반드시 준수]
TITLE: [기사 제목]
CONTENT: [본문 내용 (각 문단은 빈 줄로 구분)]
"""
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

# ==========================================
# 4. 서브 본문 HTML 렌더링 (다중 이미지 분산 배치 + 공유 모달 탑재)
# ==========================================
def build_post_html(post_id, title, content, images, date_str, category):
    paras = [p.strip() for p in content.split("\n\n") if p.strip()]
    main_image = images[0] if images else "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80"
    extra_images = images[1:]  # 본문 사이에 끼워 넣을 추가 사진들

    # 인아티클 중간 광고
    in_article_ad = f"""
    <div class="ad-in-article">
        <ins class="adsbygoogle"
             style="display:block; text-align:center;"
             data-ad-layout="in-article"
             data-ad-format="fluid"
             data-ad-client="{ADSENSE_CLIENT}"
             data-ad-slot="{AD_SLOT_IN_ARTICLE}"></ins>
        <script>
             (adsbygoogle = window.adsbygoogle || []).push({{}});
        </script>
    </div>
    """

    p_tags = []
    img_idx = 0
    total_paras = len(paras)

    for i, p in enumerate(paras):
        p_tags.append(f"<p>{p}</p>")
        
        # 1번째 문단 직후: 인아티클 광고 배치
        if i == 0:
            p_tags.append(in_article_ad)
        
        # 이후 문단 사이마다 추가 사진 순차 배치 (최대 5장 분산)
        elif img_idx < len(extra_images):
            p_tags.append(f'<div class="article-sub-img"><img src="{extra_images[img_idx]}" alt="{title} 상세 이미지 {img_idx+1}"></div>')
            img_idx += 1

    # 만약 문단이 짧아 남은 이미지가 있다면 본문 끝에 추가
    while img_idx < len(extra_images):
        p_tags.append(f'<div class="article-sub-img"><img src="{extra_images[img_idx]}" alt="{title} 상세 이미지 {img_idx+1}"></div>')
        img_idx += 1

    article_body_html = "".join(p_tags)

    schema_data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "image": images,
        "datePublished": f"{date_str[:10]}T{date_str[11:]}:00+09:00",
        "dateModified": f"{date_str[:10]}T{date_str[11:]}:00+09:00",
        "author": [{"@type": "Organization", "name": "CARISSUE", "url": SITE_URL}]
    }
    schema_json = json.dumps(schema_data, ensure_ascii=False)
    current_post_url = f"{SITE_URL}/posts/{post_id}.html"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - CARISSUE</title>
    <meta name="description" content="{paras[0][:120] if paras else title}">
    
    <!-- 파비콘: 도메인 루트 절대경로 -->
    <link rel="icon" href="/assets/favicon.ico" type="image/x-icon">
    
    <!-- Google AdSense -->
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>
    
    <!-- SEO Schema -->
    <script type="application/ld+json">
    {schema_json}
    </script>
    
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #fff; color: #111; line-height: 1.8; }}
        a {{ text-decoration: none; color: inherit; }}

        /* 상단 공통 헤더 */
        header {{ background: #fff; border-bottom: 3px solid #111; position: sticky; top: 0; z-index: 1000; }}
        .header-inner {{ max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; }}
        .logo img {{ height: 32px; display: block; }}
        .nav-right {{ display: flex; align-items: center; gap: 24px; }}
        .nav-menu {{ font-size: 15px; font-weight: 800; color: #111; letter-spacing: 0.5px; }}
        .sns-icons {{ display: flex; align-items: center; gap: 14px; }}
        .sns-icons svg {{ width: 17px; height: 17px; fill: #111; }}

        /* 2단 본문 그리드 (PC 7:3) */
        .main-wrapper {{ max-width: 1200px; margin: 30px auto; padding: 0 20px; display: grid; grid-template-columns: 1fr 320px; gap: 40px; }}
        .content-area {{ min-width: 0; }}
        .badge {{ display: inline-block; background: #d32f2f; color: #fff; font-size: 11px; font-weight: 800; padding: 4px 8px; border-radius: 2px; text-transform: uppercase; margin-bottom: 12px; }}
        h1 {{ font-size: 32px; line-height: 1.35; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 15px; word-break: keep-all; }}
        
        /* 메타 정보 + 공유 버튼 가로 정렬 바 */
        .meta-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #eee; }}
        .meta-info {{ font-size: 13px; color: #777; }}
        .share-btn {{ display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; background: #f8f9fa; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; font-weight: 700; color: #333; cursor: pointer; transition: all 0.2s; }}
        .share-btn:hover {{ background: #eee; border-color: #bbb; }}
        .share-btn svg {{ width: 14px; height: 14px; fill: #444; }}

        .featured-img {{ width: 100%; border-radius: 4px; margin-bottom: 25px; object-fit: cover; max-height: 520px; }}
        .article-sub-img {{ margin: 30px 0; }}
        .article-sub-img img {{ width: 100%; border-radius: 4px; object-fit: cover; max-height: 520px; display: block; }}
        
        .article-body p {{ font-size: 17px; line-height: 1.85; margin-bottom: 22px; color: #222; word-break: keep-all; }}
        
        .ad-in-article {{ margin: 35px 0; text-align: center; border-top: 1px solid #f0f0f0; border-bottom: 1px solid #f0f0f0; padding: 20px 0; }}
        .ad-bottom {{ margin: 40px 0; text-align: center; }}

        /* 우측 고정 사이드바 */
        .sidebar {{ min-width: 0; }}
        .sidebar-sticky {{ position: -webkit-sticky; position: sticky; top: 85px; }}
        .sidebar-title {{ font-size: 12px; font-weight: 800; color: #999; text-transform: uppercase; margin-bottom: 10px; border-bottom: 2px solid #111; padding-bottom: 6px; }}

        footer {{ border-top: 1px solid #eee; background: #fafafa; padding: 40px 20px; text-align: center; font-size: 13px; color: #888; margin-top: 60px; }}

        /* 공유 모달 팝업 스타일 (캡처화면 디자인 완벽 구현) */
        .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 2000; justify-content: center; align-items: center; }}
        .modal-box {{ background: #fff; width: 90%; max-width: 400px; border-radius: 8px; padding: 24px; position: relative; box-shadow: 0 10px 30px rgba(0,0,0,0.2); animation: fadeIn 0.2s ease-out; }}
        .modal-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        .modal-title {{ font-size: 17px; font-weight: 800; color: #111; }}
        .modal-close {{ font-size: 20px; color: #888; cursor: pointer; border: none; background: none; }}
        .share-icons {{ display: flex; justify-content: space-around; margin-bottom: 24px; }}
        .share-icon-btn {{ display: flex; flex-direction: column; align-items: center; gap: 6px; cursor: pointer; font-size: 11px; color: #555; border: none; background: none; }}
        .share-icon-btn div {{ width: 44px; height: 44px; border-radius: 50%; display: flex; justify-content: center; align-items: center; color: #fff; font-weight: 900; }}
        .url-box {{ display: flex; border: 1px solid #ddd; border-radius: 4px; overflow: hidden; background: #f8f9fa; }}
        .url-input {{ flex: 1; border: none; background: transparent; padding: 10px 12px; font-size: 12px; color: #666; outline: none; }}
        .copy-btn {{ background: #333; color: #fff; border: none; padding: 0 16px; font-size: 12px; font-weight: 700; cursor: pointer; }}
        .copy-btn:hover {{ background: #111; }}
        .toast-msg {{ display: none; position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.8); color: #fff; padding: 10px 20px; border-radius: 20px; font-size: 13px; z-index: 3000; }}

        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(-10px); }} to {{ opacity: 1; transform: translateY(0); }} }}

        @media (max-width: 768px) {{
            .main-wrapper {{ grid-template-columns: 1fr; gap: 0; margin: 15px auto; padding: 0 16px; }}
            h1 {{ font-size: 24px; line-height: 1.35; }}
            .article-body p {{ font-size: 16px; line-height: 1.75; margin-bottom: 18px; }}
            .sidebar {{ display: none; }}
            .sns-icons {{ display: none; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-inner">
            <a href="/" class="logo"><img src="/assets/logo.png" alt="CARISSUE"></a>
            <div class="nav-right">
                <a href="/" class="nav-menu">NEWS</a>
                <div class="sns-icons">
                    <a href="#" aria-label="Facebook"><svg viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
                    <a href="#" aria-label="YouTube"><svg viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg></a>
                    <a href="#" aria-label="X"><svg viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
                    <a href="#" aria-label="Instagram"><svg viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg></a>
                </div>
            </div>
        </div>
    </header>

    <div class="main-wrapper">
        <article class="content-area">
            <span class="badge">{category} 이슈</span>
            <h1>{title}</h1>
            
            <!-- 메타 정보 + 우측 공유 버튼 (뉴오토포스트 스타일) -->
            <div class="meta-bar">
                <div class="meta-info">발행일: {date_str} | CARISSUE 편집국</div>
                <button type="button" class="share-btn" onclick="openShareModal()">
                    <svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z"/></svg>
                    공유
                </button>
            </div>
            
            <!-- 대표 썸네일 (1번째 이미지) -->
            <img src="{main_image}" alt="{title}" class="featured-img">
            
            <!-- 본문 문단 및 추가 이미지 (최대 5장) 순차 분산 배치 -->
            <div class="article-body">
                {article_body_html}
            </div>

            <!-- 본문 최하단 반응형 광고 -->
            <div class="ad-bottom">
                <ins class="adsbygoogle"
                     style="display:block"
                     data-ad-client="{ADSENSE_CLIENT}"
                     data-ad-slot="{AD_SLOT_BOTTOM}"
                     data-ad-format="auto"
                     data-full-width-responsive="true"></ins>
                <script>
                     (adsbygoogle = window.adsbygoogle || []).push({{}});
                </script>
            </div>
        </article>

        <!-- 우측 고정 사이드바 광고 -->
        <aside class="sidebar">
            <div class="sidebar-sticky">
                <div class="sidebar-title">ADVERTISEMENT</div>
                <ins class="adsbygoogle"
                     style="display:inline-block;width:300px;height:600px"
                     data-ad-client="{ADSENSE_CLIENT}"
                     data-ad-slot="{AD_SLOT_SIDEBAR}"></ins>
                <script>
                     (adsbygoogle = window.adsbygoogle || []).push({{}});
                </script>
            </div>
        </aside>
    </div>

    <!-- 공유하기 모달 팝업 레이어 (캡처 디자인 구현) -->
    <div id="shareModal" class="modal-overlay" onclick="closeShareModal(event)">
        <div class="modal-box" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="modal-title">공유하기</div>
                <button type="button" class="modal-close" onclick="closeShareModal()">&times;</button>
            </div>
            <div class="share-icons">
                <button type="button" class="share-icon-btn" onclick="shareX()">
                    <div style="background:#111;">X</div>
                    <span>X(트위터)</span>
                </button>
                <button type="button" class="share-icon-btn" onclick="shareFB()">
                    <div style="background:#1877F2;">f</div>
                    <span>페이스북</span>
                </button>
                <button type="button" class="share-icon-btn" onclick="shareKakao()">
                    <div style="background:#FEE500; color:#111;">talk</div>
                    <span>카카오톡</span>
                </button>
            </div>
            <div class="url-box">
                <input type="text" id="shareUrlInput" class="url-input" value="{current_post_url}" readonly>
                <button type="button" class="copy-btn" onclick="copyCurrentUrl()">복사</button>
            </div>
        </div>
    </div>

    <div id="toastMsg" class="toast-msg">기사 주소가 클립보드에 복사되었습니다.</div>

    <footer>
        &copy; CARISSUE. All rights reserved.
    </footer>

    <script>
        const postTitle = "{title}";
        const postUrl = "{current_post_url}";

        function openShareModal() {{
            if (navigator.share && /Android|iPhone|iPad/i.test(navigator.userAgent)) {{
                navigator.share({{ title: postTitle, url: postUrl }}).catch(() => {{}});
            }} else {{
                document.getElementById('shareModal').style.display = 'flex';
            }}
        }}

        function closeShareModal() {{
            document.getElementById('shareModal').style.display = 'none';
        }}

        function copyCurrentUrl() {{
            const input = document.getElementById('shareUrlInput');
            input.select();
            navigator.clipboard.writeText(postUrl).then(() => {{
                const toast = document.getElementById('toastMsg');
                toast.style.display = 'block';
                setTimeout(() => {{ toast.style.display = 'none'; }}, 2500);
            }});
        }}

        function shareX() {{
            window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(postTitle) + '&url=' + encodeURIComponent(postUrl), '_blank');
        }}

        function shareFB() {{
            window.open('https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(postUrl), '_blank');
        }}

        function shareKakao() {{
            window.open('https://story.kakao.com/share?url=' + encodeURIComponent(postUrl), '_blank');
        }}
    </script>
</body>
</html>"""

# ==========================================
# 5. 기존 posts 폴더의 모든 글 전체 자동 복구 및 인덱스 재생성
# ==========================================
def rebuild_entire_site():
    print(">>> [전체 복구] posts 폴더의 모든 과거 기사를 스캔하여 메인 페이지를 재구성합니다...")
    posts = []
    
    if os.path.exists(POSTS_DIR):
        for fname in os.listdir(POSTS_DIR):
            if not fname.endswith(".html"):
                continue
            fpath = os.path.join(POSTS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    soup = BeautifulSoup(f.read(), "html.parser")
                
                h1 = soup.find("h1")
                title = h1.text.strip() if h1 else fname.replace(".html", "")
                
                img = soup.find("img", class_="featured-img")
                img_url = img["src"] if img and img.get("src") else "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80"
                
                badge = soup.find("span", class_="badge")
                cat = badge.text.replace("이슈", "").strip() if badge else "이슈"
                
                meta = soup.find("div", class_="meta-info") or soup.find("div", class_="meta")
                date_str = ""
                if meta:
                    m = re.search(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}', meta.text)
                    if m:
                        date_str = m.group(0)
                if not date_str:
                    date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fpath)))
                    
                posts.append({
                    "id": fname.replace(".html", ""),
                    "title": title,
                    "image_url": img_url,
                    "category": cat,
                    "date_str": date_str
                })
            except Exception as e:
                print(f"-> 파일 파싱 실패 ({fname}): {e}")

    posts.sort(key=lambda x: (x["date_str"], x["id"]), reverse=True)
    print(f"-> 총 {len(posts)}개의 과거 기사가 정상 확인되었습니다.")

    cards_html = ""
    for post in posts:
        cards_html += f"""
        <article class="post-card">
            <a href="posts/{post['id']}.html" class="thumb-wrap">
                <img src="{post['image_url']}" alt="{post['title']}">
            </a>
            <span class="card-tag">CARISSUE {post['category']}</span>
            <a href="posts/{post['id']}.html">
                <h3>{post['title']}</h3>
            </a>
            <span class="date">{post['date_str']}</span>
            <a href="posts/{post['id']}.html" class="read-more">READ MORE &rarr;</a>
        </article>
        """

    full_index = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CARISSUE - 글로벌 &amp; 국내 자동차 매거진</title>
    <meta name="description" content="글로벌 및 국내 최신 자동차 뉴스, 신차 스펙, 시승기 및 심층 분석 매거진">
    <link rel="icon" href="/assets/favicon.ico" type="image/x-icon">
    
    <!-- Google AdSense -->
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>

    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #fff; color: #111; line-height: 1.6; }}
        a {{ text-decoration: none; color: inherit; }}

        header {{ background: #fff; border-bottom: 3px solid #111; position: sticky; top: 0; z-index: 1000; }}
        .header-inner {{ max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; }}
        .logo img {{ height: 32px; display: block; }}
        .nav-right {{ display: flex; align-items: center; gap: 24px; }}
        .nav-menu {{ font-size: 15px; font-weight: 800; color: #111; letter-spacing: 0.5px; }}
        
        .sns-icons {{ display: flex; align-items: center; gap: 14px; }}
        .sns-icons svg {{ width: 17px; height: 17px; fill: #111; }}

        .container {{ max-width: 1200px; margin: 30px auto; padding: 0 20px; }}
        .section-header {{ font-size: 20px; font-weight: 900; letter-spacing: 0.5px; margin: 40px 0 20px 0; border-bottom: 2px solid #111; padding-bottom: 8px; text-transform: uppercase; }}
        .section-header span {{ color: #d32f2f; }}

        .article-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 30px 24px; }}
        .post-card {{ display: flex; flex-direction: column; background: #fff; }}
        .post-card:hover h3 {{ color: #d32f2f; }}
        .post-card .thumb-wrap {{ width: 100%; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 4px; margin-bottom: 12px; background: #f0f0f0; }}
        .post-card img {{ width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s; }}
        .post-card:hover img {{ transform: scale(1.03); }}
        .card-tag {{ font-size: 11px; font-weight: 800; color: #d32f2f; text-transform: uppercase; margin-bottom: 6px; }}
        .post-card h3 {{ font-size: 17px; font-weight: 800; line-height: 1.4; margin-bottom: 8px; color: #111; word-break: keep-all; }}
        .post-card .date {{ font-size: 12px; color: #888; }}
        .read-more {{ font-size: 11px; font-weight: 800; color: #d32f2f; margin-top: 10px; display: inline-block; }}

        footer {{ border-top: 1px solid #eee; background: #fafafa; padding: 40px 20px; text-align: center; font-size: 13px; color: #888; margin-top: 60px; }}

        @media (max-width: 900px) {{
            .article-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        @media (max-width: 600px) {{
            .article-grid {{ grid-template-columns: 1fr; }}
            .sns-icons {{ display: none; }}
            .container {{ padding: 0 16px; margin: 15px auto; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-inner">
            <a href="/" class="logo"><img src="/assets/logo.png" alt="CARISSUE"></a>
            <div class="nav-right">
                <a href="/" class="nav-menu">NEWS</a>
                <div class="sns-icons">
                    <a href="#" aria-label="Facebook"><svg viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
                    <a href="#" aria-label="YouTube"><svg viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg></a>
                    <a href="#" aria-label="X"><svg viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
                    <a href="#" aria-label="Instagram"><svg viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg></a>
                </div>
            </div>
        </div>
    </header>

    <main class="container">
        <div class="section-header">LATEST STORIES <span>●</span></div>
        <div class="article-grid" id="article-grid">
            {cards_html}
        </div>
    </main>

    <footer>
        &copy; CARISSUE. All rights reserved.
    </footer>
</body>
</html>"""

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(full_index)

    sitemap_entries = ""
    for post in posts:
        sitemap_entries += f"  <url>\n    <loc>{SITE_URL}/posts/{post['id']}.html</loc>\n    <lastmod>{post['date_str'][:10]}</lastmod>\n    <priority>0.8</priority>\n  </url>\n"
        
    sitemap_full = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}/</loc>
    <priority>1.0</priority>
  </url>
{sitemap_entries}</urlset>"""

    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(sitemap_full)
    print("-> 메인 페이지 및 sitemap.xml 복구 완료!")

def main():
    print(">>> 1. 4대 공식 피드 수집 시작...")
    history_set = load_history()
    collected = []
    
    for feed in FEEDS:
        items = fetch_feed_items(feed, history_set)
        collected.extend(items)
        
    print(f"\n>>> 수집 완료: 총 {len(collected)}개 기사 확보됨")

    os.makedirs(POSTS_DIR, exist_ok=True)
    
    if collected:
        for idx, item in enumerate(collected):
            print(f"\n[{idx+1}/{len(collected)}] 기사 생성 중: [{item['source']}] {item['title'][:25]}...")
            try:
                t, c = generate_article(item)
                timestamp = int(time.time()) + idx
                post_id = f"post_{timestamp}_{idx}"
                date_str = time.strftime("%Y-%m-%d %H:%M")
                
                # 다중 이미지(item['images']) 전달
                html = build_post_html(post_id, t, c, item['images'], date_str, item['category'])
                with open(os.path.join(POSTS_DIR, f"{post_id}.html"), "w", encoding="utf-8") as f:
                    f.write(html)
                    
                save_history(item['link'])
                time.sleep(3)
            except Exception as e:
                print(f"-> [작성 실패]: {e}")

    # 신규 기사 생성 여부와 관계없이 메인 화면 최신 상태 유지
    rebuild_entire_site()
    print(">>> 모든 작업 완료!")

if __name__ == "__main__":
    main()
