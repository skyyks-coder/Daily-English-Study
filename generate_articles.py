# -*- coding: utf-8 -*-
import html, json, os, random, re, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import feedparser, requests
from openai import OpenAI
from pydantic import BaseModel

CNBC_RSS_URLS=[
 'https://www.cnbc.com/id/100003114/device/rss/rss.html',
 'https://www.cnbc.com/id/100727362/device/rss/rss.html',
 'https://www.cnbc.com/id/15837362/device/rss/rss.html',
 'https://www.cnbc.com/id/20409666/device/rss/rss.html?x=1']
OPENROUTER_BASE_URL='https://openrouter.ai/api/v1'
ARCHIVE_DIR=Path('articles'); TODAY_FILE=Path('today_news.json')
REQUEST_TIMEOUT=20; MAX_RSS_ENTRIES=60; MAX_PUBLIC_CANDIDATES=20
BLOCKED_URL_KEYWORDS=('/investingclub/','/investing-club/','/cnbc-pro/','/pro/','/club/','cnbc.com/pro')
BLOCKED_RSS_KEYWORDS=('cnbc pro','cnbc investing club','investing club','pro subscribers','club members','members only','subscriber only','subscription required')
BLOCKED_PAGE_PATTERNS=(
 r'"isAccessibleForFree"\s*:\s*false',r'"isAccessibleForFree"\s*:\s*"false"',
 r'"accessibilityForFree"\s*:\s*false',r'"premium"\s*:\s*true',r'"isPremium"\s*:\s*true',
 r'"contentClassification"\s*:\s*"(?:PRO|CLUB|PREMIUM)"',
 r'"contentTier"\s*:\s*"(?:PRO|CLUB|PREMIUM|PAID)"',
 r'sign\s+in\s+to\s+(?:continue|read)\s+(?:this|the)\s+article',
 r'subscribe\s+to\s+(?:continue|read)\s+(?:this|the)\s+article')
PUBLIC_ARTICLE_PATTERNS=(r'"@type"\s*:\s*"(?:NewsArticle|Article)"',r'"articleBody"\s*:',r'property=["\']og:type["\']\s+content=["\']article["\']',r'class=["\'][^"\']*article-body')

class VocabularyItem(BaseModel): word:str; meaning:str
class QuizItem(BaseModel): question:str; options:list[str]; answer:int
class RephraseItem(BaseModel): original:str; ai_suggestion:str
class StudyMaterial(BaseModel):
 summary:str; vocab:list[VocabularyItem]; shadowing:list[str]; quizzes:list[QuizItem]; rephraseTarget:list[RephraseItem]

def get_korea_today(): return datetime.now(ZoneInfo('Asia/Seoul'))
def get_today_topic(): return {0:'Business',1:'Travel',2:'AI',3:'Food',4:'Economy',5:'Culture',6:'Weekly Review'}[get_korea_today().weekday()]
def clean_html(text):
 text=html.unescape(str(text or '')); text=re.sub(r'<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<[^>]+>',' ',text,flags=re.I|re.S); return re.sub(r'\s+',' ',text).strip()
def is_blocked_cnbc_url(url):
 u=str(url or '').strip().lower(); return not u or 'cnbc.com' not in u or any(k in u for k in BLOCKED_URL_KEYWORDS)
def has_blocked_page_signal(text):
 return next((p for p in BLOCKED_PAGE_PATTERNS if re.search(p,text,re.I|re.S)),None)
def has_public_article_signal(text): return any(re.search(p,text,re.I|re.S) for p in PUBLIC_ARTICLE_PATTERNS)

def is_public_cnbc_article(entry):
 title=str(entry.get('title','')).strip(); link=str(entry.get('link','')).strip(); summary=clean_html(entry.get('summary','') or entry.get('description','')).lower()
 if not title or is_blocked_cnbc_url(link) or any(k in f'{title.lower()} {summary}' for k in BLOCKED_RSS_KEYWORDS): return False
 try:
  r=requests.get(link,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/xhtml+xml'},timeout=REQUEST_TIMEOUT,allow_redirects=True)
 except requests.RequestException as e: print('기사 연결 실패:',e); return False
 page=r.text or ''; blocked=has_blocked_page_signal(page)
 if r.status_code!=200 or is_blocked_cnbc_url(r.url) or len(page)<5000 or blocked or not has_public_article_signal(page):
  if blocked: print('제외: 유료 신호',blocked)
  return False
 entry['link']=r.url; print('공개 기사 확인 완료:',title); return True

def fetch_cnbc_rss_entries():
 headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/rss+xml,application/xml;q=0.9,*/*;q=0.7','Referer':'https://www.cnbc.com/'}
 entries=[]; seen=set()
 for url in CNBC_RSS_URLS:
  for attempt in range(1,4):
   try:
    print(f'CNBC RSS 요청: {url} (시도 {attempt}/3)'); r=requests.get(url,headers=headers,timeout=30,allow_redirects=True); print('CNBC RSS 응답:',r.status_code,len(r.content)); r.raise_for_status(); feed=feedparser.parse(r.content)
    for e in feed.entries:
     title=str(e.get('title','')).strip(); link=str(e.get('link','')).strip()
     if title and link and link not in seen: seen.add(link); entries.append(e)
    break
   except requests.RequestException as ex:
    print('RSS 요청 실패:',ex)
    if attempt<3: time.sleep(attempt*3)
  if len(entries)>=MAX_RSS_ENTRIES: break
 print('CNBC RSS 최종 수집 기사:',len(entries)); return entries

def get_topic_candidates(entries,topic):
 keys={'Business':['business','company','retail','earnings','ceo','sales'],'Travel':['travel','airline','hotel','tourism','flight','airport'],'AI':['ai','artificial intelligence','technology','tech','openai','nvidia'],'Food':['food','restaurant','coffee','consumer','grocery','beverage'],'Economy':['economy','inflation','interest rate','fed','jobs','market'],'Culture':['culture','media','entertainment','sports','lifestyle','film']}
 found=[]
 for e in entries:
  text=clean_html(f"{e.get('title','')} {e.get('summary','') or e.get('description','')}").lower()
  if any(k in text for k in keys.get(topic,[])): found.append(e)
 return found or list(entries[:15])
def select_public_article(candidates):
 pool=list(candidates); random.shuffle(pool)
 for i,e in enumerate(pool[:MAX_PUBLIC_CANDIDATES],1):
  print(f"후보 {i}: {e.get('title','')}")
  if is_public_cnbc_article(e): return e
 raise RuntimeError('후보 기사 중 공개 CNBC 기사를 찾지 못했습니다.')
def pick_article():
 entries=fetch_cnbc_rss_entries()
 if not entries: raise RuntimeError('모든 CNBC RSS 주소에서 기사를 불러오지 못했습니다.')
 topic=get_today_topic(); candidates=get_topic_candidates(entries,topic)
 try: article=select_public_article(candidates)
 except RuntimeError:
  used={str(e.get('link','')) for e in candidates}; article=select_public_article([e for e in entries if str(e.get('link','')) not in used])
 title=str(article.get('title','')).strip(); link=str(article.get('link','')).strip(); published=article.get('published','') or article.get('updated',''); description=clean_html(article.get('summary','') or article.get('description','')) or title
 if not title or not link: raise RuntimeError('선택된 기사 정보가 올바르지 않습니다.')
 return {'title':title,'link':link,'published':published,'description':description,'topic':topic}

def client():
 key=''.join(os.environ.get('OPENROUTER_API_KEY','').split()).strip('"').strip("'")
 if not key.startswith('sk-or-'): raise RuntimeError('OPENROUTER_API_KEY가 없거나 형식이 올바르지 않습니다.')
 return OpenAI(base_url=OPENROUTER_BASE_URL,api_key=key)
def requirements(): return 'Return JSON keys summary, vocab, shadowing, quizzes, rephraseTarget. Summary 3-5 C1 sentences. Exactly 5 vocab, 5 shadowing, 3 quizzes with 3 options and zero-based answer, 2 rephrasing items. Korean vocab meanings. Do not invent facts. JSON only.'
def request_material(prompt,label,temp):
 r=client().chat.completions.create(model='openai/gpt-4o-mini',messages=[{'role':'system','content':'Return accurate English study material as JSON only.'},{'role':'user','content':prompt}],response_format={'type':'json_object'},temperature=temp)
 obj=StudyMaterial.model_validate(json.loads(r.choices[0].message.content))
 if len(obj.vocab)!=5 or len(obj.shadowing)!=5 or len(obj.quizzes)!=3 or len(obj.rephraseTarget)!=2: raise RuntimeError(label+': 항목 수 오류')
 return obj
def generate_study_material(a): return request_material(f"Create material only from: {json.dumps(a,ensure_ascii=False)}\n{requirements()}",'Daily Article',0.4)
def load_weekly_articles():
 today=get_korea_today(); items=[]
 for d in range(6,0,-1):
  p=ARCHIVE_DIR/f'{today-timedelta(days=d):%Y-%m-%d}.json'
  if p.exists():
   x=json.loads(p.read_text(encoding='utf-8'))
   if not x.get('isWeeklyReview'): items.append(x)
 if not items and TODAY_FILE.exists(): items=[json.loads(TODAY_FILE.read_text(encoding='utf-8'))]
 if not items: raise RuntimeError('Weekly Review 자료가 없습니다.')
 return items
def generate_weekly_review(items):
 a={'topic':'Weekly Review','title':'Weekly English Review','published':f'{get_korea_today():%Y-%m-%d}','description':'','link':''}; return a,request_material(f"Create weekly review from {json.dumps(items,ensure_ascii=False)}\n{requirements()}",'Weekly Review',0.3)
def save_today_news(a,s,weekly=False):
 out={'title':a['title'],'date':f'{get_korea_today():%Y-%m-%d}','link':a['link'],'isWeeklyReview':weekly,'summary':s.summary,'vocab':[x.model_dump() for x in s.vocab],'shadowing':s.shadowing,'quizzes':[x.model_dump() for x in s.quizzes],'rephraseTarget':[x.model_dump() for x in s.rephraseTarget]}
 TODAY_FILE.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 if not weekly: ARCHIVE_DIR.mkdir(exist_ok=True); (ARCHIVE_DIR/f"{out['date']}.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 print('today_news.json 생성 완료')
def main():
 if get_korea_today().weekday()==6: a,s=generate_weekly_review(load_weekly_articles()); save_today_news(a,s,True)
 else: a=pick_article(); print('선택 기사:',a['title']); save_today_news(a,generate_study_material(a),False)
 print('모든 작업이 정상적으로 완료되었습니다.')
if __name__=='__main__': main()
