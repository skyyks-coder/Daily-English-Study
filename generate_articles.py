import json
import os
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
from openai import OpenAI
from pydantic import BaseModel

CNBC_RSS_URL = "https://www.cnbc.com/id/100003114/device/rss/rss.html"


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
    return datetime.now(ZoneInfo("Asia/Seoul"))


def get_today_topic():
    topics = {
        0: "Business",
        1: "Travel",
        2: "AI",
        3: "Food",
        4: "Economy",
        5: "Culture",
        6: "Weekly Review",
    }
    return topics[get_korea_today().weekday()]


def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def pick_article():
    feed = feedparser.parse(CNBC_RSS_URL)
    if feed.bozo and not feed.entries:
        raise RuntimeError("CNBC RSS를 불러오지 못했습니다.")
    if not feed.entries:
        raise RuntimeError("CNBC RSS에 기사가 없습니다.")

    topic = get_today_topic()
    keywords = {
        "Business": ["business", "company", "retail", "earnings", "ceo", "sales"],
        "Travel": ["travel", "airline", "hotel", "tourism", "flight", "airport"],
        "AI": ["ai", "artificial intelligence", "technology", "tech", "openai", "nvidia"],
        "Food": ["food", "restaurant", "coffee", "consumer", "grocery", "beverage"],
        "Economy": ["economy", "inflation", "interest rate", "fed", "jobs", "market"],
        "Culture": ["culture", "media", "entertainment", "sports", "lifestyle", "film"],
    }

    if topic == "Weekly Review":
        candidates = list(feed.entries[:15])
    else:
        candidates = []
        for entry in feed.entries[:30]:
            combined = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
            if any(word in combined for word in keywords.get(topic, [])):
                candidates.append(entry)
        if not candidates:
            candidates = list(feed.entries[:10])

    if not candidates:
        raise RuntimeError("선택 가능한 CNBC 기사가 없습니다.")

    article = random.choice(candidates[:10])
    title = article.get("title", "").strip()
    link = article.get("link", "").strip()
    published = article.get("published", "") or article.get("updated", "")
    description = clean_html(article.get("summary", "")) or title

    if not title or not link:
        raise RuntimeError("선택된 기사에 제목 또는 링크가 없습니다.")
    if "cnbc.com" not in link.lower():
        raise RuntimeError("선택된 링크가 CNBC 링크가 아닙니다.")

    return {
        "title": title,
        "link": link,
        "published": published,
        "description": description,
        "topic": topic,
    }


def generate_study_material(article):
    raw_api_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_key = "".join(raw_api_key.split()).strip('"').strip("'")
    if api_key.lower().startswith("bearer"):
        api_key = api_key[6:].strip()

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY가 비어 있습니다.")
    if not api_key.startswith("sk-or-"):
        raise RuntimeError("OPENROUTER_API_KEY 형식이 올바르지 않습니다.")

    print(f"OpenRouter 키 확인 완료: 길이={len(api_key)}, 시작={api_key[:6]}...")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    prompt = f"""
Create English study material based only on this CNBC RSS article information.

Topic: {article['topic']}
Title: {article['title']}
Published: {article['published']}
Description: {article['description']}
Original URL: {article['link']}

Return one valid JSON object with exactly this structure:
{{
  "summary": "3 to 5 sentence CEFR C1 summary",
  "vocab": [{{"word": "English word", "meaning": "Natural Korean meaning"}}],
  "shadowing": ["English sentence"],
  "quizzes": [
    {{
      "question": "English question",
      "options": ["Option 1", "Option 2", "Option 3"],
      "answer": 0
    }}
  ],
  "rephraseTarget": [
    {{"original": "Original sentence", "ai_suggestion": "Suggested rephrasing"}}
  ]
}}

Requirements:
- Exactly 5 vocabulary items with Korean meanings.
- Exactly 5 shadowing sentences.
- Exactly 3 quizzes, each with exactly 3 options.
- Quiz answer is the zero-based correct index: 0, 1, or 2.
- Exactly 2 rephrasing exercises.
- Use only the supplied article information. Do not invent facts.
- Output JSON only. Do not use Markdown fences.
"""

    print("OpenRouter에 학습 자료 생성을 요청합니다.")
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Create accurate English-learning materials. Return valid JSON only and never invent facts.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )

    raw_content = response.choices[0].message.content
    if not raw_content:
        raise RuntimeError("OpenRouter가 빈 응답을 반환했습니다.")

    try:
        result = StudyMaterial.model_validate(json.loads(raw_content))
    except Exception as error:
        print("OpenRouter 원본 응답:")
        print(raw_content)
        raise RuntimeError(f"AI 응답 JSON 처리 실패: {error}") from error

    if len(result.vocab) != 5:
        raise RuntimeError("Vocabulary가 정확히 5개가 아닙니다.")
    if len(result.shadowing) != 5:
        raise RuntimeError("Shadowing 문장이 정확히 5개가 아닙니다.")
    if len(result.quizzes) != 3:
        raise RuntimeError("Quiz가 정확히 3개가 아닙니다.")
    if len(result.rephraseTarget) != 2:
        raise RuntimeError("Rephrasing이 정확히 2개가 아닙니다.")

    for quiz_number, quiz in enumerate(result.quizzes, start=1):
        if len(quiz.options) != 3:
            raise RuntimeError(f"Quiz {quiz_number}의 보기가 정확히 3개가 아닙니다.")
        if quiz.answer not in (0, 1, 2):
            raise RuntimeError(f"Quiz {quiz_number}의 정답 번호가 올바르지 않습니다.")

    print("AI 학습 자료 생성 완료")
    return result


def save_today_news(article, study):
    output = {
        "title": article["title"],
        "date": get_korea_today().strftime("%Y-%m-%d"),
        "link": article["link"],
        "summary": study.summary,
        "vocab": [item.model_dump() for item in study.vocab],
        "shadowing": list(study.shadowing),
        "quizzes": [item.model_dump() for item in study.quizzes],
        "rephraseTarget": [item.model_dump() for item in study.rephraseTarget],
    }

    with open("today_news.json", "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    with open("today_news.json", "r", encoding="utf-8") as file:
        validated = json.load(file)

    if len(validated.get("quizzes", [])) != 3:
        raise RuntimeError("생성된 JSON의 Quiz 개수가 3개가 아닙니다.")

    print("today_news.json 생성 완료")
    print(f"제목: {article['title']}")
    print(f"링크: {article['link']}")


def main():
    article = pick_article()
    print(f"오늘의 주제: {article['topic']}")
    print(f"선택 기사: {article['title']}")
    print(f"실제 링크: {article['link']}")

    study = generate_study_material(article)
    if study is None:
        raise RuntimeError("generate_study_material 함수가 결과를 반환하지 않았습니다.")

    save_today_news(article, study)
    print("모든 작업이 정상적으로 완료되었습니다.")


if __name__ == "__main__":
    main()
