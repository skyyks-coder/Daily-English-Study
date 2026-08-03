import html
import json
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from openai import OpenAI
from pydantic import BaseModel


# =========================================================
# 기본 설정
# =========================================================

# 기존에 사용하던 CNBC RSS 주소를 여기에 넣으세요.
CNBC_RSS_URL = "여기에_기존_CNBC_RSS_URL"

# OpenRouter 공식 API Base URL
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

ARCHIVE_DIR = Path("articles")
TODAY_FILE = Path("today_news.json")

REQUEST_TIMEOUT = 20
MAX_RSS_ENTRIES = 40
MAX_PUBLIC_CANDIDATES = 15


# =========================================================
# CNBC 유료, Club, Pro 기사 필터 설정
# =========================================================

# URL에 아래 경로가 있으면 바로 제외합니다.
BLOCKED_URL_KEYWORDS = (
    "/investingclub/",
    "/investing-club/",
    "/cnbc-pro/",
    "/pro/",
    "/club/",
    "cnbc.com/pro",
    "cnbc.com/investingclub",
    "cnbc.com/investing-club",
)

# RSS 제목 또는 설명에 아래 문구가 있으면 제외합니다.
BLOCKED_RSS_KEYWORDS = (
    "cnbc pro",
    "cnbc investing club",
    "investing club",
    "pro subscribers",
    "club members",
    "members only",
    "subscriber only",
    "subscription required",
)

# 페이지 소스에서 확인할 강한 유료 콘텐츠 신호입니다.
# 단순히 sign in이라는 단어 하나만으로 제외하지 않습니다.
BLOCKED_PAGE_PATTERNS = (
    r'"isAccessibleForFree"\s*:\s*false',
    r'"isAccessibleForFree"\s*:\s*"false"',
    r'"accessibilityForFree"\s*:\s*false',
    r'"premium"\s*:\s*true',
    r'"isPremium"\s*:\s*true',
    r'"contentClassification"\s*:\s*"(?:PRO|CLUB|PREMIUM)"',
    r'"contentTier"\s*:\s*"(?:PRO|CLUB|PREMIUM|PAID)"',
    r'"articleSection"\s*:\s*"(?:CNBC Pro|Investing Club|CNBC Investing Club)"',
    r'<meta?:CNBC Pro|Investing Club|CNBC Investing Club["\'][^>]*>',
    r'<meta?:CNBC Pro|Investing Club|CNBC Investing Club["\']',
    r'sign\s+in\s+to\s+(?:continue|read)\s+(?:this|the)\s+article',
    r'subscribe\s+to\s+(?:continue|read)\s+(?:this|the)\s+article',
    r'this\s+article\s+is\s+for\s+(?:club\s+members|pro\s+subscribers)',
    r'available\s+exclusively\s+to\s+(?:club\s+members|pro\s+subscribers)',
    r'join\s+the\s+cnbc\s+investing\s+club\s+to\s+(?:continue|read)',
)

# 공개 기사임을 확인하는 페이지 구조 신호입니다.
PUBLIC_ARTICLE_PATTERNS = (
    r'"@type"\s*:\s*"(?:NewsArticle|Article)"',
    r'"articleBody"\s*:',
    r'property=["\']og:type["\']\s+content=["\']article["\']',
    r'content=["\']article["\']\s+property=["\']og:type["\']',
    r'class=["\'][^"\']*ArticleBody-articleBody',
    r'class=["\'][^"\']*article-body',
)


# =========================================================
# 데이터 모델
# =========================================================

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


# =========================================================
# 날짜 및 주제
# =========================================================

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


# =========================================================
# 문자열 및 HTML 정리
# =========================================================

def clean_html(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_text(value):
    return clean_html(value).lower().strip()


def normalize_url(url):
    return str(url or "").strip().lower()


# =========================================================
# CNBC 공개 기사 확인
# =========================================================

def is_blocked_cnbc_url(url):
    """
    URL 구조만으로 Club, Investing Club, Pro 기사인지 확인합니다.
    """
    normalized = normalize_url(url)

    if not normalized:
        return True

    if "cnbc.com" not in normalized:
        return True

    return any(keyword in normalized for keyword in BLOCKED_URL_KEYWORDS)


def contains_blocked_rss_text(title, summary):
    """
    RSS 제목 또는 설명에 Club, Pro, 구독 전용 문구가 있는지 확인합니다.
    """
    combined = f"{normalize_text(title)} {normalize_text(summary)}"

    return any(keyword in combined for keyword in BLOCKED_RSS_KEYWORDS)


def has_blocked_page_signal(page_html):
    """
    페이지 소스에 강한 유료 또는 회원 전용 신호가 있는지 확인합니다.
    """
    for pattern in BLOCKED_PAGE_PATTERNS:
        if re.search(pattern, page_html, flags=re.I | re.S):
            return pattern

    return None


def has_public_article_signal(page_html):
    """
    페이지가 일반 기사 구조를 가지고 있는지 확인합니다.
    """
    return any(
        re.search(pattern, page_html, flags=re.I | re.S)
        for pattern in PUBLIC_ARTICLE_PATTERNS
    )


def is_public_cnbc_article(entry):
    """
    CNBC 기사가 로그인이나 구독 없이 읽을 수 있는 공개 기사인지
    URL, RSS 정보, 실제 페이지 소스를 순서대로 확인합니다.
    """
    title = entry.get("title", "").strip()
    link = entry.get("link", "").strip()
    summary = entry.get("summary", "") or entry.get("description", "")

    if not title or not link:
        print("제외: 제목 또는 링크가 비어 있습니다.")
        return False

    if is_blocked_cnbc_url(link):
        print(f"제외: Club 또는 Pro URL 감지 -> {link}")
        return False

    if contains_blocked_rss_text(title, summary):
        print(f"제외: RSS에서 Club 또는 Pro 문구 감지 -> {title}")
        return False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        response = requests.get(
            link,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as error:
        print(f"제외: 기사 페이지 연결 실패 -> {link}")
        print(f"연결 오류: {error}")
        return False

    final_url = response.url.strip()
    page_html = response.text or ""

    if response.status_code != 200:
        print(
            "제외: 기사 페이지 응답 오류 "
            f"status={response.status_code} -> {link}"
        )
        return False

    if is_blocked_cnbc_url(final_url):
        print(f"제외: Club 또는 Pro 페이지로 이동됨 -> {final_url}")
        return False

    if len(page_html) < 5000:
        print(
            "제외: 기사 페이지 내용이 지나치게 짧습니다. "
            f"HTML 길이={len(page_html)} -> {final_url}"
        )
        return False

    blocked_pattern = has_blocked_page_signal(page_html)

    if blocked_pattern:
        print(f"제외: 로그인, Club 또는 Pro 신호 감지 -> {final_url}")
        print(f"감지 패턴: {blocked_pattern}")
        return False

    if not has_public_article_signal(page_html):
        print(f"제외: 일반 공개 기사 구조를 확인하지 못했습니다 -> {final_url}")
        return False

    print(f"공개 기사 확인 완료: {title}")
    print(f"공개 링크: {final_url}")

    # 리디렉션된 최종 정상 URL을 저장합니다.
    entry["link"] = final_url

    return True


# =========================================================
# 기사 후보 및 선택
# =========================================================

def get_topic_candidates(entries, topic):
    keywords = {
        "Business": [
            "business",
            "company",
            "retail",
            "earnings",
            "ceo",
            "sales",
        ],
        "Travel": [
            "travel",
            "airline",
            "hotel",
            "tourism",
            "flight",
            "airport",
        ],
        "AI": [
            "ai",
            "artificial intelligence",
            "technology",
            "tech",
            "openai",
            "nvidia",
        ],
        "Food": [
            "food",
            "restaurant",
            "coffee",
            "consumer",
            "grocery",
            "beverage",
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
            "film",
        ],
    }

    if topic == "Weekly Review":
        return list(entries[:15])

    candidates = []

    for entry in entries[:MAX_RSS_ENTRIES]:
        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        combined = normalize_text(f"{title} {summary}")

        if any(word in combined for word in keywords.get(topic, [])):
            candidates.append(entry)

    if not candidates:
        print(
            f"{topic} 주제 키워드에 맞는 기사가 없어 "
            "최신 기사 후보를 사용합니다."
        )
        candidates = list(entries[:15])

    return candidates


def select_public_article(candidates):
    """
    후보 순서를 섞은 뒤, 공개 여부를 확인합니다.
    최대 MAX_PUBLIC_CANDIDATES개만 검사합니다.
    """
    candidates = list(candidates)

    if not candidates:
        raise RuntimeError("확인할 기사 후보가 없습니다.")

    random.shuffle(candidates)
    candidates = candidates[:MAX_PUBLIC_CANDIDATES]

    print(f"공개 여부를 확인할 기사 후보: {len(candidates)}개")

    for number, entry in enumerate(candidates, start=1):
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()

        print("")
        print("=" * 60)
        print(f"후보 {number}/{len(candidates)}")
        print(f"기사 제목: {title}")
        print(f"기사 링크: {link}")

        if is_public_cnbc_article(entry):
            print("선택 가능: 공개 CNBC 기사입니다.")
            print("=" * 60)
            return entry

        print("선택 제외: Club, Pro, 로그인 또는 비공개 기사입니다.")
        print("=" * 60)

    raise RuntimeError(
        "후보 기사 중 로그인 없이 전문을 읽을 수 있는 "
        "CNBC 공개 기사를 찾지 못했습니다."
    )


def pick_article():
    feed = feedparser.parse(CNBC_RSS_URL)

    if feed.bozo and not feed.entries:
        raise RuntimeError("CNBC RSS를 불러오지 못했습니다.")

    if not feed.entries:
        raise RuntimeError("CNBC RSS에 기사가 없습니다.")

    topic = get_today_topic()
    candidates = get_topic_candidates(feed.entries, topic)

    if not candidates:
        raise RuntimeError("선택 가능한 CNBC 기사가 없습니다.")

    article = select_public_article(candidates)

    title = article.get("title", "").strip()
    link = article.get("link", "").strip()
    published = article.get("published", "") or article.get("updated", "")
    rss_summary = article.get("summary", "") or article.get("description", "")
    description = clean_html(rss_summary) or title

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


# =========================================================
# OpenRouter 공통 설정
# =========================================================

def get_openrouter_api_key():
    raw_api_key = os.environ.get("OPENROUTER_API_KEY", "")

    api_key = "".join(raw_api_key.split()).strip('"').strip("'")

    if api_key.lower().startswith("bearer"):
        api_key = api_key[6:].strip()

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY가 비어 있습니다.")

    if not api_key.startswith("sk-or-"):
        raise RuntimeError("OPENROUTER_API_KEY 형식이 올바르지 않습니다.")

    print(
        "OpenRouter 키 확인 완료: "
        f"길이={len(api_key)}, 시작={api_key[:6]}..."
    )

    return api_key


def create_openrouter_client():
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=get_openrouter_api_key(),
    )


# =========================================================
# 일일 학습 자료 생성
# =========================================================

def generate_study_material(article):
    client = create_openrouter_client()

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
  "vocab": [
    {{
      "word": "English word",
      "meaning": "Natural Korean meaning"
    }}
  ],
  "shadowing": [
    "English sentence"
  ],
  "quizzes": [
    {{
      "question": "English question",
      "options": [
        "Option 1",
        "Option 2",
        "Option 3"
      ],
      "answer": 0
    }}
  ],
  "rephraseTarget": [
    {{
      "original": "Original sentence",
      "ai_suggestion": "Suggested rephrasing"
    }}
  ]
}}

Requirements:
- Exactly 5 vocabulary items with Korean meanings.
- Exactly 5 shadowing sentences.
- Exactly 3 quizzes.
- Each quiz must have exactly 3 options.
- Quiz answer must be the zero-based correct index: 0, 1, or 2.
- Exactly 2 rephrasing exercises.
- Use only the supplied article information.
- Do not invent names, numbers, events, quotations, or facts.
- If the RSS description is limited, keep the material general.
- Output JSON only.
- Do not use Markdown fences.
"""

    print("OpenRouter에 학습 자료 생성을 요청합니다.")

    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Create accurate English-learning materials. "
                    "Return valid JSON only and never invent facts."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
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
        raise RuntimeError(
            f"AI 응답 JSON 처리 실패: {error}"
        ) from error

    validate_study_material(result, label="Daily Article")

    print("AI 학습 자료 생성 완료")

    return result


def validate_study_material(result, label):
    if len(result.vocab) != 5:
        raise RuntimeError(
            f"{label}: Vocabulary가 정확히 5개가 아닙니다."
        )

    if len(result.shadowing) != 5:
        raise RuntimeError(
            f"{label}: Shadowing 문장이 정확히 5개가 아닙니다."
        )

    if len(result.quizzes) != 3:
        raise RuntimeError(
            f"{label}: Quiz가 정확히 3개가 아닙니다."
        )

    if len(result.rephraseTarget) != 2:
        raise RuntimeError(
            f"{label}: Rephrasing이 정확히 2개가 아닙니다."
        )

    for quiz_number, quiz in enumerate(result.quizzes, start=1):
        if len(quiz.options) != 3:
            raise RuntimeError(
                f"{label}: Quiz {quiz_number}의 보기가 "
                "정확히 3개가 아닙니다."
            )

        if quiz.answer not in (0, 1, 2):
            raise RuntimeError(
                f"{label}: Quiz {quiz_number}의 정답 번호가 "
                "올바르지 않습니다."
            )


# =========================================================
# 날짜별 학습 자료 보관
# =========================================================

def archive_daily_output(output):
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    archive_path = ARCHIVE_DIR / f"{output['date']}.json"

    with archive_path.open("w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"날짜별 학습 자료 저장 완료: {archive_path}")


# =========================================================
# Weekly Review
# =========================================================

def load_weekly_articles():
    today = get_korea_today()
    items = []

    for days_back in range(6, 0, -1):
        target = today - timedelta(days=days_back)
        path = ARCHIVE_DIR / f"{target:%Y-%m-%d}.json"

        if not path.exists():
            print(f"복습 파일 없음: {path}")
            continue

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not data.get("isWeeklyReview", False):
            items.append(data)

    if not items and TODAY_FILE.exists():
        with TODAY_FILE.open("r", encoding="utf-8") as file:
            fallback = json.load(file)

        if (
            fallback.get("summary")
            and not fallback.get("isWeeklyReview", False)
        ):
            items.append(fallback)
            print(
                "아카이브가 없어 기존 today_news.json을 "
                "초기 복습자료로 사용합니다."
            )

    if not items:
        raise RuntimeError(
            "Weekly Review에 사용할 학습 자료가 없습니다."
        )

    print(f"Weekly Review 자료 {len(items)}개 불러오기 완료")

    return items


def generate_weekly_review(items):
    sources = [
        {
            "date": item.get("date", ""),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "vocab": item.get("vocab", []),
            "shadowing": item.get("shadowing", []),
        }
        for item in items
    ]

    source_json = json.dumps(
        sources,
        ensure_ascii=False,
        indent=2,
    )

    article = {
        "topic": "Weekly Review",
        "title": "Weekly English Review",
        "published": get_korea_today().strftime("%Y-%m-%d"),
        "description": source_json,
        "link": "",
    }

    client = create_openrouter_client()

    prompt = f"""
Create a Sunday Weekly Review based only on these previous study materials:

{source_json}

Return one valid JSON object with exactly these keys:
summary, vocab, shadowing, quizzes, rephraseTarget.

Requirements:
- Summary must contain 3 to 5 CEFR C1 sentences.
- Exactly 5 vocabulary items with Korean meanings.
- Exactly 5 shadowing sentences.
- Exactly 3 quizzes.
- Each quiz must have exactly 3 options.
- Each quiz answer must be the zero-based index 0, 1, or 2.
- Exactly 2 rephrasing exercises.
- Do not invent facts.
- Output JSON only.
- Do not use Markdown fences.
"""

    print("OpenRouter에 Weekly Review 생성을 요청합니다.")

    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Create an accurate Weekly Review. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    raw_content = response.choices[0].message.content

    if not raw_content:
        raise RuntimeError(
            "Weekly Review 응답이 비어 있습니다."
        )

    try:
        result = StudyMaterial.model_validate(
            json.loads(raw_content)
        )
    except Exception as error:
        print("Weekly Review 원본 응답:")
        print(raw_content)
        raise RuntimeError(
            f"Weekly Review JSON 처리 실패: {error}"
        ) from error

    validate_study_material(
        result,
        label="Weekly Review",
    )

    print("Weekly Review 생성 완료")

    return article, result


# =========================================================
# today_news.json 저장
# =========================================================

def save_today_news(article, study, is_weekly_review=False):
    output = {
        "title": article["title"],
        "date": get_korea_today().strftime("%Y-%m-%d"),
        "link": article["link"],
        "isWeeklyReview": is_weekly_review,
        "summary": study.summary,
        "vocab": [
            item.model_dump()
            for item in study.vocab
        ],
        "shadowing": list(study.shadowing),
        "quizzes": [
            item.model_dump()
            for item in study.quizzes
        ],
        "rephraseTarget": [
            item.model_dump()
            for item in study.rephraseTarget
        ],
    }

    with TODAY_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    with TODAY_FILE.open("r", encoding="utf-8") as file:
        validated = json.load(file)

    if len(validated.get("quizzes", [])) != 3:
        raise RuntimeError(
            "생성된 JSON의 Quiz 개수가 3개가 아닙니다."
        )

    if len(validated.get("vocab", [])) != 5:
        raise RuntimeError(
            "생성된 JSON의 Vocabulary 개수가 5개가 아닙니다."
        )

    if len(validated.get("shadowing", [])) != 5:
        raise RuntimeError(
            "생성된 JSON의 Shadowing 개수가 5개가 아닙니다."
        )

    if len(validated.get("rephraseTarget", [])) != 2:
        raise RuntimeError(
            "생성된 JSON의 Rephrasing 개수가 2개가 아닙니다."
        )

    if not is_weekly_review:
        if not validated.get("link"):
            raise RuntimeError(
                "공개 기사의 원문 링크가 비어 있습니다."
            )

        if is_blocked_cnbc_url(validated["link"]):
            raise RuntimeError(
                "저장 직전 Club 또는 Pro 링크가 감지되었습니다."
            )

        archive_daily_output(output)

    print("today_news.json 생성 완료")
    print(f"제목: {article['title']}")
    print(f"링크: {article['link']}")


# =========================================================
# 메인 실행
# =========================================================

def main():
    today = get_korea_today()

    if today.weekday() == 6:
        print("오늘은 Weekly Review Day입니다.")

        items = load_weekly_articles()
        article, study = generate_weekly_review(items)

        save_today_news(
            article,
            study,
            is_weekly_review=True,
        )

    else:
        article = pick_article()

        print(f"오늘의 주제: {article['topic']}")
        print(f"선택 기사: {article['title']}")
        print(f"실제 링크: {article['link']}")

        study = generate_study_material(article)

        if study is None:
            raise RuntimeError(
                "generate_study_material 함수가 "
                "결과를 반환하지 않았습니다."
            )

        save_today_news(
            article,
            study,
            is_weekly_review=False,
        )

    print("모든 작업이 정상적으로 완료되었습니다.")


if __name__ == "__main__":
    main()
