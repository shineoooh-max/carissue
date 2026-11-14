# config.py - CARISSUE 고정 설정 및 상수 관리 파일

SITE_URL = "https://carissue.koo1000.com"
SITE_NAME = "CARISSUE"
POSTS_DIR = "posts"
TEMPLATES_DIR = "templates"
INDEX_PATH = "index.html"
SITEMAP_PATH = "sitemap.xml"
HISTORY_FILE = "published_links.txt"
META_DB_PATH = "posts_meta.json"

# Gemini 모델 설정
GEMINI_MODEL = "gemini-3.8-flash"

# 구글 애드센스 고정 슬롯 번호
ADSENSE_CLIENT = "ca-pub-4793184080983542"
AD_SLOTS = {
    "in_article": "4181249863",  # 본문 중간
    "sidebar": "5924062639",     # 우측 고정 사이드바 (300x600)
    "bottom": "9203364457",      # 하단 디스플레이
    "multiplex": "3913014950"    # 하단 멀티플렉스
}

# 수집 대상 RSS 피드 (오전: 국내 총 5개 / 오후: 글로벌 총 5개)
FEEDS_MORNING = [
    {
        "name": "오토헤럴드",
        "category": "국내 이슈",
        "url": "http://www.autoherald.co.kr/rss/allArticle.xml",
        "target_count": 2
    },
    {
        "name": "모터그래프",
        "category": "국내 이슈",
        "url": "https://www.motorgraph.com/rss/allArticle.xml",
        "target_count": 2
    },
    {
        "name": "카가이",
        "category": "국내 이슈",
        "url": "https://www.carguy.kr/rss/allArticle.xml",
        "target_count": 1
    }
]

FEEDS_EVENING = [
    {
        "name": "Carscoops",
        "category": "글로벌 뉴스",
        "url": "https://www.carscoops.com/feed/",
        "target_count": 2
    },
    {
        "name": "Motor1",
        "category": "글로벌 뉴스",
        "url": "https://www.motor1.com/rss/news/all/",
        "target_count": 1
    },
    {
        "name": "InsideEVs",
        "category": "글로벌 뉴스",
        "url": "https://insideevs.com/rss/news/all/",
        "target_count": 1
    },
    {
        "name": "Car and Driver",
        "category": "글로벌 뉴스",
        "url": "https://www.caranddriver.com/rss/all.xml/",
        "target_count": 1
    }
]
