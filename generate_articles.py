import json
import os
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
from openai import OpenAI
from pydantic import BaseModel


# CNBC 공식 Top News RSS
CNBC_RSS_URL = (
    "https://www.cnbc.com/id/100003114/"
    "device/rss/rss.html"
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


def get_korea_today():
    return datetime.now(
        ZoneInfo("Asia/Seoul")
    )


def get_today_topic():
    weekday = get_korea_today().weekday()

    topics = {
        0: "Business",
        1: "Travel",
        2: "AI",
        3: "Food",
        4: "Economy",
        5: "Culture",
        6: "Weekly Review",
    }

    return topics[weekday]


def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def pick_article():
    feed = feedparser.parse(CNBC_RSS_URL)

    if feed.bozo and not feed.entries:
        raise RuntimeError(
            "CNBC RSS를 불러오지 못했습니다."
        )

    if not feed.entries:
        raise RuntimeError(
            "CNBC RSS에 기사가 없습니다."
        )

    topic = get_today_topic()

    keywords = {
        "Business": [
            "business",
            "company",
            "retail",
            "earnings",
            "ceo",
        ],
        "Travel": [
            "travel",
            "airline",
            "hotel",
            "tourism",
            "flight",
        ],
        "AI": [
            "ai",
            "artificial intelligence",
            "technology",
            "tech",
            "openai",
        ],
        "Food": [
            "food",
            "restaurant",
            "coffee",
            "consumer",
            "grocery",
        ],
        "Economy": [
            "economy",
            "inflation",
            "interest rate",
            "fed",
            "jobs",
            "market",
        ],
        "Culture": [
            "culture",
            "media",
            "entertainment",
            "sports",
            "lifestyle",
        ],
    }

    if topic == "Weekly Review":
        candidates = feed.entries[:15]
    else:
        topic_keywords = keywords.get(topic, [])

        candidates = []

        for entry in feed.entries[:30]:
            combined_text = (
                f"{entry.get('title', '')} "
                f"{entry.get('summary', '')}"
            ).lower()

            if any(
                keyword in combined_text
                for keyword in topic_keywords
            ):
                candidates.append(entry)

        if not candidates:
            candidates = feed.entries[:10]

    article = random.choice(candidates[:10])

    title = article.get("title", "").strip()
    link = article.get("link", "").strip()

    published = (
        article.get("published", "")
        or article.get("updated", "")
    )

    description = clean_html(
        article.get("summary", "")
    )

    if not title or not link:
        raise RuntimeError(
            "선택된 기사에 제목 또는 링크가 없습니다."
        )

    if "cnbc.com" not in link:
        raise RuntimeError(
            "선택된 링크가 CNBC 링크가 아닙니다."
        )

    return {
        "title": title,
        "link": link,
        "published": published,
        "description": description,
        "topic": topic,
    }


def generate_study_material(article):
    raw_api_key = os.environ.get(
        "OPENROUTER_API_KEY",
        ""
    )

    # GitHub Secret에 포함될 수 있는 줄바꿈, 탭,
    # 따옴표, Bearer 접두어를 제거
    api_key = "".join(raw_api_key.split())

    api_key = api_key.strip('"').strip("'")

    if api_key.lower().startswith("bearer"):
        api_key = api_key[6:].strip()

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY가 비어 있습니다."
        )

    if not api_key.startswith("sk-or-"):
        raise RuntimeError(
            "OPENROUTER_API_KEY 형식이 올바르지 않습니다. "
            "OpenRouter 키 자체만 Secret에 등록하세요."
        )

    print(
        "OpenRouter 키 확인 완료:",
        f"길이={len(api_key)}, "
        f"시작={api_key[:6]}..."
    )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

def save_today_news(article, study):
    today = get_korea_today()

    output = {
        "title": article["title"],
        "date": today.strftime("%Y-%m-%d"),
        "link": article["link"],
        "summary": study.summary,
        "vocab": [
            item.model_dump()
            for item in study.vocab
        ],
        "shadowing": study.shadowing,
        "quizzes": [
            item.model_dump()
            for item in study.quizzes
        ],
        "rephraseTarget": [
            item.model_dump()
            for item in study.rephraseTarget
        ],
    }

    with open(
        "today_news.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("today_news.json 생성 완료")
    print(f"제목: {article['title']}")
    print(f"링크: {article['link']}")


def main():
    article = pick_article()

    print(f"오늘의 주제: {article['topic']}")
    print(f"선택 기사: {article['title']}")
    print(f"실제 링크: {article['link']}")

    study = generate_study_material(article)
    save_today_news(article, study)


if __name__ == "__main__":
    main()
