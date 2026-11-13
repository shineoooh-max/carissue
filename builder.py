# builder.py - 설정(config)과 수집기(parser)를 받아 HTML 템플릿에 조립하는 경량 엔진
import os
import re
import time
import json
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import config
import parser

KST = timezone(timedelta(hours=9))


def get_now_kst_dt():
    return datetime.now(KST)


def get_now_kst():
    return get_now_kst_dt().strftime("%Y-%m-%d %H:%M")


def load_template(filename):
    path = os.path.join(config.TEMPLATES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_history():
    if os.path.exists(config.HISTORY_FILE):
        with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_history(link):
    with open(config.HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link.strip() + "\n")


def get_current_feeds():
    now = get_now_kst_dt()
    if now.hour < 12:
        print(f">>> [KST 오전] 국내 기사 수집 시작 (현재시각: {now.strftime('%H:%M')})")
        return config.FEEDS_MORNING
    else:
        print(f">>> [KST 오후] 글로벌 기사 수집 시작 (현재시각: {now.strftime('%H:%M')})")
        return config.FEEDS_EVENING


def parse_markdown_to_html(generated_md, fallback_title, images):
    lines = generated_md.split("\n")
    post_title = fallback_title
    subtitle = ""
    body_lines = []
    title_found = False

    for line in lines:
        s_line = line.strip()
        if s_line.startswith("# ") and not title_found:
            post_title = s_line[2:].strip()
            title_found = True
        elif s_line.startswith("## ") and not subtitle:
            subtitle = s_line[3:].strip()
        else:
            body_lines.append(line)

    # 빈 줄 기준으로 문단 분리
    paragraphs = []
    cur_p = []
    for bl in body_lines:
        if bl.strip() == "":
            if cur_p:
                paragraphs.append(" ".join(cur_p).strip())
                cur_p = []
        else:
            cur_p.append(bl.strip())
    if cur_p:
        paragraphs.append(" ".join(cur_p).strip())

    content_html_parts = []
    img_idx = 1  # images[0]은 상단 대표 이미지로 사용되므로 본문은 1번부터 배치
    p_count = 0

    for p_text in paragraphs:
        # 소제목 처리 (### 또는 잘못 붙은 #/## 방어)
        if p_text.startswith("### "):
            h3_text = p_text[4:].strip()
            content_html_parts.append(f"<h3>{h3_text}</h3>")
            # 소제목 1개당 이미지 1장 배치
            if img_idx < len(images):
                content_html_parts.append(
                    f'<div class="content-img"><img src="{images[img_idx]}" alt="{h3_text}" loading="lazy"></div>'
                )
                img_idx += 1
        elif p_text.startswith("#"):
            clean_h3 = p_text.lstrip("#").strip()
            content_html_parts.append(f"<h3>{clean_h3}</h3>")
            if img_idx < len(images):
                content_html_parts.append(
                    f'<div class="content-img"><img src="{images[img_idx]}" alt="{clean_h3}" loading="lazy"></div>'
                )
                img_idx += 1
        else:
            # 일반 본문 문단 (무조건 <p> 태그 강제)
            clean_p = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", p_text)
            content_html_parts.append(f"<p>{clean_p}</p>")
            p_count += 1

            # 2번째 문단 뒤에 인아티클 광고 삽입
            if p_count == 2:
                content_html_parts.append(f"""
                <div class="ad-in-article">
                    <ins class="adsbygoogle"
                         style="display:block; text-align:center;"
                         data-ad-layout="in-article"
                         data-ad-format="fluid"
                         data-ad-client="{config.ADSENSE_CLIENT}"
                         data-ad-slot="{config.AD_SLOTS['in_article']}"></ins>
                    <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
                </div>
                """)

    return post_title, subtitle, "\n".join(content_html_parts)


def build_article_page(item_data, all_posts, article_tpl):
    post_id = item_data["id"]
    title = item_data["title"]
    subtitle = item_data.get("subtitle", "")
    images = item_data.get("images", [])
    featured_img = images[0] if images else "/assets/logo.png"
    date_str = item_data.get("date", get_now_kst())
    category = item_data.get("category", "국내 이슈")
    source = item_data.get("source", config.SITE_NAME)

    schema_ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "description": subtitle or title,
        "image": images,
        "datePublished": item_data.get("iso_date", datetime.now(timezone.utc).isoformat()),
        "author": [{"@type": "Organization", "name": config.SITE_NAME, "url": config.SITE_URL}],
        "publisher": {
            "@type": "Organization",
            "name": config.SITE_NAME,
            "logo": {"@type": "ImageObject", "url": f"{config.SITE_URL}/assets/logo.png"}
        }
    }

    related_html = ""
    for r in [p for p in all_posts if p["id"] != post_id][:3]:
        r_img = r.get("images", ["/assets/logo.png"])[0] if r.get("images") else "/assets/logo.png"
        related_html += f"""
        <a href="/posts/{r['id']}.html" class="rel-card">
            <div class="rel-thumb"><img src="{r_img}" alt="{r['title']}" loading="lazy"></div>
            <div class="rel-title">{r['title']}</div>
        </a>
        """

    subtitle_html = f'<div class="post-sub">{subtitle}</div>' if subtitle else ""
    copyright_html = f"""
    <div class="copyright-notice">
        ※ 본 기사는 각 언론사({source} 등)의 공식 보도자료 및 외신 브리핑을 바탕으로 CARISSUE 편집국의 분석을 더해 재구성되었으며, 대표 이미지의 저작권은 해당 원문 출처에 있습니다.
    </div>
    """

    html = article_tpl
    replacements = {
        "{{SITE_URL}}": config.SITE_URL,
        "{{ADSENSE_CLIENT}}": config.ADSENSE_CLIENT,
        "{{AD_SLOT_BOTTOM}}": config.AD_SLOTS["bottom"],
        "{{AD_SLOT_MULTIPLEX}}": config.AD_SLOTS["multiplex"],
        "{{AD_SLOT_SIDEBAR}}": config.AD_SLOTS["sidebar"],
        "{{POST_ID}}": post_id,
        "{{POST_TITLE}}": title,
        "{{POST_SUBTITLE}}": subtitle or title,
        "{{POST_SUBTITLE_HTML}}": subtitle_html,
        "{{POST_CATEGORY}}": category,
        "{{POST_DATE}}": date_str,
        "{{FEATURED_IMG}}": featured_img,
        "{{ARTICLE_CONTENT}}": item_data.get("content_html", ""),
        "{{COPYRIGHT_NOTICE}}": copyright_html,
        "{{RELATED_POSTS_HTML}}": related_html,
        "{{SCHEMA_JSON_LD}}": json.dumps(schema_ld, ensure_ascii=False, indent=2),
    }

    for marker, val in replacements.items():
        html = html.replace(marker, val)

    file_path = os.path.join(config.POSTS_DIR, f"{post_id}.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)


def build_index_page(posts, index_tpl):
    if not posts:
        return

    def get_thumb(p):
        imgs = p.get("images", [])
        return imgs[0] if (imgs and len(imgs) > 0 and imgs[0]) else "/assets/logo.png"

    top_hero = posts[0]
    sub_heroes = posts[1:4]
    remaining_posts = posts[4:]

    # 1. 상단 60:40 스플릿 메인 기사
    top_hero_html = f"""
    <a href="/posts/{top_hero['id']}.html" class="hero-split">
        <div class="hero-split-img">
            <img src="{get_thumb(top_hero)}" alt="{top_hero['title']}">
        </div>
        <div class="hero-split-body">
            <div class="hero-kicker">
                <span class="badge-red">{top_hero.get('category', '국내 이슈')}</span>
                <span class="top-story-tag">TOP STORY</span>
            </div>
            <h1>{top_hero['title']}</h1>
            <p>{top_hero.get('subtitle', '')}</p>
            <span class="meta-info">{top_hero.get('date', '')} &bull; CARISSUE 편집국</span>
        </div>
    </a>
    """

    # 2. 중단 3열 서브 카드
    sub_heroes_html = ""
    for sh in sub_heroes:
        sub_heroes_html += f"""
        <a href="/posts/{sh['id']}.html" class="sub-card">
            <div class="sub-card-img">
                <img src="{get_thumb(sh)}" alt="{sh['title']}" loading="lazy">
            </div>
            <div><span class="badge-red">{sh.get('category', '글로벌 뉴스')}</span></div>
            <h3>{sh['title']}</h3>
            <span class="meta-info">{sh.get('date', '')}</span>
        </a>
        """

    # 3. 하단 최신 뉴스 피드
    feed_list_html = ""
    for lp in remaining_posts:
        feed_list_html += f"""
        <a href="/posts/{lp['id']}.html" class="feed-item">
            <div class="feed-thumb">
                <img src="{get_thumb(lp)}" alt="{lp['title']}" loading="lazy">
            </div>
            <div class="feed-content">
                <span class="badge-red">{lp.get('category', '국내 이슈')}</span>
                <h4>{lp['title']}</h4>
                <p class="feed-desc">{lp.get('subtitle', '')}</p>
                <span class="meta-info">{lp.get('date', '')}</span>
            </div>
        </a>
        """

    html = index_tpl
    replacements = {
        "{{SITE_URL}}": config.SITE_URL,
        "{{ADSENSE_CLIENT}}": config.ADSENSE_CLIENT,
        "{{AD_SLOT_BOTTOM}}": config.AD_SLOTS["bottom"],
        "{{AD_SLOT_SIDEBAR}}": config.AD_SLOTS["sidebar"],
        "{{TOP_HERO_HTML}}": top_hero_html,
        "{{SUB_HEROES_HTML}}": sub_heroes_html,
        "{{FEED_LIST_HTML}}": feed_list_html,
    }

    for marker, val in replacements.items():
        html = html.replace(marker, val)

    with open(config.INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def update_sitemap(posts):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    static_pages = [
        ("", "1.0"),
        ("about.html", "0.7"),
        ("privacy.html", "0.5"),
        ("terms.html", "0.5"),
    ]
    urls_xml = ""
    for path, prio in static_pages:
        loc = f"{config.SITE_URL}/{path}" if path else f"{config.SITE_URL}/"
        urls_xml += f"""  <url>
    <loc>{loc}</loc>
    <lastmod>{now_iso}</lastmod>
    <priority>{prio}</priority>
  </url>
"""

    for p in posts:
        p_iso = p.get("iso_date", now_iso)[:10]
        urls_xml += f"""  <url>
    <loc>{config.SITE_URL}/posts/{p['id']}.html</loc>
    <lastmod>{p_iso}</lastmod>
    <priority>0.8</priority>
  </url>
"""

    sitemap_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_xml}</urlset>
"""
    with open(config.SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(sitemap_content)


def scan_existing_posts(exclude_ids):
    existing_posts = []
    if not os.path.exists(config.POSTS_DIR):
        return existing_posts

    for fname in sorted(os.listdir(config.POSTS_DIR), reverse=True):
        if not (fname.endswith(".html") and fname.startswith("post_")):
            continue
        pid = fname.replace(".html", "")
        if pid in exclude_ids:
            continue

        fpath = os.path.join(config.POSTS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as hf:
                raw_html = hf.read()
                h_soup = BeautifulSoup(raw_html, "html.parser")

                rec_title, rec_sub, rec_date = "", "", ""
                rec_images = []
                schema_script = h_soup.find("script", type="application/ld+json")
                if schema_script and schema_script.string:
                    try:
                        s_data = json.loads(schema_script.string.strip())
                        rec_title = s_data.get("headline", "")
                        rec_sub = s_data.get("description", "")
                        s_img = s_data.get("image", [])
                        if isinstance(s_img, list):
                            rec_images = [i for i in s_img if i]
                        elif isinstance(s_img, str) and s_img:
                            rec_images = [s_img]
                        if "datePublished" in s_data:
                            rec_date = s_data["datePublished"][:16].replace("T", " ")
                    except Exception:
                        pass

                if not rec_title:
                    h1 = h_soup.find("h1")
                    rec_title = h1.get_text().strip() if h1 else pid

                if not rec_images:
                    og_img = h_soup.find("meta", property="og:image")
                    if og_img and og_img.get("content"):
                        rec_images = [og_img["content"].strip()]
                if not rec_images:
                    rec_images = ["/assets/logo.png"]

                if not rec_date:
                    m = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", raw_html)
                    rec_date = m.group(0) if m else get_now_kst()

                rec_cat = "글로벌 뉴스"
                cat_el = h_soup.find(class_=re.compile(r"post-cat|category|badge"))
                if cat_el and "국내" in cat_el.get_text():
                    rec_cat = "국내 이슈"

                # 기존 본문 HTML 추출 및 긴 문장이 소제목(h3)으로 뭉치는 현상 교정
                article_el = h_soup.find("article", class_="post-content") or h_soup.find("article")
                cleaned_body_parts = []
                if article_el:
                    for child in article_el.children:
                        tag_name = getattr(child, "name", None)
                        if tag_name in ["h1", "h2", "h3", "h4"]:
                            t = child.get_text().strip()
                            if not t:
                                continue
                            # 45자 초과 시 소제목이 아닌 일반 본문 문단(<p>)으로 교정
                            if len(t) > 45:
                                cleaned_body_parts.append(f"<p>{t}</p>")
                            else:
                                cleaned_body_parts.append(f"<h3>{t}</h3>")
                        elif tag_name == "p":
                            t_html = child.decode_contents().strip()
                            if t_html:
                                cleaned_body_parts.append(f"<p>{t_html}</p>")
                        elif tag_name == "div" and "content-img" in child.get("class", []):
                            cleaned_body_parts.append(str(child))
                        elif tag_name == "div" and "ad-in-article" in child.get("class", []):
                            cleaned_body_parts.append(str(child))

                existing_posts.append({
                    "id": pid,
                    "title": rec_title,
                    "subtitle": rec_sub,
                    "category": rec_cat,
                    "source": config.SITE_NAME,
                    "date": rec_date,
                    "iso_date": rec_date[:10],
                    "images": rec_images,
                    "content_html": "\n".join(cleaned_body_parts)
                })
        except Exception as err:
            print(f"기존 기사 파싱 예외 ({fname}): {err}")

    return existing_posts


def main():
    design_only = os.environ.get("DESIGN_ONLY", "false").lower() == "true"

    os.makedirs(config.POSTS_DIR, exist_ok=True)
    article_tpl = load_template("article.html")
    index_tpl = load_template("index.html")
    new_articles = []

    if not design_only:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is missing.")

        history_set = load_history()
        feeds = get_current_feeds()

        for f_conf in feeds:
            items = parser.fetch_feed_items(f_conf, history_set)
            for item in items:
                print(f"\n[기사 생성] 원문 분석: {item['title']}")
                raw_text, images = parser.extract_article_details(
                    item["link"], item["feed_img"], item.get("feed_desc", "")
                )
                if not raw_text or len(raw_text) < 80:
                    continue

                generated_md = parser.generate_article_content(
                    api_key, item["source"], item["category"], item["title"], raw_text
                )
                if not generated_md:
                    continue

                post_title, subtitle, content_html = parse_markdown_to_html(
                    generated_md, item["title"], images
                )

                post_id = f"post_{int(time.time())}_{len(new_articles)}"
                now_dt = get_now_kst_dt()

                new_articles.append({
                    "id": post_id,
                    "title": post_title,
                    "subtitle": subtitle,
                    "category": item["category"],
                    "source": item["source"],
                    "date": now_dt.strftime("%Y-%m-%d %H:%M"),
                    "iso_date": now_dt.isoformat(),
                    "images": images,
                    "content_html": content_html
                })
                save_history(item["link"])
                time.sleep(2)
    else:
        print(">>> [디자인 전용 모드] AI 기사 생성을 건너뛰고 기존 기사 전체에 새 디자인을 일괄 적용합니다. (토큰 소모 0원)")

    new_ids = {na["id"] for na in new_articles}
    existing_posts = scan_existing_posts(new_ids)
    all_posts = new_articles + existing_posts
    all_posts.sort(key=lambda x: x.get("id", ""), reverse=True)

    print(f"\n>>> [스캔 완료] 총 기사 수: {len(all_posts)}개 (신규: {len(new_articles)}개, 기존 복원: {len(existing_posts)}개)")

    # 신규 기사는 무조건 빌드, 디자인 전용 모드일 때는 기존 기사까지 전부 새 article.html로 일괄 재빌드
    target_build_posts = all_posts if design_only else new_articles
    for p in target_build_posts:
        if p.get("content_html"):
            build_article_page(p, all_posts, article_tpl)

    build_index_page(all_posts, index_tpl)
    update_sitemap(all_posts)
    print(">>> [완료] 새 템플릿 기반 전체 페이지 및 sitemap.xml 빌드가 완료되었습니다.")


if __name__ == "__main__":
    main()
