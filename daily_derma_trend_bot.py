"""
데일리 애프터케어 및 더마코스메틱 트렌드 자동 브리핑 봇 (Daily Derma Trend Bot)
=============================================================================
이 스크립트는 매일 자동으로 최신 애프터케어 및 더마코스메틱 뉴스를 수집하고,
Google Gemini API(최신 google-genai SDK 및 REST API 지원)를 통해 핵심 트렌드를 분석·요약한 뒤:
1. 웹 대시보드(index.html 또는 derma_trend_dashboard.html)를 자동으로 갱신(최신 브리핑 추가)하고,
2. 텔레그램(Telegram) 또는 슬랙(Slack), 이메일로 자동 전송합니다.

[실행 환경]
1. 로컬 PC / 개인 서버: cron 또는 Windows 작업 스케줄러로 매일 오전 9시 실행
2. GitHub Actions: 서버 비용 0원으로 클라우드에서 매일 오전 9시(KST) 자동 실행 및 웹사이트 배포

[필요 라이브러리]
pip install requests google-genai python-dotenv
"""

import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import urllib.parse
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# ==============================================================================
# 환경 변수 및 설정 (Configuration)
# ==============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# 이메일 전송 설정 (선택 사항)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")

# 검색 키워드 목록
SEARCH_KEYWORDS = [
    "더마코스메틱 신제품",
    "피부과 시술 후 애프터케어",
    "PDRN 엑소좀 재생 앰플",
    "피부장벽 리페어 트렌드"
]


# ==============================================================================
# 1. 최신 뉴스 및 트렌드 수집 모듈 (Google News RSS 활용 - 별도 API 키 불필요)
# ==============================================================================
def fetch_latest_news(keywords, max_items_per_kw=4):
    """
    구글 뉴스 RSS 피드를 활용하여 키워드별 최신 기사를 수집합니다.
    별도의 유료 검색 API 없이 안정적으로 최신 뉴스를 가져옵니다.
    """
    collected_articles = []
    seen_titles = set()

    for kw in keywords:
        encoded_kw = urllib.parse.quote(kw)
        rss_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
        
        try:
            response = requests.get(rss_url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                items = root.findall(".//item")[:max_items_per_kw]
                
                for item in items:
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                    
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        collected_articles.append({
                            "keyword": kw,
                            "title": title,
                            "link": link,
                            "pub_date": pub_date
                        })
        except Exception as e:
            print(f"[{kw}] 뉴스 수집 중 오류 발생: {e}", file=sys.stderr)

    return collected_articles


# ==============================================================================
# 2. LLM 브리핑 생성 모듈 (최신 google-genai 및 REST API 지원)
# ==============================================================================
def generate_trend_briefing(articles):
    """
    수집된 뉴스 기사 리스트를 기반으로 최신 Gemini API를 호출하여
    체계적인 데일리 더마코스메틱 트렌드 브리핑 텍스트를 생성합니다.
    """
    if not GEMINI_API_KEY:
        print("경고: GEMINI_API_KEY가 설정되지 않아 규칙 기반 기본 요약본을 생성합니다.")
        return create_fallback_briefing(articles)

    context_lines = []
    for i, a in enumerate(articles, 1):
        context_lines.append(f"{i}. [{a['keyword']}] {a['title']}\n   링크: {a['link']}")
    context_text = "\n".join(context_lines)

    prompt = f"""당신은 대한민국 뷰티 및 더마코스메틱 업계의 전문 트렌드 분석가입니다.
아래 수집된 오늘자 최신 뉴스 기사들을 바탕으로, 실무진과 기획자에게 유용한 '데일리 애프터케어 & 더마코스메틱 트렌드 일일 브리핑'을 작성해주세요.

[오늘 수집된 뉴스 목록]
{context_text}

[작성 형식]
반드시 다음 4가지 번호 섹션으로 구분하여 명확하고 실용적인 인사이트를 제공해주세요:
1. 주요 트렌드 및 유통 동향 (핵심 시장 이슈 2~3개)
2. 주목할 성분 및 신기술 동향 (PDRN, 엑소좀, EGF, 펩타이드, 장벽 재생 등)
3. 소비자 반응 및 다운타임 케어 프로토콜 (시술 직후 피부 진정 니즈)
4. 마케팅 및 제품 기획 인사이트 (신제품 제형, 소구점, 카테고리 제안)

각 항목은 개조식 불릿(-)으로 간결하고 전문적인 문체로 작성해주세요."""

    # 1. 최신 google-genai SDK 방식 시도
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and hasattr(response, "text") and response.text:
                    print(f"✓ 최신 google-genai SDK ({model_name})로 브리핑 생성 성공")
                    return response.text
            except Exception as e:
                print(f"google-genai ({model_name}) 호출 실패: {e}")
    except ImportError:
        pass

    # 2. 구버전 google.generativeai SDK 방식 시도 (하위 호환)
    try:
        import google.generativeai as legacy_genai
        legacy_genai.configure(api_key=GEMINI_API_KEY)
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                model = legacy_genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text:
                    print(f"✓ 구버전 SDK ({model_name})로 브리핑 생성 성공")
                    return response.text
            except Exception as e:
                print(f"구버전 SDK ({model_name}) 호출 실패: {e}")
    except ImportError:
        pass

    # 3. 직접 REST API 호출 (SDK 버전 이슈 없이 100% 안전하게 동작)
    try:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"✓ REST API ({model_name})로 브리핑 생성 성공")
                return text
            else:
                print(f"REST API ({model_name}) 응답 코드: {res.status_code}")
    except Exception as e:
        print(f"REST API 호출 중 오류: {e}")

    # 모든 API 시도 실패 시 기본 브리핑 생성
    print("경고: AI 모델 호출에 실패하여 기본 템플릿 브리핑으로 대체합니다.")
    return create_fallback_briefing(articles)


def create_fallback_briefing(articles):
    """API 키가 없거나 호출 실패 시 동작하는 규칙 기반 기본 브리핑 템플릿"""
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    lines = [
        f"📅 {today_str} 데일리 애프터케어 & 더마코스메틱 주요 기사",
        "",
        "1. 주요 트렌드 및 유통 동향",
    ]
    for a in articles[:3]:
        lines.append(f"- {a['title']} ({a['link']})")
    
    lines.extend([
        "",
        "2. 주목할 성분 및 신기술 동향",
        "- PDRN(연어/식물성) 및 엑소좀 고농축 앰플 중심의 홈케어 시장 확장 지속",
        "- 마이크로바이옴 및 판테놀·세라마이드 복합 고보습 리페어 크림 수요 증가",
        "",
        "3. 소비자 반응 및 다운타임 케어 프로토콜",
        "- 레이저·리프팅 시술 후 72시간 골든타임 진정 및 붉은기 완화 제품 선호",
        "",
        "4. 마케팅 및 제품 기획 인사이트",
        "- '피부과 전문의 공동개발' 및 '인체적용시험(피부장벽 개선율)' 데이터 전면 배치 권장"
    ])
    return "\n".join(lines)


# ==============================================================================
# 3. HTML 웹 대시보드 자동 갱신 모듈 (Auto-Update Dashboard)
# ==============================================================================
def update_html_dashboard(briefing_text, html_filename="index.html"):
    """
    생성된 텍스트 브리핑을 파싱하여 index.html 또는 derma_trend_dashboard.html 파일 내부의
    BRIEFINGS_DATA 배열 맨 앞에 자동으로 추가합니다.
    """
    possible_paths = [
        html_filename,
        "index.html",
        "derma_trend_dashboard.html",
        os.path.join(os.path.dirname(__file__), html_filename),
        os.path.join(os.path.dirname(__file__), "index.html"),
        os.path.join(os.path.dirname(__file__), "derma_trend_dashboard.html"),
        os.path.join("artifacts", "file_generation", "ttl=63d", "output", "index.html"),
        os.path.join("artifacts", "file_generation", "ttl=63d", "output", "derma_trend_dashboard.html"),
    ]

    target_path = None
    for p in possible_paths:
        if os.path.exists(p):
            target_path = p
            break

    if not target_path:
        print(f"대시보드 HTML 파일({html_filename})을 찾지 못해 HTML 업데이트를 건너뜁니다.")
        return False

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()

        today_date = datetime.now().strftime("%Y-%m-%d")
        if f'"{today_date}"' in content:
            print(f"[{today_date}] 이미 HTML 대시보드에 오늘자 브리핑이 반영되어 있습니다.")
            return True

        # 간단한 목차별 파싱
        sections = []
        current_sec = None
        for line in briefing_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if any(line.startswith(prefix) for prefix in ["1.", "2.", "3.", "4.", "### 1", "### 2", "### 3", "### 4"]):
                if current_sec:
                    sections.append(current_sec)
                current_sec = {
                    "title": line.replace("#", "").strip(),
                    "points": []
                }
            elif current_sec and (line.startswith(("-", "•", "*")) or (len(line) > 5 and not line.startswith("🧴"))):
                clean_pt = line.lstrip("-•* ").strip()
                if clean_pt:
                    current_sec["points"].append(clean_pt)

        if current_sec:
            sections.append(current_sec)

        # 4개 기본 섹션 보장
        if not sections:
            sections = [{"title": "오늘의 핵심 브리핑", "points": [line.strip() for line in briefing_text.split("\n") if line.strip()][:5]}]

        # 새 브리핑 데이터 구조
        briefing_obj = {
            "id": today_date,
            "date": today_date,
            "title": f"데일리 애프터케어 & 더마코스메틱 트렌드 ({datetime.now().strftime('%m월 %d일')})",
            "tags": ["시술사후관리", "PDRN·엑소좀", "장벽리페어"],
            "summary": "오늘 수집된 최신 뉴스를 바탕으로 AI가 자동 분석한 데일리 시장 및 성분 트렌드 브리핑입니다.",
            "sections": sections
        }

        json_str = json.dumps(briefing_obj, ensure_ascii=False, indent=8)
        snippet = f"      {json_str.strip()},\n"

        marker = "    const BRIEFINGS_DATA = [\n"
        if marker in content:
            updated_content = content.replace(marker, marker + snippet, 1)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(updated_content)
            print(f"✓ [{today_date}] HTML 대시보드에 오늘자 브리핑이 자동 추가되었습니다: {target_path}")
            return True
        else:
            print("HTML 파일 내 BRIEFINGS_DATA 마커를 찾지 못했습니다.")
            return False

    except Exception as e:
        print(f"HTML 대시보드 업데이트 중 오류 발생: {e}", file=sys.stderr)
        return False


# ==============================================================================
# 4. 전송 채널 모듈 (Telegram, Slack, Email)
# ==============================================================================
def send_telegram_message(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}", file=sys.stderr)
        return False


def send_slack_message(text):
    if not SLACK_WEBHOOK_URL:
        return False

    payload = {"text": text}
    try:
        res = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"슬랙 전송 실패: {e}", file=sys.stderr)
        return False


def send_email_briefing(subject, body):
    if not (SMTP_USER and SMTP_PASSWORD and EMAIL_RECEIVER):
        return False

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"이메일 전송 실패: {e}", file=sys.stderr)
        return False


# ==============================================================================
# 메인 실행 파이프라인
# ==============================================================================
def main():
    print(f"[{datetime.now()}] 데일리 더마코스메틱 트렌드 수집 및 분석 시작...")

    # 1. 뉴스 데이터 수집
    print("1. 구글 뉴스 RSS 데이터 수집 중...")
    articles = fetch_latest_news(SEARCH_KEYWORDS, max_items_per_kw=4)
    print(f"총 {len(articles)}개의 최신 관련 뉴스를 수집했습니다.")

    if not articles:
        print("수집된 뉴스가 없습니다. 종료합니다.")
        return

    # 2. LLM 브리핑 생성
    print("2. Gemini AI를 활용한 트렌드 분석 및 브리핑 생성 중...")
    briefing = generate_trend_briefing(articles)
    header = f"🧴 [데일리 더마코스메틱 트렌드 브리핑] {datetime.now().strftime('%Y-%m-%d')}\n\n"
    final_message = header + briefing

    # 3. HTML 웹 대시보드 파일 자동 업데이트
    print("3. 웹 대시보드(HTML 홈페이지) 자동 업데이트 진행 중...")
    update_html_dashboard(briefing)

    # 4. 외부 메신저/이메일 발송 (설정된 경우)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        if send_telegram_message(final_message):
            print("✓ 텔레그램 메시지 발송 완료")

    if SLACK_WEBHOOK_URL:
        if send_slack_message(final_message):
            print("✓ 슬랙 채널 메시지 발송 완료")

    if SMTP_USER and EMAIL_RECEIVER:
        if send_email_briefing(f"[더마 트렌드] {datetime.now().strftime('%m월 %d일')} 데일리 브리핑", final_message):
            print("✓ 이메일 발송 완료")

    print(f"[{datetime.now()}] 브리핑 봇 작업이 성공적으로 완료되었습니다.")


if __name__ == "__main__":
    main()