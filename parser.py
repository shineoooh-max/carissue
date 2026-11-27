# parser.py - RSS 수집, 다중 고화질 이미지 + 캡션 추출, Gemini 기사 생성 전용 모듈
import os
import re
import struct
import time
import urllib.request
from urllib.parse import urljoin, urlparse, parse_qs
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from google import genai
import config

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
BLOCKED_IMG_KEYWORDS = [
    "logo", "icon", "banner", "btn", "favicon", "avatar", "ad_",
    "blank", "placeholder", "spinner", "loading", "1x1", "pixel",
    "sprite", "sns", "share", "button", "badge", "author", "profile",
    "noimage", "no-image", "default", "reporter", "journalist", "brand",
    "emblem", "ci_", "bi_", "thumb_s", "/skin/", "/common/", "/layout/"
]


def normalize_img_url(base_url, src):
    if not src:
        return ""
    src = src.strip()
    if src.startswith("data:") or src.startswith("blob:"):
        return ""
    if src.startswith("//"):
        return "https:" + src
    if not src.startswith("http"):
        return urljoin(base_url, src)
    return src


def clean_caption_text(raw_caption):
    """이미지 alt/figcaption에서 파일명이나 의미 없는 기호 제거 후 정제"""
    if not raw_caption:
        return ""
    text = re.sub(r"\s+", " ", raw_caption).strip()
    # 파일명 형태(예: 20261115_1234.jpg, image1.png) 제외
    if re.search(r"\.(jpg|jpeg|png|webp|gif)$", text, re.I):
        return ""
    # 너무 짧거나 단순한 단어 제외
    if len(text) < 4 or text.lower() in ("image", "photo", "picture", "이미지", "사진", "썸네일"):
        return ""
    # 불필요한 대괄호 출처 표기([사진=현대차] 등)는 가독성을 위해 정리
    text = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
    if len(text) > 70:
        text = text[:67].rstrip() + "..."
    return text


def extract_caption_from_tag(img_tag):
    """<img> 태그의 부모 <figure>/<figcaption> 또는 alt/title 속성에서 설명 추출"""
    if not img_tag:
        return ""

    # 1순위: 감싸고 있는 <figure> 내부의 <figcaption> 텍스트
    figure = img_tag.find_parent("figure")
    if figure:
        figcap = figure.find("figcaption")
        if figcap:
            cleaned = clean_caption_text(figcap.get_text())
            if cleaned:
                return cleaned

    # 2순위: ND소프트(모터그래프/카가이/오토헤럴드) 이미지 캡션 클래스 탐색
    parent_box = img_tag.find_parent(["div", "td", "p"])
    if parent_box:
        cap_el = parent_box.find(["figcaption", "span", "p", "div"], class_=re.compile(r"caption|desc|txt|title", re.I))
        if cap_el and cap_el != img_tag:
            cleaned = clean_caption_text(cap_el.get_text())
            if cleaned:
                return cleaned

    # 3순위: img 태그의 alt 또는 title 속성
    alt_text = img_tag.get("alt") or img_tag.get("title") or ""
    return clean_caption_text(alt_text)


def extract_best_from_srcset(srcset_val):
    if not srcset_val:
        return ""
    candidates = [c.strip() for c in re.split(r",\s*(?=https?://|/)", srcset_val) if c.strip()]
    if not candidates:
        return ""
    return candidates[-1].split()[0]


def get_img_fingerprint(img_url):
    parsed = urlparse(img_url)
    path = parsed.path
    fname = os.path.basename(path).lower()
    fname = re.sub(r"-\d+x\d+(?=\.[a-z]+$)", "", fname)
    fname = re.sub(r"_(thumb|small|medium|large|s|m|l)(?=\.[a-z]+$)", "", fname)

    qs = parse_qs(parsed.query)
    id_part = ""
    for key in ("id", "img", "file", "idx", "photo"):
        if key in qs and qs[key]:
            id_part = f"_{key}={qs[key][0]}"
            break

    return f"{fname}{id_part}" if fname else img_url


def is_valid_large_image(img_url, min_width=450):
    try:
        req = urllib.request.Request(
            img_url,
            headers={"User-Agent": USER_AGENT, "Range": "bytes=0-32768"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(32768)

        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return w >= min_width and h >= 220

        if data[:2] == b"\xff\xd8":
            idx = 2
            while idx < len(data) - 9:
                if data[idx] != 0xFF:
                    idx += 1
                    continue
                marker = data[idx + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[idx + 5:idx + 9])
                    return w >= min_width and h >= 220
                if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
                    idx += 2
                    continue
                seg_len = struct.unpack(">H", data[idx + 2:idx + 4])[0]
                idx += 2 + seg_len

        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            chunk = data[12:16]
            if chunk == b"VP8X" and len(data) >= 30:
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return w >= min_width and h >= 220

        return len(data) >= 15360
    except Exception:
        return False


def decode_html_bytes(raw_bytes):
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="ignore")


def fetch_url_bytes(url, headers=None, timeout=15, max_retries=2):
    req_headers = headers or {"User-Agent": USER_AGENT}
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait_sec = 2 * (attempt + 1)
                print(f"HTTP 요청 재시도 ({attempt + 1}/{max_retries}, {wait_sec}s 대기): {url} -> {e}")
                time.sleep(wait_sec)
    raise last_err


def fetch_feed_items(feed_conf, history_set):
    items = []
    target = feed_conf["target_count"]
    print(f"\n[{feed_conf['name']}] RSS 수집 시작 ({feed_conf['category']} - 목표: {target}건)")

    try:
        raw_data = fetch_url_bytes(feed_conf["url"], timeout=15, max_retries=2)
        xml_text = decode_html_bytes(raw_data)

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
    images = []  # [{"url": ..., "caption": ...}, ...] 형태로 저장
    fp_to_idx = {}
    text_content = ""
    safe_desc = feed_desc or ""
    is_korean_media = any(domain in url.lower() for domain in ("motorgraph.com", "carguy.kr", "autoherald.co.kr"))

    def try_add_image(raw_src, caption="", skip_size_check=False):
        full_url = normalize_img_url(url, raw_src)
        if not full_url or not full_url.startswith("http"):
            return
        lower_u = full_url.lower()
        if any(x in lower_u for x in BLOCKED_IMG_KEYWORDS):
            return
        if "{" in full_url or "}" in full_url or "\\u" in full_url:
            return
        if urlparse(lower_u).path.endswith((".svg", ".gif")):
            return

        if is_korean_media and "/news/photo/" not in lower_u:
            return

        fp = get_img_fingerprint(full_url)

        # 이미 og:image로 먼저 들어온 동일 이미지인데 본문 스캔에서 캡션이 발견되면 캡션만 보강!
        if fp and fp in fp_to_idx:
            existing_idx = fp_to_idx[fp]
            if caption and not images[existing_idx]["caption"]:
                images[existing_idx]["caption"] = caption
            return

        if not skip_size_check and not is_valid_large_image(full_url, min_width=450):
            return

        new_idx = len(images)
        images.append({"url": full_url, "caption": caption})
        if fp:
            fp_to_idx[fp] = new_idx

    def scan_container_images(container):
        if not container:
            return
        # 1) <picture> 내부 고화질 원본 수집
        for pic in container.find_all("picture"):
            source_tag = pic.find("source")
            img_in_pic = pic.find("img")
            if source_tag:
                best_src = extract_best_from_srcset(
                    source_tag.get("data-srcset") or source_tag.get("srcset")
                )
                if best_src:
                    cap = extract_caption_from_tag(img_in_pic or pic)
                    try_add_image(best_src, caption=cap)
                    if len(images) >= 5:
                        return

        # 2) 일반 <img> 태그 수집 + 캡션 추출
        for img in container.find_all("img"):
            parent_classes = " ".join(
                " ".join(p.get("class", [])) + " " + (p.get("id") or "")
                for p in img.parents if getattr(p, "get", None)
            ).lower()
            if any(bad in parent_classes for bad in ("reporter", "journalist", "profile", "author", "related", "recommend", "banner", "brand", "tag", "byline")):
                continue

            w = img.get("width")
            h = img.get("height")
            if w and w.isdigit() and int(w) < 300:
                continue
            if h and h.isdigit() and int(h) < 180:
                continue

            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("data-img-url")
                or extract_best_from_srcset(img.get("data-srcset") or img.get("srcset"))
                or img.get("src")
            )
            cap = extract_caption_from_tag(img)
            try_add_image(src, caption=cap)
            if len(images) >= 5:
                return

    try:
        raw_bytes = fetch_url_bytes(url, timeout=15, max_retries=2)
        html = decode_html_bytes(raw_bytes)
        soup = BeautifulSoup(html, "html.parser")

        # 1. og:image 메타 태그 (og:image:alt가 있으면 함께 추출)
        og_img = soup.find("meta", property="og:image")
        og_alt = soup.find("meta", property="og:image:alt")
        og_caption = clean_caption_text(og_alt["content"]) if (og_alt and og_alt.get("content")) else ""
        if og_img and og_img.get("content"):
            try_add_image(og_img["content"], caption=og_caption, skip_size_check=True)

        if not images and feed_img:
            try_add_image(feed_img, skip_size_check=True)

        # 2. 순수 기사 본문 영역 스캔 (동일한 1번 이미지의 본문 캡션도 여기서 자동 매칭됨)
        article_elem = (
            soup.find("div", id=re.compile(r"article-view-content-div|articleBody|news_body_area", re.I))
            or soup.find("div", class_=re.compile(r"article-body|entry-content|post-content|view-content|content-body", re.I))
            or soup.find("article")
        )

        if article_elem:
            scan_container_images(article_elem)

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

def generate_article_content(api_key, source, category, original_title, raw_text, images=None):
    client = genai.Client(api_key=api_key, http_options={"timeout": 60000})

    # 영문 등 외국어 캡션이 있는 이미지만 추출해 번역 요청 목록 구성
    caption_lines = []
    if images:
        for idx, img in enumerate(images):
            cap = img.get("caption", "").strip() if isinstance(img, dict) else ""
            if cap and re.search(r"[a-zA-Z]{3,}", cap):
                caption_lines.append(f"{idx}: {cap}")

    caption_instruction = ""
    if caption_lines:
        joined_caps = "\n".join(caption_lines)
        caption_instruction = f"""

[이미지 캡션 한국어 요약 번역 대상]
{joined_caps}

7. 위 [이미지 캡션 한국어 요약 번역 대상]에 있는 영문 사진 설명을 자동차 매거진 사진 캡션에 어울리는 간결한 한국어 명사구(15~25자 내외, 예: '2027년형 애스턴마틴 발할라 전면부 모습')로 번역하여, 기사 본문이 모두 끝난 맨 마지막 줄 아래에 아래 형식으로만 출력하세요.
[IMG_CAPTIONS]
번호: 한국어 캡션
[/IMG_CAPTIONS]
"""

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
6. 본문 문단에는 `#` 기호나 굵은 마크다운 제목을 쓰지 말고 순수 텍스트 문장으로만 작성하세요.{caption_instruction}
"""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            interaction = client.interactions.create(
                model=config.GEMINI_MODEL,
                input=prompt
            )
            return interaction.output_text.strip()
        except Exception as e:
            print(f"Gemini API 에러 (시도 {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                wait_sec = 2 * (attempt + 1)
                print(f"{wait_sec}초 후 Gemini API 재시도...")
                time.sleep(wait_sec)
    print("Gemini API 최대 재시도 초과로 해당 기사를 건너뜁니다.")
    return None
