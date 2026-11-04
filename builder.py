import os
import re
import time
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
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

# 한국 표준시(KST, UTC+9) 고정
KST = timezone(timedelta(hours=9))

def get_now_kst_dt():
    return datetime.now(KST)

def get_now_kst():
    return get_now_kst_dt().strftime("%Y-%m-%d %H:%M")

# ==========================================
# 2. 애드센스 계정 및 고유 슬롯 번호 (불변 규격)
# ==========================================
ADSENSE_CLIENT = "ca-pub-4793184080983542"
AD_SLOT_IN_ARTICLE = "4181249863"  # 본문 중간 (인아티클)
AD_SLOT_SIDEBAR = "5924062639"     # 우측 고정 사이드바 (300x600)
AD_SLOT_BOTTOM = "9203364457"      # 본문 최하단 반응형 디스플레이
AD_SLOT_MULTIPLEX = "3913014950"   # 본문 하단 멀티플렉스 (일치하는 콘텐츠)

# ==========================================
# 3. 오전(국내 5) / 오후(해외 5) 피드 배분 정의
# ==========================================
def get_current_feeds():
    now = get_now_kst_dt()
    # KST 기준 12시 이전: 오전 국내 기사 5건 (오토헤럴드)
    if now.hour < 12:
        print(f">>> [피드 분기] 오전 스케줄 적용: 국내 기사 5건 (KST 현재시각: {now.strftime('%H:%M')})")
        return [
            {"name": "오토헤럴드", "category": "국내", "url": "http://www.autoherald.co.kr/rss/allArticle.xml", "target_count": 5}
        ]
    # KST 기준 12시 이후: 오후 글로벌 기사 5건 (Motor1 3건 + Carscoops 2건)
    else:
        print(f">>> [피드 분기] 오후 스케줄 적용: 해외 기사 5건 (KST 현재시각: {now.strftime('%H:%M')})")
        return [
            {"name": "Motor1", "category": "글로벌", "url": "https://www.motor1.com/rss/news/all/", "target_count": 3},
            {"name": "Carscoops", "category": "글로벌", "url": "https://www.carscoops.com/feed/", "target_count": 2}
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
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        )
        raw_data = urllib.request.urlopen(req, timeout=15).read()
        try:
            xml_text = raw_data.decode('utf-8')
        except UnicodeDecodeError:
            xml_text = raw_data.decode('cp949', errors='ignore')
            
        root = ET.fromstring(xml_text)
        entries = root.findall(".//item")
        print(f"-> 수집된 원문 엔트리: {len(entries)}개")

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
            
            # 피드 내부 이미지 추출 보조
            feed_img = ""
            enc = entry.find("enclosure")
            if enc is not None and enc.attrib.get("url"):
                feed_img = enc.attrib["url"]
            elif desc:
                d_soup = BeautifulSoup(desc, "html.parser")
                img_tag = d_soup.find("img")
                if img_tag and img_tag.get("src"):
                    feed_img = img_tag["src"]

            items.append({
                "source": feed_conf["name"],
                "category": feed_conf["category"],
                "title": title,
                "link": link,
                "feed_img": feed_img,
                "feed_desc": desc
            })
    except Exception as e:
        print(f"[{feed_conf['name']}] RSS 수집 오류 발생: {e}")
        
    return items

def extract_article_details(url, feed_img="", feed_desc=""):
    images = []
    text_content = ""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        )
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, "html.parser")

        # 본문 영역 탐색 범위 대폭 확장
        article_elem = (
            soup.find('article') or 
            soup.find('div', class_=re.compile(r'article-body|entry-content|content|post-body|view-content|postContent|m1-article-body|article__body', re.I)) or
            soup.find('div', id=re.compile(r'article-body|content|post-body', re.I)) or
            soup.body
        )
        
        raw_imgs = []
        if feed_img:
            raw_imgs.append(feed_img)

        if article_elem:
            for img in article_elem.find_all('img'):
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if not src and img.get('srcset'):
                    src = img.get('srcset').split(',')[0].split(' ')[0]
                if src and src.startswith('http'):
                    if any(x in src.lower() for x in ['logo', 'icon', 'banner', 'btn', 'avatar', 'ad_', 'advertisement']):
                        continue
                    raw_imgs.append(src)

            # 본문 문단 추출
            paragraphs = [p.get_text().strip() for p in article_elem.find_all(['p', 'h2', 'h3']) if len(p.get_text().strip()) > 20]
            text_content = "\n\n".join(paragraphs)

        # 웹 파싱 실패 시 피드 내 description 텍스트로 보완(fallback)
        if (not text_content or len(text_content) < 100) and feed_desc:
            desc_soup = BeautifulSoup(feed_desc, "html.parser")
            desc_text = desc_soup.get_text().strip()
            if len(desc_text) > 80:
                text_content = desc_text

        # 이미지 중복 제거
        seen = set()
        for i in raw_imgs:
            if i not in seen:
                seen.add(i)
                images.append(i)
                if len(images) >= 5:
                    break
    except Exception as e:
        print(f"기사 상세 파싱 예외 ({url}): {e}")
        if feed_desc:
            desc_soup = BeautifulSoup(feed_desc, "html.parser")
            text_content = desc_soup.get_text().strip()

    return text_content[:4000], images

# ==========================================
# 4. Gemini 프롬프트 및 기사 재작성
# ==========================================
def generate_article_content(source, category, original_title, raw_text):
    prompt = f"""
당신은 국내 최고의 프리미엄 자동차 전문 웹진 '카이슈(CARISSUE)'의 수석 자동차 전문 에디터입니다.
아래 제공된 출처({source}, 분류: {category})의 자동차 뉴스/원문을 바탕으로 독자들의 몰입감을 극대화하는 매력적인 한국어 자동차 매거진 기사를 작성해주세요.

[원문 정보]
원문 제목: {original_title}
원문 내용:
{raw_text}

[작성 및 출력 가이드라인 - 반드시 준수]
1. 제목:
   - 독자의 클릭을 유도하는 전문적이고 세련된 한국어 헤드라인 1개.
   - 첫 줄에 `# 제목` 형식으로 출력하세요.
2. 부제목(서브헤드):
   - 기사의 핵심을 찌르는 임팩트 있는 요약 1줄.
   - `## 부제목` 형식으로 제목 바로 아래에 출력하세요.
3. 본문 구조:
   - 본문은 자연스러운 4~5개 단락으로 깊이 있게 구성하세요.
   - 외신 기사의 경우 단순 직역을 지양하고, 한국 소비자의 시선과 시장 맥락(국내 출시 가능성, 경쟁 모델과의 비교, 가격 정책 등)을 결합해 분석적으로 재해석하세요.
   - 각 단락 시작 전 `### 소제목`을 달아 가독성을 극대화하세요.
   - 마크다운(Markdown) 포맷으로만 정갈하게 출력하세요.
"""
    try:
        interaction = client.interactions.create(
            model="gemini-3.8-flash",
            input=prompt
        )
        return interaction.output_text.strip()
    except Exception as e:
        print(f"Gemini API 호출 에러: {e}")
        return None

# ==========================================
# 5. HTML 빌드 헬퍼 (공유 모달, 푸터, 주석)
# ==========================================
def render_header(active_nav=""):
    return f"""
    <header class="site-header">
        <div class="header-inner">
            <a href="/" class="logo">
                <img src="/assets/logo.png" alt="CARISSUE" />
            </a>
            <nav class="main-nav">
                <a href="/" class="nav-item {'active' if not active_nav else ''}">최신뉴스</a>
                <a href="/category_domestic.html" class="nav-item {'active' if active_nav == '국내' else ''}">국내신차</a>
                <a href="/category_global.html" class="nav-item {'active' if active_nav == '글로벌' else ''}">글로벌이슈</a>
            </nav>
        </div>
    </header>
    """

def render_footer():
    return f"""
    <footer class="site-footer">
        <div class="footer-inner">
            <div class="footer-links">
                <a href="/privacy.html">개인정보처리방침</a> &bull;
                <a href="/terms.html">이용약관</a> &bull;
                <a href="mailto:shineoooh@gmail.com">광고·제휴 문의</a>
            </div>
            <p class="copyright">&copy; 2026 CARISSUE. All rights reserved.</p>
        </div>
    </footer>
    """

def get_base_css():
    return """
    :root {
        --primary: #d32f2f;
        --dark: #121212;
        --text: #222222;
        --text-sub: #666666;
        --border: #e5e5e5;
        --bg-footer: #f8f8fa;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", sans-serif; color: var(--text); background: #ffffff; line-height: 1.6; }
    a { color: inherit; text-decoration: none; }
    img { max-width: 100%; height: auto; display: block; }
    
    .site-header { border-bottom: 1px solid var(--border); background: #fff; position: sticky; top: 0; z-index: 100; }
    .header-inner { max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 12px 20px; }
    .logo img { height: 38px; width: auto; }
    .main-nav { display: flex; gap: 24px; font-weight: 700; font-size: 16px; }
    .nav-item:hover, .nav-item.active { color: var(--primary); }

    .site-footer { background: var(--bg-footer); border-top: 1px solid var(--border); padding: 35px 20px; margin-top: 60px; text-align: center; }
    .footer-inner { max-width: 1200px; margin: 0 auto; }
    .footer-links { font-size: 14px; font-weight: 500; color: #555; margin-bottom: 12px; }
    .footer-links a:hover { color: var(--primary); text-decoration: underline; }
    .copyright { font-size: 13px; color: #888; }

    /* 공유 모달 */
    .share-modal { display: none; position: fixed; z-index: 9999; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; }
    .share-modal-content { background: #fff; width: 90%; max-width: 380px; border-radius: 12px; padding: 24px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.2); }
    .share-title { font-size: 18px; font-weight: 700; margin-bottom: 20px; color: #111; }
    .share-btn-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
    .share-act-btn { border: 1px solid #ddd; background: #fafafa; border-radius: 8px; padding: 12px 0; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
    .share-act-btn:hover { background: #f0f0f0; border-color: #bbb; }
    .share-close-btn { background: #333; color: #fff; border: none; padding: 10px 0; width: 100%; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 14px; }
    """

# ==========================================
# 6. 기사 상세 페이지 생성 및 리빌드
# ==========================================
def build_article_page(item_data, all_posts):
    post_id = item_data["id"]
    title = item_data["title"]
    subtitle = item_data.get("subtitle", "")
    content_html = item_data["content_html"]
    images = item_data.get("images", [])
    featured_img = images[0] if images else "/assets/logo.png"
    date_str = item_data.get("date", get_now_kst())
    category = item_data.get("category", "국내")
    source = item_data.get("source", "CARISSUE")

    # SEO JSON-LD
    schema_ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "description": subtitle or title,
        "image": images,
        "datePublished": item_data.get("iso_date", datetime.now(timezone.utc).isoformat()),
        "author": [{
            "@type": "Organization",
            "name": "CARISSUE",
            "url": SITE_URL
        }],
        "publisher": {
            "@type": "Organization",
            "name": "CARISSUE",
            "logo": {
                "@type": "ImageObject",
                "url": f"{SITE_URL}/assets/logo.png"
            }
        }
    }

    # 추천 기사 (최신 3개)
    related_html = ""
    for r in [p for p in all_posts if p["id"] != post_id][:3]:
        r_img = r.get("images", ["/assets/logo.png"])[0] if r.get("images") else "/assets/logo.png"
        related_html += f"""
        <a href="/posts/{r['id']}.html" class="rel-card">
            <div class="rel-thumb"><img src="{r_img}" alt="{r['title']}" loading="lazy"></div>
            <div class="rel-title">{r['title']}</div>
        </a>
        """

    # 저작권 주석 (폰트 크기 11px)
    copyright_notice = f"""
    <div class="copyright-notice">
        ※ 본 기사는 각 언론사({source} 등)의 공식 보도자료 및 외신 브리핑을 바탕으로 에디터의 분석을 더해 재구성되었으며, 대표 이미지의 저작권은 해당 원문 출처에 있습니다.
    </div>
    """

    page_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - CARISSUE</title>
    <meta name="description" content="{subtitle or title}">
    <link rel="icon" href="/assets/favicon.ico" type="image/x-icon">
    <link rel="canonical" href="{SITE_URL}/posts/{post_id}.html">
    <script type="application/ld+json">
    {json.dumps(schema_ld, ensure_ascii=False, indent=2)}
    </script>
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>
    <style>
        {get_base_css()}
        .post-layout {{ max-width: 1200px; margin: 30px auto; padding: 0 20px; display: grid; grid-template-columns: 1fr 300px; gap: 40px; }}
        @media(max-width: 900px) {{ .post-layout {{ grid-template-columns: 1fr; }} .sidebar-wrap {{ display: none; }} }}
        
        .post-cat {{ color: var(--primary); font-weight: 700; font-size: 14px; text-transform: uppercase; margin-bottom: 8px; }}
        .post-title {{ font-size: 32px; font-weight: 800; line-height: 1.3; margin-bottom: 12px; word-break: keep-all; }}
        .post-sub {{ font-size: 18px; color: var(--text-sub); line-height: 1.5; margin-bottom: 20px; font-weight: 400; }}
        .post-meta {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; font-size: 14px; color: #777; }}
        .share-btn {{ background: #fff; border: 1px solid #ccc; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; cursor: pointer; }}
        .share-btn:hover {{ background: #f5f5f5; border-color: #999; }}

        .featured-img-wrap {{ margin-bottom: 30px; border-radius: 8px; overflow: hidden; }}
        .featured-img-wrap img {{ width: 100%; height: auto; }}

        .post-content {{ font-size: 17px; line-height: 1.85; color: #2a2a2a; margin-bottom: 40px; }}
        .post-content p {{ margin-bottom: 22px; word-break: keep-all; }}
        .post-content h3 {{ font-size: 21px; margin: 34px 0 14px; color: #111; font-weight: 700; }}
        .content-img {{ margin: 30px 0; border-radius: 6px; overflow: hidden; }}
        .content-img img {{ width: 100%; height: auto; }}

        .ad-in-article {{ margin: 35px 0; text-align: center; }}
        .ad-bottom {{ margin: 40px 0; }}
        .ad-multiplex {{ margin: 35px 0; }}

        .copyright-notice {{ font-size: 11px; color: #8c8c8c; line-height: 1.5; background: #fafafa; border: 1px solid #f0f0f0; border-radius: 4px; padding: 10px 14px; margin: 35px 0 20px; }}

        .related-wrap {{ margin-top: 40px; border-top: 2px solid #111; padding-top: 24px; }}
        .related-title {{ font-size: 20px; font-weight: 800; margin-bottom: 20px; }}
        .related-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }}
        @media(max-width: 600px) {{ .related-grid {{ grid-template-columns: 1fr; }} }}
        .rel-card {{ display: block; }}
        .rel-thumb {{ border-radius: 6px; overflow: hidden; aspect-ratio: 16/9; margin-bottom: 10px; background: #eee; }}
        .rel-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
        .rel-title {{ font-size: 15px; font-weight: 700; line-height: 1.4; color: #222; }}

        .sidebar-sticky {{ position: sticky; top: 80px; width: 300px; height: 600px; }}
    </style>
</head>
<body>
    {render_header(category)}
    
    <div class="post-layout">
        <main class="post-main">
            <div class="post-cat">{category} 뉴스 &bull; {source}</div>
            <h1 class="post-title">{title}</h1>
            {f'<div class="post-sub">{subtitle}</div>' if subtitle else ''}
            
            <div class="post-meta">
                <span>발행: {date_str} (KST)</span>
                <button type="button" class="share-btn" id="openShareModalBtn">공유하기</button>
            </div>

            <div class="featured-img-wrap">
                <img src="{featured_img}" alt="{title}">
            </div>

            <article class="post-content">
                {content_html}
            </article>

            <!-- 본문 최하단 저작권 및 출처 주석 -->
            {copyright_notice}

            <!-- 구글 애드센스 하단 디스플레이 -->
            <div class="ad-bottom">
                <ins class="adsbygoogle"
                     style="display:block"
                     data-ad-client="{ADSENSE_CLIENT}"
                     data-ad-slot="{AD_SLOT_BOTTOM}"
                     data-ad-format="auto"
                     data-full-width-responsive="true"></ins>
                <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
            </div>

            <!-- 구글 애드센스 멀티플렉스 (일치하는 콘텐츠) -->
            <div class="ad-multiplex">
                <ins class="adsbygoogle"
                     style="display:block"
                     data-ad-format="autorelaxed"
                     data-ad-client="{ADSENSE_CLIENT}"
                     data-ad-slot="{AD_SLOT_MULTIPLEX}"></ins>
                <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
            </div>

            <div class="related-wrap">
                <div class="related-title">CARISSUE 주요 추천 뉴스</div>
                <div class="related-grid">
                    {related_html}
                </div>
            </div>
        </main>

        <aside class="sidebar-wrap">
            <div class="sidebar-sticky">
                <!-- 우측 고정 사이드바 300x600 -->
                <ins class="adsbygoogle"
                     style="display:inline-block;width:300px;height:600px"
                     data-ad-client="{ADSENSE_CLIENT}"
                     data-ad-slot="{AD_SLOT_SIDEBAR}"></ins>
                <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
            </div>
        </aside>
    </div>

    <!-- 공유 모달 팝업 -->
    <div id="shareModal" class="share-modal">
        <div class="share-modal-content">
            <div class="share-title">기사 공유하기</div>
            <div class="share-btn-grid">
                <button type="button" class="share-act-btn" id="shareX">X (트위터)</button>
                <button type="button" class="share-act-btn" id="shareFB">페이스북</button>
                <button type="button" class="share-act-btn" id="copyUrl">URL 복사</button>
            </div>
            <button type="button" class="share-close-btn" id="closeShareModalBtn">닫기</button>
        </div>
    </div>

    {render_footer()}

    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            const modal = document.getElementById('shareModal');
            const openBtn = document.getElementById('openShareModalBtn');
            const closeBtn = document.getElementById('closeShareModalBtn');
            const pageUrl = window.location.href;
            const pageTitle = document.title;

            if (openBtn && modal) {{
                openBtn.addEventListener('click', function(e) {{
                    e.preventDefault();
                    modal.style.display = 'flex';
                }});
            }}

            if (closeBtn && modal) {{
                closeBtn.addEventListener('click', function() {{
                    modal.style.display = 'none';
                }});
            }}

            window.addEventListener('click', function(e) {{
                if (e.target === modal) {{
                    modal.style.display = 'none';
                }}
            }});

            document.getElementById('shareX').addEventListener('click', function() {{
                window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(pageTitle) + '&url=' + encodeURIComponent(pageUrl), '_blank');
            }});

            document.getElementById('shareFB').addEventListener('click', function() {{
                window.open('https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(pageUrl), '_blank');
            }});

            document.getElementById('copyUrl').addEventListener('click', function() {{
                navigator.clipboard.writeText(pageUrl).then(function() {{
                    alert('기사 주소가 클립보드에 복사되었습니다.');
                    modal.style.display = 'none';
                }}).catch(function() {{
                    prompt('아래 URL을 복사하세요:', pageUrl);
                }});
            }});
        }});
    </script>
</body>
</html>
"""
    file_path = os.path.join(POSTS_DIR, f"{post_id}.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(page_html)

# ==========================================
# 7. 메인 화면 (Motor1 스타일 레이아웃) 빌드
# ==========================================
def build_index_page(posts):
    if not posts:
        return

    top_hero = posts[0]
    sub_heroes = posts[1:4]
    remaining_posts = posts[4:]

    def get_thumb(p):
        return p.get("images", ["/assets/logo.png"])[0] if p.get("images") else "/assets/logo.png"

    # Top Hero HTML
    top_hero_html = f"""
    <a href="/posts/{top_hero['id']}.html" class="top-hero-card">
        <div class="top-hero-thumb">
            <img src="{get_thumb(top_hero)}" alt="{top_hero['title']}">
            <div class="top-hero-overlay">
                <span class="badge">{top_hero.get('category','국내')}</span>
                <h2>{top_hero['title']}</h2>
                <p>{top_hero.get('subtitle','')}</p>
            </div>
        </div>
    </a>
    """

    # Sub Heroes HTML (3열 그리드)
    sub_heroes_html = ""
    for sh in sub_heroes:
        sub_heroes_html += f"""
        <a href="/posts/{sh['id']}.html" class="sub-hero-card">
            <div class="sub-hero-thumb">
                <img src="{get_thumb(sh)}" alt="{sh['title']}" loading="lazy">
                <span class="badge">{sh.get('category','글로벌')}</span>
            </div>
            <div class="sub-hero-info">
                <h3>{sh['title']}</h3>
                <span class="date">{sh.get('date','')}</span>
            </div>
        </a>
        """

    # 메인 하단 리스트 HTML
    list_html = ""
    for lp in remaining_posts:
        list_html += f"""
        <a href="/posts/{lp['id']}.html" class="feed-item">
            <div class="feed-thumb">
                <img src="{get_thumb(lp)}" alt="{lp['title']}" loading="lazy">
            </div>
            <div class="feed-text">
                <span class="badge-sm">{lp.get('category','국내')}</span>
                <h4>{lp['title']}</h4>
                <p class="feed-desc">{lp.get('subtitle','')}</p>
                <span class="date">{lp.get('date','')}</span>
            </div>
        </a>
        """

    index_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CARISSUE - 글로벌 & 국내 자동차 전문 매거진</title>
    <meta name="description" content="신차 출시, 스파이샷, 업계 동향 및 시승기 등 가장 빠르고 정확한 프리미엄 자동차 뉴스 포털">
    <link rel="icon" href="/assets/favicon.ico" type="image/x-icon">
    <link rel="canonical" href="{SITE_URL}/">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>
    <style>
        {get_base_css()}
        .main-container {{ max-width: 1200px; margin: 24px auto; padding: 0 20px; }}
        
        .top-hero-card {{ display: block; margin-bottom: 24px; border-radius: 10px; overflow: hidden; position: relative; background: #000; }}
        .top-hero-thumb {{ position: relative; aspect-ratio: 21/9; width: 100%; }}
        .top-hero-thumb img {{ width: 100%; height: 100%; object-fit: cover; opacity: 0.88; }}
        .top-hero-overlay {{ position: absolute; bottom: 0; left: 0; right: 0; padding: 30px; background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 100%); color: #fff; }}
        .top-hero-overlay h2 {{ font-size: 28px; font-weight: 800; line-height: 1.3; margin: 8px 0; }}
        .top-hero-overlay p {{ font-size: 15px; color: #ddd; }}

        .sub-heroes-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 35px; }}
        @media(max-width: 800px) {{ .sub-heroes-grid {{ grid-template-columns: 1fr; }} .top-hero-thumb {{ aspect-ratio: 16/9; }} .top-hero-overlay h2 {{ font-size: 20px; }} }}
        
        .sub-hero-card {{ display: block; border-radius: 8px; overflow: hidden; background: #fff; border: 1px solid var(--border); }}
        .sub-hero-thumb {{ position: relative; aspect-ratio: 16/10; }}
        .sub-hero-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
        .sub-hero-info {{ padding: 14px; }}
        .sub-hero-info h3 {{ font-size: 16px; font-weight: 700; line-height: 1.4; color: #111; }}

        .badge {{ background: var(--primary); color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; display: inline-block; }}
        .badge-sm {{ color: var(--primary); font-size: 12px; font-weight: 700; display: inline-block; margin-bottom: 4px; }}
        .date {{ font-size: 12px; color: #888; display: block; margin-top: 6px; }}

        .infeed-ad-wrap {{ margin: 30px 0; padding: 20px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); text-align: center; }}

        .feed-layout {{ display: grid; grid-template-columns: 1fr 300px; gap: 40px; margin-top: 30px; }}
        @media(max-width: 900px) {{ .feed-layout {{ grid-template-columns: 1fr; }} .side-box {{ display: none; }} }}

        .feed-item {{ display: grid; grid-template-columns: 220px 1fr; gap: 20px; padding: 18px 0; border-bottom: 1px solid var(--border); }}
        @media(max-width: 600px) {{ .feed-item {{ grid-template-columns: 110px 1fr; gap: 12px; }} }}
        .feed-thumb {{ border-radius: 6px; overflow: hidden; aspect-ratio: 16/10; background: #eee; }}
        .feed-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
        .feed-text h4 {{ font-size: 17px; font-weight: 700; line-height: 1.4; color: #111; margin-bottom: 6px; }}
        .feed-desc {{ font-size: 13px; color: #666; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
    </style>
</head>
<body>
    {render_header()}
    
    <div class="main-container">
        {top_hero_html}

        <div class="sub-heroes-grid">
            {sub_heroes_html}
        </div>

        <!-- 인피드 광고 영역 -->
        <div class="infeed-ad-wrap">
            <ins class="adsbygoogle"
                 style="display:block"
                 data-ad-client="{ADSENSE_CLIENT}"
                 data-ad-slot="{AD_SLOT_BOTTOM}"
                 data-ad-format="auto"
                 data-full-width-responsive="true"></ins>
            <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
        </div>

        <div class="feed-layout">
            <div class="feed-list">
                {list_html}
            </div>
            <aside class="side-box">
                <div style="position: sticky; top: 80px; width: 300px; height: 600px;">
                    <ins class="adsbygoogle"
                         style="display:inline-block;width:300px;height:600px"
                         data-ad-client="{ADSENSE_CLIENT}"
                         data-ad-slot="{AD_SLOT_SIDEBAR}"></ins>
                    <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
                </div>
            </aside>
        </div>
    </div>

    {render_footer()}
</body>
</html>
"""
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(index_html)

# ==========================================
# 8. Sitemap.xml 실시간 동기화
# ==========================================
def update_sitemap(posts):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls_xml = f"""  <url>
    <loc>{SITE_URL}/</loc>
    <lastmod>{now_iso}</lastmod>
    <priority>1.0</priority>
  </url>
"""
    for p in posts:
        p_iso = p.get("iso_date", now_iso)
        if len(p_iso) > 10:
            p_iso = p_iso[:10]
        urls_xml += f"""  <url>
    <loc>{SITE_URL}/posts/{p['id']}.html</loc>
    <lastmod>{p_iso}</lastmod>
    <priority>0.8</priority>
  </url>
"""
    sitemap_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_xml}</urlset>
"""
    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(sitemap_content)

# ==========================================
# 9. 메인 실행 파이프라인
# ==========================================
def main():
    os.makedirs(POSTS_DIR, exist_ok=True)
    history_set = load_history()
    feeds = get_current_feeds()

    new_articles = []
    for f_conf in feeds:
        items = fetch_feed_items(f_conf, history_set)
        for item in items:
            print(f"\n[기사 변환 작업] 원문 분석: {item['title']}")
            raw_text, images = extract_article_details(item["link"], item["feed_img"], item.get("feed_desc", ""))
            if not raw_text or len(raw_text) < 80:
                print("-> 본문 추출 실패 또는 내용 부족으로 패스.")
                continue

            generated_md = generate_article_content(item["source"], item["category"], item["title"], raw_text)
            if not generated_md:
                continue

            lines = generated_md.split("\n")
            post_title = item["title"]
            subtitle = ""
            body_lines = []
            post_title_found = False  # 버그 수정: 변수 사전 초기화 완료

            for line in lines:
                if line.startswith("# ") and not post_title_found:
                    post_title = line.replace("# ", "").strip()
                    post_title_found = True
                elif line.startswith("## ") and not subtitle:
                    subtitle = line.replace("## ", "").strip()
                else:
                    body_lines.append(line)

            # 마크다운 문단을 HTML로 변환하며 다중 이미지 분산 배치 및 중간 광고 삽입
            paragraphs = []
            cur_p = []
            for bl in body_lines:
                if bl.strip() == "":
                    if cur_p:
                        paragraphs.append("\n".join(cur_p))
                        cur_p = []
                else:
                    cur_p.append(bl)
            if cur_p:
                paragraphs.append("\n".join(cur_p))

            content_html_parts = []
            img_idx = 1
            for p_i, p_text in enumerate(paragraphs):
                if p_text.startswith("### "):
                    h3_text = p_text.replace("### ", "").strip()
                    content_html_parts.append(f"<h3>{h3_text}</h3>")
                else:
                    content_html_parts.append(f"<p>{p_text}</p>")

                # 2번째 문단 뒤 인아티클 광고 삽입
                if p_i == 1:
                    content_html_parts.append(f"""
                    <div class="ad-in-article">
                        <ins class="adsbygoogle"
                             style="display:block; text-align:center;"
                             data-ad-layout="in-article"
                             data-ad-format="fluid"
                             data-ad-client="{ADSENSE_CLIENT}"
                             data-ad-slot="{AD_SLOT_IN_ARTICLE}"></ins>
                        <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
                    </div>
                    """)

                # 본문 중간 이미지 분산 배치
                if p_i in [0, 2, 4] and img_idx < len(images):
                    content_html_parts.append(f"""
                    <div class="content-img">
                        <img src="{images[img_idx]}" alt="{post_title}" loading="lazy">
                    </div>
                    """)
                    img_idx += 1

            post_id = f"post_{int(time.time())}_{len(new_articles)}"
            now_dt = get_now_kst_dt()
            
            article_record = {
                "id": post_id,
                "title": post_title,
                "subtitle": subtitle,
                "category": item["category"],
                "source": item["source"],
                "date": now_dt.strftime("%Y-%m-%d %H:%M"),
                "iso_date": now_dt.isoformat(),
                "images": images,
                "content_html": "\n".join(content_html_parts)
            }

            new_articles.append(article_record)
            save_history(item["link"])
            time.sleep(2)

    # 기존 DB 동기화 및 전체 리빌드
    data_file = "posts_data.json"
    existing_posts = []
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                existing_posts = json.load(f)
        except Exception:
            existing_posts = []

    all_posts = new_articles + existing_posts
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)

    print(f"\n>>> 전체 기사 수: {len(all_posts)}개 (신규 생성: {len(new_articles)}개)")
    
    # 기존 글까지 포함하여 최신 스크립트(모달, 주석, 푸터)로 일괄 리빌드
    for p in all_posts:
        build_article_page(p, all_posts)

    build_index_page(all_posts)
    update_sitemap(all_posts)
    print(">>> [완료] index.html, sitemap.xml 및 기사 전체 리빌드가 성공적으로 완료되었습니다.")

if __name__ == "__main__":
    main()
