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
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다."
        )

    client = OpenAI(api_key=api_key)

    prompt = f"""
Create English study material based only on the
CNBC RSS article information below.

Topic: {article["topic"]}
Title: {article["title"]}
Published: {article["published"]}
Description: {article["description"]}
Original URL: {article["link"]}

Requirements:

1. Write a CEFR C1 English summary in 3 to 5 sentences.
2. Provide exactly 5 vocabulary items.
3. Korean meanings must be natural and concise.
4. Provide exactly 5 shadowing sentences.
5. Shadowing sentences must be based only on the article.
6. Provide exactly 3 comprehension quizzes.
7. Each quiz must have exactly 3 options.
8. The answer must be the correct zero-based option index:
   0, 1, or 2.
9. Provide exactly 2 rephrasing exercises.
10. Do not add facts not present in the supplied article data.
"""

    response = client.responses.parse(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "You create accurate English-learning "
                    "materials. Never invent article facts."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        text_format=StudyMaterial,
    )

    result = response.output_parsed

    if result is None:
        raise RuntimeError(
            "학습 자료를 생성하지 못했습니다."
        )

    if len(result.vocab) != 5:
        raise RuntimeError(
            "Vocabulary가 5개가 아닙니다."
        )

    if len(result.shadowing) != 5:
        raise RuntimeError(
            "Shadowing 문장이 5개가 아닙니다."
        )

    if len(result.quizzes) != 3:
        raise RuntimeError(
            "Quiz가 3개가 아닙니다."
        )

    for quiz in result.quizzes:
        if len(quiz.options) != 3:
            raise RuntimeError(
                "Quiz 보기가 3개가 아닙니다."
            )

        if quiz.answer not in [0, 1, 2]:
            raise RuntimeError(
                "Quiz 정답 번호가 잘못되었습니다."
            )

    return result


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
