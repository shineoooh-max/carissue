# builder.py - 설정(config)과 수집기(parser)를 받아 HTML 템플릿에 조립하는 경량 엔진
import os
import re
import time
import json
from urllib.parse import urlparse
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


def build_google_preferred_banner():
    domain = urlparse(config.SITE_URL).netloc or "carissue.koo1000.com"
    pref_url = f"https://www.google.com/preferences/source?q={domain}"
    return f"""
    <div class="google-pref-wrap" style="display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:14px 16px; margin:0 0 24px 0; border-top:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb; background:#fafafa;">
        <a href="{pref_url}" target="_blank" rel="noopener noreferrer" style="display:inline-flex; align-items:center; gap:8px; padding:8px 16px; background:#ffffff; border:1px solid #dadce0; border-radius:999px; text-decoration:none; color:#1a73e8; font-size:13px; font-weight:700; box-shadow:0 1px 2px rgba(0,0,0,0.04);">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
                <path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.17Z"/>
                <path fill="#34A853" d="M12 24c3.3 0 6.08-1.09 8.1-2.96l-3.88-3.05c-1.1.74-2.51 1.18-4.22 1.18-3.24 0-5.99-2.19-6.97-5.13H1.02v3.14C3.05 21.2 7.24 24 12 24Z"/>
                <path fill="#FBBC05" d="M5.03 14.04c-.25-.74-.39-1.54-.39-2.36 0-.82.14-1.62.39-2.36V6.18H1.02C.37 7.47 0 8.93 0 10.48s.37 3.01 1.02 4.3l4.01-3.14Z"/>
                <path fill="#EA4335" d="M12 4.75c1.79 0 3.41.62 4.68 1.82l3.51-3.51C18.07 1.19 15.3 0 12 0 7.24 0 3.05 2.8 1.02 6.82l4.01 3.14c.98-2.94 3.73-5.21 6.97-5.21Z"/>
            </svg>
            <span>구글 검색 선호 출처로 추가</span>
        </a>
        <span style="font-size:13px; color:#5f6368; line-height:1.4;">Google 검색과 디스커버에서 CARISSUE 기사를 더 자주 볼 수 있습니다.</span>
    </div>
    """


def parse_markdown_to_html(generated_md, fallback_title, images, source="CARISSUE"):
    lines = generated_md.split("\n")
    post_title = fallback_title
    subtitle = ""
    summary_points = []
    body_blocks = []  # ("h3", text) 또는 ("p", text) 튜플 저장
    title_found = False

    cur_p = []

    def flush_paragraph():
        nonlocal cur_p
        if cur_p:
            body_blocks.append(("p", " ".join(cur_p).strip()))
            cur_p = []

    for line in lines:
        s_line = line.strip()
        if s_line.startswith("# ") and not title_found:
            post_title = s_line[2:].strip()
            title_found = True
        elif s_line.startswith("## ") and not subtitle:
            subtitle = s_line[3:].strip()
        elif s_line.startswith("### "):
            flush_paragraph()
            pt = s_line[4:].strip()
            if pt:
                if len(pt) <= 35:
                    if len(summary_points) < 4:
                        summary_points.append(pt)
                    body_blocks.append(("h3", pt))
                else:
                    body_blocks.append(("p", pt))
        elif s_line.startswith("#"):
            flush_paragraph()
            pt = s_line.lstrip("#").strip()
            if pt:
                if len(pt) <= 35:
                    if len(summary_points) < 4:
                        summary_points.append(pt)
                    body_blocks.append(("h3", pt))
                else:
                    body_blocks.append(("p", pt))
        elif s_line == "":
            flush_paragraph()
        else:
            cur_p.append(s_line)

    flush_paragraph()

    # 왼쪽 빨간 세로줄 핵심 요약 박스 HTML 생성 (메인 이미지 위로 배치하기 위해 별도 보관)
    summary_box_html = ""
    if summary_points:
        summary_items_html = "".join(f"<div class='summary-line'>{pt}</div>" for pt in summary_points[:4])
        summary_box_html = f"""
        <div class="article-summary-box" style="margin: 0 0 22px 0;">
            {summary_items_html}
        </div>
        """

    content_html_parts = []

    def make_ad_block():
        return f"""
        <div class="ad-in-article" style="margin: 24px 0 28px 0;">
            <ins class="adsbygoogle"
                 style="display:block; text-align:center;"
                 data-ad-layout="in-article"
                 data-ad-format="fluid"
                 data-ad-client="{config.ADSENSE_CLIENT}"
                 data-ad-slot="{config.AD_SLOTS['in_article']}"></ins>
            <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
        </div>
        """

    def make_content_img_block(img_url):
        return f"""
        <figure class="content-img" style="margin: 24px 0 12px 0;">
            <img src="{img_url}" alt="{post_title}" referrerpolicy="no-referrer" loading="lazy" onerror="this.closest('.content-img').style.display='none';">
            <figcaption style="font-size: 12px; color: #6b7280; text-align: right; margin-top: 6px;">출처 - {source}</figcaption>
        </figure>
        """

    # 유효한 실제 크롤링 이미지 필터링 (images[0]은 상단 대표이미지, images[1:]는 본문 추가 이미지)
    valid_imgs = [img for img in images if img and "/assets/logo.png" not in img]
    extra_imgs = valid_imgs[1:]
    extra_img_idx = 0

    total_p_count = sum(1 for b_type, _ in body_blocks if b_type == "p")
    p_counter = 0
    ad_counter = 0
    max_in_article_ads = 3

    # 세 템포(3문단)마다 [추가 이미지 + 출처 캡션] + 그 바로 아래 [중간광고] 세트 배치
    for b_type, b_text in body_blocks:
        if b_type == "h3":
            content_html_parts.append(f"<h3>{b_text}</h3>")
            continue

        clean_p = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", b_text)
        content_html_parts.append(f"<p>{clean_p}</p>")
        p_counter += 1

        # 마지막 문단 직후에는 배치 생략 (하단 광고와 겹침 방지)
        if p_counter >= total_p_count:
            continue

        if p_counter % 3 == 0:
            if extra_img_idx < len(extra_imgs):
                content_html_parts.append(make_content_img_block(extra_imgs[extra_img_idx]))
                extra_img_idx += 1
            if ad_counter < max_in_article_ads:
                content_html_parts.append(make_ad_block())
                ad_counter += 1

    if extra_img_idx < len(extra_imgs) and len(content_html_parts) > 1:
        content_html_parts.insert(-1, make_content_img_block(extra_imgs[extra_img_idx]))

    return post_title, subtitle, summary_box_html, "\n".join(content_html_parts)


def build_article_page(item_data, all_posts, article_tpl):
    post_id = item_data["id"]
    title = item_data["title"]
    subtitle = item_data.get("subtitle", "")
    images = item_data.get("images", [])
    valid_imgs = [img for img in images if img and "/assets/logo.png" not in img]
    featured_img = valid_imgs[0] if valid_imgs else ""
    date_str = item_data.get("date", get_now_kst())
    category = item_data.get("category", "국내 이슈")
    source = item_data.get("source", config.SITE_NAME)
    summary_box_html = item_data.get("summary_box_html", "")

    schema_ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "description": subtitle or title,
        "image": valid_imgs if valid_imgs else [f"{config.SITE_URL}/assets/logo.png"],
        "datePublished": item_data.get("iso_date", datetime.now(timezone.utc).isoformat()),
        "author": [{"@type": "Organization", "name": config.SITE_NAME, "url": config.SITE_URL}],
        "publisher": {
            "@type": "Organization",
            "name": config.SITE_NAME,
            "logo": {"@type": "ImageObject", "url": f"{config.SITE_URL}/assets/logo.png"}
        }
    }

    related_html = ""
    for r in [p for p in all_posts if p["id"] != post_id][:6]:
        r_imgs = [i for i in r.get("images", []) if i and "/assets/logo.png" not in i]
        r_img = r_imgs[0] if r_imgs else "/assets/logo.png"
        related_html += f"""
        <a href="/posts/{r['id']}.html" class="rel-card">
            <div class="rel-thumb"><img src="{r_img}" alt="{r['title']}" referrerpolicy="no-referrer" loading="lazy"></div>
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
    if not featured_img:
        html = re.sub(r'<div class="featured-img-wrap">.*?</div>', "", html, flags=re.DOTALL)
    else:
        # 대표 메인 이미지 하단에 '출처 - {source}' 캡션 추가 + 요약 목차를 메인 이미지 바로 위로 배치
        caption_tag = f'<div class="featured-caption" style="font-size: 12px; color: #6b7280; text-align: right; margin-top: 6px;">출처 - {source}</div>'
        html = re.sub(
            r'(<div class="featured-img-wrap">.*?)(</div>)',
            rf'{summary_box_html}\n\1{caption_tag}\2',
            html,
            count=1,
            flags=re.DOTALL
        )
        summary_box_html = ""

    # 구글 선호 출처 배너 결합 (대표 이미지가 없는 기사라면 요약 목차도 함께 상단 결합)
    raw_content_html = item_data.get("content_html", "")
    prefix_blocks = [summary_box_html] if summary_box_html else []
    if "google-pref-wrap" not in raw_content_html:
        prefix_blocks.append(build_google_preferred_banner())
    prefix_blocks.append(raw_content_html)
    full_article_content = "\n".join(b for b in prefix_blocks if b)

    replacements = {
        "{{SITE_HEADER}}": load_template("header.html"),
        "{{SITE_FOOTER}}": load_template("footer.html"),
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
        "{{FEATURED_IMG}}": featured_img if featured_img else f"{config.SITE_URL}/assets/logo.png",
        "{{ARTICLE_CONTENT}}": full_article_content,
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

    top_hero_html = f"""
    <a href="/posts/{top_hero['id']}.html" class="hero-split">
        <div class="hero-split-img">
            <img src="{get_thumb(top_hero)}" alt="{top_hero['title']}" referrerpolicy="no-referrer">
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

    sub_heroes_html = ""
    for sh in sub_heroes:
        sub_heroes_html += f"""
        <a href="/posts/{sh['id']}.html" class="sub-card">
            <div class="sub-card-img">
                <img src="{get_thumb(sh)}" alt="{sh['title']}" referrerpolicy="no-referrer" loading="lazy">
            </div>
            <div><span class="badge-red">{sh.get('category', '글로벌 뉴스')}</span></div>
            <h3>{sh['title']}</h3>
            <span class="meta-info">{sh.get('date', '')}</span>
        </a>
        """

    feed_list_html = ""
    for lp in remaining_posts:
        feed_list_html += f"""
        <a href="/posts/{lp['id']}.html" class="feed-item">
            <div class="feed-thumb">
                <img src="{get_thumb(lp)}" alt="{lp['title']}" referrerpolicy="no-referrer" loading="lazy">
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
        "{{SITE_HEADER}}": load_template("header.html"),
        "{{SITE_FOOTER}}": load_template("footer.html"),
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

                # 기존 HTML 하단 저작권 문구에서 원문 언론사명 추출 및 보존
                rec_source = config.SITE_NAME
                src_match = re.search(r"각 언론사\((.+?)\s*등\)의", raw_html)
                if src_match and src_match.group(1).strip():
                    rec_source = src_match.group(1).strip()

                article_el = h_soup.find("article", class_="post-content") or h_soup.find("article")
                cleaned_body_parts = []
                if article_el:
                    for child in article_el.children:
                        tag_name = getattr(child, "name", None)
                        if tag_name in ["h1", "h2", "h3", "h4"]:
                            t = child.get_text().strip()
                            if not t:
                                continue
                            if len(t) > 45:
                                cleaned_body_parts.append(f"<p>{t}</p>")
                            else:
                                cleaned_body_parts.append(f"<h3>{t}</h3>")
                        elif tag_name == "p":
                            t_html = child.decode_contents().strip()
                            if t_html:
                                cleaned_body_parts.append(f"<p>{t_html}</p>")
                        elif tag_name in ["div", "figure"] and "content-img" in child.get("class", []):
                            cleaned_body_parts.append(str(child))
                        elif tag_name == "div" and "ad-in-article" in child.get("class", []):
                            cleaned_body_parts.append(str(child))

                existing_posts.append({
                    "id": pid,
                    "title": rec_title,
                    "subtitle": rec_sub,
                    "category": rec_cat,
                    "source": rec_source,
                    "date": rec_date,
                    "iso_date": rec_date[:10],
                    "images": rec_images,
                    "summary_box_html": "",
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

                post_title, subtitle, summary_box_html, content_html = parse_markdown_to_html(
                    generated_md, item["title"], images, item["source"]
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
                    "summary_box_html": summary_box_html,
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

    target_build_posts = all_posts if design_only else new_articles
    for p in target_build_posts:
        if p.get("content_html"):
            build_article_page(p, all_posts, article_tpl)

    build_index_page(all_posts, index_tpl)
    update_sitemap(all_posts)
    print(">>> [완료] 새 템플릿 기반 전체 페이지 및 sitemap.xml 빌드가 완료되었습니다.")


if __name__ == "__main__":
    main()
