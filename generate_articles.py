# -*- coding: utf-8 -*-
"""Daily English Study article generator."""

import html
import json
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from openai import OpenAI
from pydantic import BaseModel, field_validator

CNBC_RSS_URLS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "https://www.cnbc.com/id/15837362/device/rss/rss.html",
    "https://www.cnbc.com/id/20409666/device/rss/rss.html?x=1",
]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ARCHIVE_DIR = Path("articles")
TODAY_FILE = Path("today_news.json")
REQUEST_TIMEOUT = 20
MAX_RSS_ENTRIES = 60
MAX_PUBLIC_CANDIDATES = 20

BLOCKED_URL_KEYWORDS = (
    "/investingclub/", "/investing-club/", "/cnbc-pro/", "/pro/", "/club/",
    "cnbc.com/pro", "cnbc.com/investingclub", "cnbc.com/investing-club",
)
BLOCKED_RSS_KEYWORDS = (
    "cnbc pro", "cnbc investing club", "investing club", "pro subscribers",
    "club members", "members only", "subscriber only", "subscription required",
)
BLOCKED_PAGE_PATTERNS = (
    r'"isAccessibleForFree"\s*:\s*false',
    r'"isAccessibleForFree"\s*:\s*"false"',
    r'"accessibilityForFree"\s*:\s*false',
    r'"premium"\s*:\s*true',
    r'"isPremium"\s*:\s*true',
    r'"contentClassification"\s*:\s*"(?:PRO|CLUB|PREMIUM)"',
    r'"contentTier"\s*:\s*"(?:PRO|CLUB|PREMIUM|PAID)"',
    r'sign\s+in\s+to\s+(?:continue|read)\s+(?:this|the)\s+article',
    r'subscribe\s+to\s+(?:continue|read)\s+(?:this|the)\s+article',
)
PUBLIC_ARTICLE_PATTERNS = (
    r'"@type"\s*:\s*"(?:NewsArticle|Article)"',
    r'"articleBody"\s*:',
    r'property=["\']og:type["\']\s+content=["\']article["\']',
    r'class=["\'][^"\']*article-body',
)


class VocabularyItem(BaseModel):
    word: str
    meaning: str


class QuizItem(BaseModel):
    question: str
    options: list[str]
    answer: int


class RephraseItem(BaseModel):
    original: str
    ai_suggestion: str


class StudyMaterial(BaseModel):
    summary: str
    vocab: list[VocabularyItem]
    shadowing: list[str]
    quizzes: list[QuizItem]
    rephraseTarget: list[RephraseItem]

    @field_validator("rephraseTarget", mode="before")
    @classmethod
    def normalize_rephrase_target(cls, value):
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                normalized.append({"original": text, "ai_suggestion": text})
            elif isinstance(item, dict):
                original = str(item.get("original") or item.get("sentence") or item.get("text") or "").strip()
                suggestion = str(item.get("ai_suggestion") or item.get("suggestion") or item.get("rephrased") or original).strip()
                normalized.append({"original": original, "ai_suggestion": suggestion})
            else:
                normalized.append(item)
        return normalized


def get_korea_today():
    return datetime.now(ZoneInfo("Asia/Seoul"))


def get_today_topic():
    return {0: "Business", 1: "Travel", 2: "AI", 3: "Food", 4: "Economy", 5: "Culture", 6: "Weekly Review"}[get_korea_today().weekday()]


def clean_html(text):
    text = html.unescape(str(text or ""))
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<[^>]+>", " ", text, flags=re.I | re.S)
    return re.sub(r"\s+", " ", text).strip()


def is_blocked_cnbc_url(url):
    normalized = str(url or "").strip().lower()
    return not normalized or "cnbc.com" not in normalized or any(k in normalized for k in BLOCKED_URL_KEYWORDS)


def has_blocked_page_signal(text):
    return next((p for p in BLOCKED_PAGE_PATTERNS if re.search(p, text, re.I | re.S)), None)


def has_public_article_signal(text):
    return any(re.search(p, text, re.I | re.S) for p in PUBLIC_ARTICLE_PATTERNS)


def is_public_cnbc_article(entry):
    title = str(entry.get("title", "")).strip()
    link = str(entry.get("link", "")).strip()
    summary = clean_html(entry.get("summary", "") or entry.get("description", "")).lower()
    if not title or is_blocked_cnbc_url(link):
        return False
    if any(k in f"{title.lower()} {summary}" for k in BLOCKED_RSS_KEYWORDS):
        return False
    try:
        response = requests.get(link, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.RequestException as error:
        print(f"기사 연결 실패: {error}")
        return False
    page_html = response.text or ""
    blocked = has_blocked_page_signal(page_html)
    if response.status_code != 200 or is_blocked_cnbc_url(response.url) or len(page_html) < 5000:
        return False
    if blocked:
        print(f"제외: 유료 신호 {blocked}")
        return False
    if not has_public_article_signal(page_html):
        print(f"제외: 공개 기사 구조 미확인 -> {response.url}")
        return False
    entry["link"] = response.url
    print(f"공개 기사 확인 완료: {title}")
    return True


def fetch_cnbc_rss_entries():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36", "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.7", "Referer": "https://www.cnbc.com/"}
    entries, seen = [], set()
    for url in CNBC_RSS_URLS:
        for attempt in range(1, 4):
            try:
                print(f"CNBC RSS 요청: {url} (시도 {attempt}/3)")
                response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
                print(f"CNBC RSS 응답: {response.status_code} {len(response.content)}")
                response.raise_for_status()
                feed = feedparser.parse(response.content)
                for entry in feed.entries:
                    title = str(entry.get("title", "")).strip()
                    link = str(entry.get("link", "")).strip()
                    if title and link and link not in seen:
                        seen.add(link)
                        entries.append(entry)
                break
            except requests.RequestException as error:
                print(f"RSS 요청 실패: {error}")
                if attempt < 3:
                    time.sleep(attempt * 3)
        if len(entries) >= MAX_RSS_ENTRIES:
            break
    print(f"CNBC RSS 최종 수집 기사: {len(entries)}")
    return entries


def get_topic_candidates(entries, topic):
    keywords = {
        "Business": ["business", "company", "retail", "earnings", "ceo", "sales"],
        "Travel": ["travel", "airline", "hotel", "tourism", "flight", "airport"],
        "AI": ["ai", "artificial intelligence", "technology", "tech", "openai", "nvidia"],
        "Food": ["food", "restaurant", "coffee", "consumer", "grocery", "beverage"],
        "Economy": ["economy", "inflation", "interest rate", "fed", "jobs", "market"],
        "Culture": ["culture", "media", "entertainment", "sports", "lifestyle", "film"],
    }
    found = []
    for entry in entries:
        text = clean_html(f"{entry.get('title', '')} {entry.get('summary', '') or entry.get('description', '')}").lower()
        if any(keyword in text for keyword in keywords.get(topic, [])):
            found.append(entry)
    return found or list(entries[:15])


def select_public_article(candidates):
    pool = list(candidates)
    random.shuffle(pool)
    for number, entry in enumerate(pool[:MAX_PUBLIC_CANDIDATES], 1):
        print(f"후보 {number}: {entry.get('title', '')}")
        if is_public_cnbc_article(entry):
            return entry
    raise RuntimeError("후보 기사 중 공개 CNBC 기사를 찾지 못했습니다.")


def pick_article():
    entries = fetch_cnbc_rss_entries()
    if not entries:
        raise RuntimeError("모든 CNBC RSS 주소에서 기사를 불러오지 못했습니다.")
    topic = get_today_topic()
    candidates = get_topic_candidates(entries, topic)
    try:
        article = select_public_article(candidates)
    except RuntimeError:
        used = {str(entry.get("link", "")) for entry in candidates}
        article = select_public_article([entry for entry in entries if str(entry.get("link", "")) not in used])
    title = str(article.get("title", "")).strip()
    link = str(article.get("link", "")).strip()
    published = article.get("published", "") or article.get("updated", "")
    description = clean_html(article.get("summary", "") or article.get("description", "")) or title
    if not title or not link:
        raise RuntimeError("선택된 기사 정보가 올바르지 않습니다.")
    return {"title": title, "link": link, "published": published, "description": description, "topic": topic}


def create_client():
    key = "".join(os.environ.get("OPENROUTER_API_KEY", "").split()).strip('"').strip("'")
    if not key.startswith("sk-or-"):
        raise RuntimeError("OPENROUTER_API_KEY가 없거나 형식이 올바르지 않습니다.")
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=key)


def requirements_text():
    return (
        "Return one JSON object with keys summary, vocab, shadowing, quizzes, rephraseTarget. "
        "summary must be 3-5 CEFR C1 sentences. vocab must contain exactly 5 objects with word and meaning, using Korean meanings. "
        "shadowing must contain exactly 5 strings. quizzes must contain exactly 3 objects with question, options, answer; each options list has exactly 3 strings and answer is 0, 1, or 2. "
        "rephraseTarget must contain exactly 2 objects, never strings. Every rephraseTarget object must contain original and ai_suggestion. Do not invent facts. JSON only."
    )


def request_material(prompt, label, temperature):
    response = create_client().chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "system", "content": "Return accurate English study material as valid JSON only and follow the schema exactly."}, {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError(f"{label}: OpenRouter 응답이 비어 있습니다.")
    try:
        material = StudyMaterial.model_validate(json.loads(raw))
    except Exception as error:
        print(f"{label} OpenRouter 원본 응답:")
        print(raw)
        raise RuntimeError(f"{label}: AI 응답 검증 실패: {error}") from error
    if len(material.vocab) != 5 or len(material.shadowing) != 5 or len(material.quizzes) != 3 or len(material.rephraseTarget) != 2:
        raise RuntimeError(f"{label}: 학습 자료 항목 수가 요구사항과 다릅니다.")
    for quiz in material.quizzes:
        if len(quiz.options) != 3 or quiz.answer not in (0, 1, 2):
            raise RuntimeError(f"{label}: Quiz 형식이 올바르지 않습니다.")
    return material


def generate_study_material(article):
    return request_material(f"Create material only from: {json.dumps(article, ensure_ascii=False)}\n{requirements_text()}", "Daily Article", 0.4)


def load_weekly_articles():
    today = get_korea_today()
    items = []
    for days_back in range(6, 0, -1):
        path = ARCHIVE_DIR / f"{today - timedelta(days=days_back):%Y-%m-%d}.json"
        if path.exists():
            item = json.loads(path.read_text(encoding="utf-8"))
            if not item.get("isWeeklyReview"):
                items.append(item)
    if not items and TODAY_FILE.exists():
        items = [json.loads(TODAY_FILE.read_text(encoding="utf-8"))]
    if not items:
        raise RuntimeError("Weekly Review 자료가 없습니다.")
    return items


def generate_weekly_review(items):
    article = {"topic": "Weekly Review", "title": "Weekly English Review", "published": f"{get_korea_today():%Y-%m-%d}", "description": "", "link": ""}
    material = request_material(f"Create weekly review from {json.dumps(items, ensure_ascii=False)}\n{requirements_text()}", "Weekly Review", 0.3)
    return article, material


def save_today_news(article, study, is_weekly_review=False):
    output = {
        "title": article["title"], "date": f"{get_korea_today():%Y-%m-%d}", "link": article["link"], "isWeeklyReview": is_weekly_review,
        "summary": study.summary, "vocab": [item.model_dump() for item in study.vocab], "shadowing": list(study.shadowing),
        "quizzes": [item.model_dump() for item in study.quizzes], "rephraseTarget": [item.model_dump() for item in study.rephraseTarget],
    }
    TODAY_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if not is_weekly_review:
        ARCHIVE_DIR.mkdir(exist_ok=True)
        (ARCHIVE_DIR / f"{output['date']}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("today_news.json 생성 완료")


def main():
    if get_korea_today().weekday() == 6:
        article, study = generate_weekly_review(load_weekly_articles())
        save_today_news(article, study, True)
    else:
        article = pick_article()
        print(f"선택 기사: {article['title']}")
        save_today_news(article, generate_study_material(article), False)
    print("모든 작업이 정상적으로 완료되었습니다.")


if __name__ == "__main__":
    main()
