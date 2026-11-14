# parser.py - RSS 수집, 이미지 필터링, Gemini 기사 생성 전용 모듈
import os
import re
import urllib.request
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from google import genai
import config

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
BLOCKED_IMG_KEYWORDS = ["logo", "icon", "banner", "btn", "favicon", "avatar", "ad_", "blank", "placeholder"]


def normalize_img_url(base_url, src):
    if not src:
        return ""
    src = src.strip()
    if src.startswith("data:"):
        return ""
    if src.startswith("//"):
        return "https:" + src
    if not src.startswith("http"):
        return urljoin(base_url, src)
    return src


def get_img_fingerprint(img_url):
    path = urlparse(img_url).path
    fname = os.path.basename(path).lower()
    fname = re.sub(r"-\d+x\d+(?=\.[a-z]+$)", "", fname)
    fname = re.sub(r"_(thumb|small|medium|large|s|m|l)(?=\.[a-z]+$)", "", fname)
    return fname


def fetch_feed_items(feed_conf, history_set):
    items = []
    target = feed_conf["target_count"]
    print(f"\n[{feed_conf['name']}] RSS 수집 시작 ({feed_conf['category']} - 목표: {target}건)")

    try:
        req = urllib.request.Request(feed_conf["url"], headers={"User-Agent": USER_AGENT})
        raw_data = urllib.request.urlopen(req, timeout=15).read()
        try:
            xml_text = raw_data.decode("utf-8")
        except UnicodeDecodeError:
            xml_text = raw_data.decode("cp949", errors="ignore")

        root = ET.fromstring(xml_text)
        entries = root.findall(".//item")

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
        print(f"[{feed_conf['name']}] RSS 수집 오류: {e}")

    return items


def extract_article_details(url, feed_img="", feed_desc=""):
    images = []
    seen_fps = set()
    text_content = ""
    safe_desc = feed_desc or ""

    def try_add_image(raw_src):
        full_url = normalize_img_url(url, raw_src)
        if not full_url or not full_url.startswith("http"):
            return
        if any(x in full_url.lower() for x in BLOCKED_IMG_KEYWORDS):
            return
        fp = get_img_fingerprint(full_url)
        if fp and fp in seen_fps:
            return
        if full_url not in images:
            images.append(full_url)
            if fp:
                seen_fps.add(fp)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")

        # 1. og:image 메타 태그를 1순위 대표 이미지로 추출
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            try_add_image(og_img["content"])

        # 2. og:image가 없을 때만 feed_img 보조 활용
        if not images and feed_img:
            try_add_image(feed_img)

        # 3. 본문 영역 내 고화질 차량 사진 추가 수집 (최대 6장)
        article_elem = (
            soup.find("div", id=re.compile(r"article-view-content-div|articleBody", re.I)) or
            soup.find("article") or
            soup.find("div", class_=re.compile(r"article-body|entry-content|content|post-body|view-content", re.I)) or
            soup.body
        )

        if article_elem:
            for img in article_elem.find_all("img"):
                src = img.get("data-src") or img.get("data-original") or img.get("src")
                if not src and img.get("srcset"):
                    src = img.get("srcset").split(",")[0].split(" ")[0]
                try_add_image(src)
                if len(images) >= 6:
                    break

            paragraphs = [
                p.get_text().strip()
                for p in article_elem.find_all(["p", "h2", "h3"])
                if len(p.get_text().strip()) > 20
            ]
            text_content = "\n\n".join(paragraphs)

        if (not text_content or len(text_content) < 80) and safe_desc:
            text_content = BeautifulSoup(safe_desc, "html.parser").get_text().strip()

    except Exception as e:
        print(f"본문 파싱 예외: {e}")
        if safe_desc:
            text_content = BeautifulSoup(safe_desc, "html.parser").get_text().strip()

    return text_content[:4000], images


def generate_article_content(api_key, source, category, original_title, raw_text):
    client = genai.Client(api_key=api_key)
    prompt = f"""
당신은 프리미엄 자동차 전문 웹진 'CARISSUE(카이슈)'의 수석 에디터입니다.
아래 출처({source}, 분류: {category})의 원문을 바탕으로 모바일 가독성이 뛰어난 한국어 자동차 매거진 기사를 작성하세요.

[원문 정보]
제목: {original_title}
내용:
{raw_text}

[엄격한 작성 규칙]
1. 첫 줄은 반드시 `# 제목` 형식으로 매력적인 한국어 헤드라인 1줄만 작성하세요.
2. 둘째 줄은 반드시 `## 부제목` 형식으로 핵심 요약 1줄만 작성하세요.
3. 분량 조절: 원문 내용의 밀도와 길이에 자연스럽게 비례하여 작성하세요. 짧은 단신이나 보도자료는 억지로 늘리지 말고 4~5문단 내외로 핵심만 간결하게 정리하고, 원문이 풍부한 심층 기사는 6~8문단 내외로 깊이 있게 구성하세요.
4. 섹션 구성: 내용의 흐름에 따라 2~4개의 섹션으로 나누고, 각 섹션 시작 전 반드시 `### 짧은 소제목` (15자 내외)을 붙이세요.
5. 모바일 문단 호흡: 한 문단은 모바일 화면에서 3~4줄로 편하게 읽히도록 2~3문장(약 100~140자) 분량으로 끊어 작성하고, 문단과 문단 사이에는 반드시 빈 줄을 넣으세요.
6. 본문 문단에는 `#` 기호나 굵은 마크다운 제목을 쓰지 말고 순수 텍스트 문장으로만 작성하세요.
"""
    try:
        interaction = client.interactions.create(
            model=config.GEMINI_MODEL,
            input=prompt
        )
        return interaction.output_text.strip()
    except Exception as e:
        print(f"Gemini API 에러: {e}")
        return None
