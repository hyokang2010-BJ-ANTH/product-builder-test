"""공통 설정 및 유틸리티."""
import json
import os
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PWA_DATA_DIR = os.path.join(ROOT, "pwa", "data")
ASSETS_DIR = os.path.join(ROOT, "assets")
TEMPLATES_DIR = os.path.join(ROOT, "templates")
USED_TOPICS_PATH = os.path.join(DATA_DIR, "used_topics.json")

KST = timezone(timedelta(hours=9))

# 검색 키워드 (한글/영문 혼합 — 논문은 영문 DB, 뉴스는 한글 위주)
#
# 주의: 예전에는 "scalp"를 단독 키워드로 넣었는데, 두피 백선(무좀균) 진단법 논문처럼
# 탈모와 무관한 연구까지 끌려와서 제외했다. 대신 탈모/모발에 특이적인 용어를 나열한다.
PUBMED_QUERY = (
    '(alopecia[Title/Abstract] OR "hair loss"[Title/Abstract] '
    'OR "hair transplant"[Title/Abstract] OR "hair transplantation"[Title/Abstract] '
    'OR "hair restoration"[Title/Abstract] OR "hair regrowth"[Title/Abstract] '
    'OR "hair growth"[Title/Abstract] OR "hair follicle"[Title/Abstract] '
    'OR "hair density"[Title/Abstract] OR "follicular unit"[Title/Abstract] '
    'OR minoxidil[Title/Abstract] OR finasteride[Title/Abstract] '
    'OR dutasteride[Title/Abstract] OR baldness[Title/Abstract]) '
    'AND ("last 30 days"[PDat])'
)

# 논문이 실제로 탈모/모발 주제인지 판정할 때 쓰는 핵심 키워드.
# 제목에 하나라도 있으면 확실한 주제로 본다.
RELEVANCE_KEYWORDS = [
    "alopecia",
    "hair",
    "follicul",
    "follicle",
    "minoxidil",
    "finasteride",
    "dutasteride",
    "baldness",
    "tricholog",
]
NEWS_QUERIES = ["탈모 치료", "모발이식", "탈모 신약", "모발 연구"]

WIKIMEDIA_TOPIC_KEYWORDS = [
    "hair loss",
    "hair transplant surgery",
    "scalp",
    "dermatology hair",
]


def today_kst():
    return datetime.now(KST)


def today_str():
    return today_kst().strftime("%Y-%m-%d")


def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    ensure_dirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def day_dir(date_str=None):
    date_str = date_str or today_str()
    d = os.path.join(DATA_DIR, date_str)
    ensure_dirs(d, os.path.join(d, "images"))
    return d
