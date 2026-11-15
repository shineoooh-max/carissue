# parser.py - RSS 수집, 다중 고화질 이미지 추출, Gemini 기사 생성 전용 모듈
import os
import re
import struct
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


def extract_best_from_srcset(srcset_val):
    """URL 내부 콤마(Hearst CDN crop 파라미터 등)를 보호하면서 가장 큰 해상도 URL 추출"""
    if not srcset_val:
        return ""
    candidates = [c.strip() for c in re.split(r",\s*(?=https?://|/)", srcset_val) if c.strip()]
    if not candidates:
        return ""
    return candidates[-1].split()[0]


def get_img_fingerprint(img_url):
    """쿼리스트링 기반 CDN(Car and Driver 등)과 파일명 기반 CDN 모두 정확히 구분"""
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
    """실제 이미지 파일의 앞부분(헤더)만 빠르게 읽어 가로 해상도가 450px 이상인지 검증"""
    try:
        req = urllib.request.Request(
            img_url,
            headers={"User-Agent": USER_AGENT, "Range": "bytes=0-32768"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read(32768)

        # PNG 헤더 파싱
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return w >= min_width and h >= 220

        # JPEG SOF 마커 파싱
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

        # WebP 헤더 파싱
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            chunk = data[12:16]
            if chunk == b"VP8X" and len(data) >= 30:
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return w >= min_width and h >= 220

        # 헤더 파싱이 어려운 CDN 응답은 최소 용량(15KB 이상)으로 1차 방어
        return len(data) >= 15360
    except Exception:
        return False


def decode_html_bytes(raw_bytes):
    """UTF-8 및 국내 언론사 CP949/EUC-KR 인코딩 자동 판별 디코딩"""
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="ignore")


def fetch_feed_items(feed_conf, history_set):
    items = []
    target = feed_conf["target_count"]
    print(f"\n[{feed_conf['name']}] RSS 수집 시작 ({feed_conf['category']} - 목표: {target}건)")

    try:
        req = urllib.request.Request(feed_conf["url"], headers={"User-Agent": USER_AGENT})
        raw_data = urllib.request.urlopen(req, timeout=15).read()
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
    images = []
    seen_fps = set()
    text_content = ""
    safe_desc = feed_desc or ""
    is_korean_media = any(domain in url.lower() for domain in ("motorgraph.com", "carguy.kr", "autoherald.co.kr"))

    def try_add_image(raw_src, skip_size_check=False):
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

        # 국내 언론사(모터그래프/카가이/오토헤럴드)는 기사 본문 업로드 경로(/news/photo/) 외 찌꺼기 이미지 원천 차단
        if is_korean_media and "/news/photo/" not in lower_u:
            return

        fp = get_img_fingerprint(full_url)
        if fp and fp in seen_fps:
            return

        # og:image가 아닌 본문 추가 이미지는 실제 가로 450px 이상 고화질만 통과
        if not skip_size_check and not is_valid_large_image(full_url, min_width=450):
            return

        if full_url not in images:
            images.append(full_url)
            if fp:
                seen_fps.add(fp)

    def scan_container_images(container):
        if not container:
            return
        # 1) <picture> 내부 <source srcset="..."> 고화질 원본 우선 수집 (해외 매체 대응)
        for pic in container.find_all("picture"):
            source_tag = pic.find("source")
            if source_tag:
                best_src = extract_best_from_srcset(
                    source_tag.get("data-srcset") or source_tag.get("srcset")
                )
                if best_src:
                    try_add_image(best_src)
                    if len(images) >= 5:
                        return

        # 2) 일반 <img> 태그의 지연 로딩(data-src 등) 및 srcset 수집 (국내/해외 공통)
        for img in container.find_all("img"):
            # 기자 프로필/관련기사/배너 박스 내부에 속한 img 태그 제외
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
            try_add_image(src)
            if len(images) >= 5:
                return

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        raw_bytes = urllib.request.urlopen(req, timeout=15).read()
        html = decode_html_bytes(raw_bytes)
        soup = BeautifulSoup(html, "html.parser")

        # 1. og:image 메타 태그를 1순위 대표 이미지로 추출
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            try_add_image(og_img["content"], skip_size_check=True)

        # 2. og:image가 없을 때만 feed_img 보조 활용
        if not images and feed_img:
            try_add_image(feed_img, skip_size_check=True)

        # 3. 순수 기사 본문 영역만 정확히 타겟팅 (전체 <article>이나 페이지 전체 스캔 제거)
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
