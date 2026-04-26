"""
콘텐츠 생성 모듈 (Claude Sonnet API)
- 4단계 생성으로 고품질 자연스러운 글 작성
- 금융/의학 YMYL 특화 프롬프트
- SEO 최적화 자동 적용
"""

import os
import anthropic
import json
import re
import requests
import base64


DISCLAIMER = {
    "금융": """
<div style="background:#f8f9fa;border-left:4px solid #007bff;padding:15px;margin:20px 0;border-radius:4px;">
<strong>⚠️ 투자/금융 면책조항</strong><br>
본 글은 일반적인 정보 제공을 목적으로 하며, 개인 금융 상담이나 투자 권유가 아닙니다. 금융 상품 가입 전 반드시 전문가 상담을 받으시기 바랍니다. 투자에는 원금 손실 위험이 있습니다.
</div>""",
    "의학/건강": """
<div style="background:#f8f9fa;border-left:4px solid #28a745;padding:15px;margin:20px 0;border-radius:4px;">
<strong>⚠️ 의학 정보 면책조항</strong><br>
본 글은 일반적인 건강 정보 제공을 목적으로 하며, 의학적 진단이나 치료를 대체하지 않습니다. 건강 관련 문제는 반드시 의사나 전문 의료진과 상담하시기 바랍니다.
</div>""",
    "생활정보": """
<div style="background:#f8f9fa;border-left:4px solid #ffc107;padding:15px;margin:20px 0;border-radius:4px;">
<strong>⚠️ 안내사항</strong><br>
본 글의 정보는 작성 시점 기준이며, 정부 정책이나 법령 변경에 따라 달라질 수 있습니다. 중요한 결정 전 반드시 공식 기관에서 확인하시기 바랍니다.
</div>"""
}


class ContentGenerator:
    CURRENT_YEAR = "2026"

    # 제목에 숫자가 없을 때 강제 삽입할 패턴
    TITLE_PATTERNS = [
        "{year}년 {keyword} 완벽 정리 | 꼭 알아야 할 핵심 정보",
        "{keyword} 관련 {n}가지 핵심 정보 완벽 정리",
        "{year}년 {keyword} {n}가지 주의사항 알아보기",
        "{keyword}로 알아보는 {n}가지 꿀팁 총정리",
        "{year}년 {keyword} {n}단계 실전 가이드",
    ]

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-6"

    def _call_claude(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        """Claude API 호출 (529 과부하 시 최대 3회 재시도)"""
        import time
        last_error = None
        for attempt in range(3):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": user_prompt}],
                    system=system_prompt
                )
                result = message.content[0].text
                return self._clean_response(result)
            except Exception as e:
                last_error = e
                err_str = str(e)
                # 529 과부하 또는 일시적 오류면 재시도
                if "529" in err_str or "overloaded" in err_str.lower() or "529" in type(e).__name__:
                    wait = 30 * (attempt + 1)  # 30초, 60초, 90초
                    print(f"  ⚠ Claude API 과부하 (529). {wait}초 후 재시도 ({attempt+1}/3)...")
                    time.sleep(wait)
                else:
                    raise  # 529 아닌 오류는 바로 예외 발생
        raise last_error

    def _enforce_title_number(self, title: str, keyword: str) -> str:
        """
        제목에 숫자가 없으면 키워드 기반으로 자연스럽게 삽입
        예) '신용대출 금리 낮추는 방법' → '신용대출 금리 낮추는 7가지 방법'
        """
        import random
        n = random.choice([3, 5, 6, 7, 8, 10])

        # 숫자가 이미 있으면 그대로 반환
        if re.search(r'\d', title):
            return title

        # ── 키워드 기반 자연스러운 제목 생성 ──────────────
        # 패턴 1: "~하는 방법" → "~하는 N가지 방법"
        if title.endswith('방법') or keyword.endswith('방법'):
            base = keyword.rstrip('방법').rstrip()
            new_title = f"{base} {n}가지 방법 완벽 정리"

        # 패턴 2: "~확인 방법" / "~하는 법"
        elif '확인' in keyword:
            new_title = f"{keyword}부터 {n}가지 체크포인트 총정리"

        # 패턴 3: "~신청 방법" / "~절차"
        elif '신청' in keyword or '절차' in keyword:
            new_title = f"{keyword} {n}단계로 쉽게 정리"

        # 패턴 4: "~절세" / "~줄이는" / "~낮추는"
        elif any(w in keyword for w in ['절세', '줄이는', '낮추는', '올리는', '늘리는']):
            new_title = f"{keyword} {n}가지 꿀팁 {self.CURRENT_YEAR}년 최신"

        # 패턴 5: "~증상" / "~원인"
        elif any(w in keyword for w in ['증상', '원인', '치료']):
            new_title = f"{keyword} {n}가지 핵심 정보 {self.CURRENT_YEAR}년 정리"

        # 패턴 6: 기타 → 연도 + N가지
        else:
            new_title = f"{self.CURRENT_YEAR}년 {keyword} {n}가지 핵심 정리"

        print(f"  ⚠ 제목 숫자 강제 삽입: {new_title}")
        return new_title

    def _repair_html(self, html: str) -> str:
        """끊긴 HTML 태그 복구 (표/리스트가 중간에 잘린 경우 닫아줌)"""
        # 열린 table이 닫히지 않은 경우
        open_tables  = html.count('<table')
        close_tables = html.count('</table>')
        for _ in range(open_tables - close_tables):
            html += '</tbody></table>'

        # 열린 tr이 닫히지 않은 경우
        open_tr  = html.count('<tr')
        close_tr = html.count('</tr>')
        for _ in range(open_tr - close_tr):
            html += '</tr>'

        # 열린 ul/ol이 닫히지 않은 경우
        for tag in ['ul', 'ol']:
            opens  = html.count(f'<{tag}')
            closes = html.count(f'</{tag}>')
            for _ in range(opens - closes):
                html += f'</{tag}>'

        return html

    def _clean_response(self, text: str) -> str:
        """마크다운 코드블록 제거 (```html ... ``` 등)"""
        # ```html 또는 ``` 로 감싸진 경우 제거
        text = re.sub(r'^```html\s*', '', text.strip())
        text = re.sub(r'^```\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text.strip())
        # 중간에 끼어있는 경우도 제거
        text = re.sub(r'```html', '', text)
        text = re.sub(r'```', '', text)
        return text.strip()

    def generate_outline(self, keyword_data: dict) -> dict:
        """
        Pass 1: SEO 최적화 아웃라인 생성
        """
        keyword = keyword_data["keyword"]
        category = keyword_data["category"]

        system = """당신은 한국의 최고 SEO 전문가이자 YMYL 콘텐츠 전략가입니다.
2025-2026년 구글 알고리즘(Helpful Content, Core Update)과 네이버 D.I.A.+ 알고리즘을 완벽히 이해합니다.

SEO 점수를 극대화하는 아웃라인 설계 원칙:
1. 검색 의도(Search Intent) 정밀 분석 → 글 상단에 핵심 답변 먼저 배치
2. 제목: 숫자/연도(2026년)/구체적 혜택 포함 → CTR(클릭률) 극대화
3. Featured Snippet 노출 위해 첫 섹션을 정의형 또는 리스트형으로 구성
4. FAQ는 구글 PAA(People Also Ask) 박스 노출 위해 실제 검색 질문 기반으로
5. LSI 키워드로 토픽 커버리지 확대 → 주제 권위도 상승
6. 네이버: 최신성·참여도 중시 → 업데이트 날짜, 구체적 수치, 실용 정보 강조
7. YMYL 신뢰도: 출처 명시, 면책조항, 전문가 관점 반드시 포함

JSON 형식으로만 응답하세요."""

        user = f"""키워드: "{keyword}" (카테고리: {category})

이 키워드로 검색하는 한국인들의 검색 의도를 분석하고,
Rank Math SEO 만점을 받을 수 있는 완벽한 아웃라인을 JSON으로 작성해주세요.

아래 Rank Math 체크리스트를 모두 충족해야 합니다:
✅ 제목 앞부분에 포커스 키워드 배치 (제목의 첫 단어 또는 두 번째 단어)
✅ 제목 작성 규칙 - 포커스 키워드에 숫자를 자연스럽게 녹여서 작성:
   포커스 키워드가 "신용대출 금리 낮추는 방법"이면:
   → "신용대출 금리 낮추는 7가지 방법 완벽 정리"
   포커스 키워드가 "당뇨 초기증상 확인 방법"이면:
   → "당뇨 초기증상 확인하는 5가지 방법 총정리"
   포커스 키워드가 "실손보험 청구 방법"이면:
   → "실손보험 청구 방법 8가지 핵심 포인트"
   포커스 키워드가 "상속세 절세 방법 2026"이면:
   → "2026년 상속세 절세하는 6가지 방법"
   → 숫자(N가지, N단계, 연도)는 반드시 포함, 3~10 사이 자연수 사용
✅ 제목 길이 35-55자
✅ 메타 설명에 포커스 키워드 포함 (120-155자)
✅ URL 슬러그에 포커스 키워드 포함 (영문 또는 한글, 60자 이하)
✅ 최소 2개 이상의 H2 부제목에 포커스 키워드 포함
✅ 외부 링크 2개 이상 (공신력 있는 기관 - DoFollow)
✅ 내부 링크 1개 이상 포함 예정

제목 예시 (이런 스타일로):
- "대출 이자 줄이는 2026년 핵심 5가지 방법"
- "고혈압 관리에 관한 7가지 주의사항 완벽 정리"
- "실손보험 청구와 관련된 8가지 꿀팁 알아보기"
- "2026년 신용점수 올리는 3단계 실전 가이드"
- "당뇨 초기증상 2026년 최신 정보 6가지"

{{
  "main_title": "포커스 키워드 앞배치 + 숫자(연도 또는 개수) 포함 제목 (40-60자)",
  "meta_description": "포커스 키워드 포함, 핵심 혜택 강조 (120-155자)",
  "url_slug": "focus-keyword-based-url (영문, 하이픈 구분, 60자 이하)",
  "search_intent": "검색 의도 분석 (정보형/거래형/탐색형)",
  "target_reader": "주요 독자층 설명",
  "keyword_density_target": 14,
  "sections": [
    {{
      "h2": "포커스 키워드 포함된 소제목",
      "key_points": ["핵심 내용1", "핵심 내용2"],
      "include_table": true,
      "include_list": true,
      "include_external_link": true
    }}
  ],
  "faq": [
    {{"question": "실제 검색되는 질문1", "answer_hint": "답변 방향"}},
    {{"question": "실제 검색되는 질문2", "answer_hint": "답변 방향"}}
  ],
  "lsi_keywords": ["관련 키워드1", "관련 키워드2", "관련 키워드3", "관련 키워드4", "관련 키워드5"],
  "external_links": [
    {{"anchor": "링크 텍스트", "url": "https://공신력있는기관.go.kr", "purpose": "근거 출처"}}
  ],
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"]
}}

섹션은 5-7개, FAQ는 3-5개로 구성하세요."""

        result = self._call_claude(system, user, max_tokens=2000)

        # JSON 파싱
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass

        # 파싱 실패 시 기본값
        return {
            "main_title": f"{keyword} 완벽 정리 | 꼭 알아야 할 핵심 정보",
            "meta_description": f"{keyword}에 대한 정확하고 신뢰할 수 있는 정보를 제공합니다.",
            "sections": [{"h2": "핵심 정보", "key_points": [keyword]}],
            "faq": [],
            "lsi_keywords": [keyword],
            "tags": [keyword, category]
        }

    def generate_article_body(self, keyword_data: dict, outline: dict) -> str:
        """
        Pass 2: 본문 작성 (전문가 톤, 자연스러운 한국어)
        """
        keyword = keyword_data["keyword"]
        category = keyword_data["category"]

        system = f"""당신은 {category} 분야에서 15년 이상 실무 경험을 쌓은 블로거입니다.
직접 겪었거나 주변에서 목격한 실제 경험담을 바탕으로 글을 씁니다.
구글 E-E-A-T의 핵심인 "경험(Experience)"을 최우선으로 반영합니다.

【경험담 기반 글쓰기 - 핵심 원칙】

이 글은 반드시 아래 요소를 포함한 "실제 경험자의 이야기"처럼 써야 합니다:

① 도입부에 개인 경험 에피소드 삽입
   예시) "작년에 제 지인이 실손보험 청구를 하다가 황당한 일을 겪었습니다."
   예시) "저도 처음엔 이게 이렇게 복잡한 줄 몰랐어요."
   예시) "주변에서 이 문제로 낭패 본 분들을 꽤 많이 봤거든요."

② 본문 중간에 경험자 시점의 인사이트 삽입
   예시) "직접 해보니까 이 부분에서 다들 막히더라고요."
   예시) "이걸 모르고 그냥 넘어갔다가 나중에 후회한 분들이 꽤 됩니다."
   예시) "저도 처음에 이 방법을 몰라서 몇 달을 헤맸던 기억이 나네요."

③ 구체적인 수치/사례를 경험자처럼 언급
   예시) "제가 실제로 비교해봤을 때 A사가 약 30만원 더 저렴했어요."
   예시) "아는 분은 이 방법으로 연간 120만원을 절약했다고 하더군요."

④ 실패담/시행착오 포함 (신뢰도 극대화)
   예시) "처음에 잘못 알고 신청했다가 반려된 적도 있었어요."
   예시) "이 부분을 간과했다가 나중에 낭패를 봤던 경험이 있습니다."

【문체 규칙】
- 블로그 말투: "~거든요", "~더라고요", "~잖아요", "~더니", "~했더니"
- 짧고 임팩트 있는 문장 + 설명하는 긴 문장 교차
- 독자에게 직접 말 걸기: "여러분은 어떠신가요?", "한번 확인해보세요"
- 전문용어 뒤 괄호로 쉬운 설명: "DSR(총부채원리금상환비율, 쉽게 말해 소득 대비 빚 비율)"

【절대 금지 - AI 냄새 나는 표현】
- "물론", "또한", "따라서", "이처럼", "결론적으로", "중요한 것은"
- "~할 수 있습니다", "~하는 것이 좋습니다" 반복
- 모든 문장이 비슷한 길이
- 교과서처럼 나열식으로만 쓰기
- 개인 경험이나 감정이 전혀 없는 건조한 설명체"""

        sections_text = json.dumps(outline.get("sections", []), ensure_ascii=False)
        lsi_keywords = ", ".join(outline.get("lsi_keywords", []))
        faq_text = json.dumps(outline.get("faq", []), ensure_ascii=False)

        user = f"""키워드: "{keyword}"
제목: {outline.get('main_title', '')}
검색 의도: {outline.get('search_intent', '')}
독자: {outline.get('target_reader', '')}

아웃라인:
{sections_text}

FAQ:
{faq_text}

LSI 키워드 (본문에 자연스럽게 포함): {lsi_keywords}

위 아웃라인을 바탕으로 Rank Math SEO 만점 기준의 블로그 글을 HTML 형식으로 작성해주세요.

【Rank Math 필수 체크리스트 - 전부 충족할 것】

★ 기본 SEO (Basic SEO)
- [필수] 제목(H1)에 포커스 키워드 "{keyword}" 포함
- [필수] 메타 설명에 포커스 키워드 포함
- [필수] 첫 번째 문단(콘텐츠 첫 10%) 안에 포커스 키워드 자연스럽게 배치
- [필수] 본문 전체에 포커스 키워드 포함 (키워드 밀도 약 1.5~2.5%)
- [필수] 총 분량: 1500~2000자 (너무 길면 내용이 잘리므로 이 범위 엄수)

★ 추가 SEO (Additional SEO)
- [필수] H2 부제목 2개 이상에 포커스 키워드 "{keyword}" 포함
- [필수] 이미지 alt 속성에 포커스 키워드 포함: <img src="" alt="{keyword} 관련이미지" />
- [필수] 외부 링크 2개 이상 (DoFollow, 공신력 있는 기관) 본문에 자연스럽게 삽입
- [필수] 내부 링크 1개 이상: <a href="/관련글/">관련 포스트 제목</a> 형태로 자연 삽입
- [권장] 포커스 키워드 조합 14회 전후 등장

★ 제목 가독성 (Title Readability)
- [필수] 제목 맨 앞에 포커스 키워드 배치
- [필수] 제목에 숫자 포함 (5가지, 2026년, 3단계 등)

【글 구성 순서】
1. 도입부: 독자 공감 + 포커스 키워드 첫 10% 안에 자연 삽입
2. H2 (포커스 키워드 포함): 핵심 정의/개요 → 표 또는 리스트
3. H2 (포커스 키워드 포함): 방법/절차 → <ol> 번호 목록
4. H2: 주의사항 또는 비교 정보 → 표 활용
5. H2: 실제 사례 또는 팁
6. H2: 자주 묻는 질문 → <dl><dt><dd> 구조
7. H2: 마치며 → 핵심 요약 + 행동 지침 1가지

【이미지 규칙 - 필수】
- 본문 상단에는 이미지 없음
- 반드시 본문 중간(3번째 H2 섹션 직후)에 이미지 1개 삽입:
  <figure style="margin:25px 0;text-align:center;">
  <img src="FEATURED_IMAGE" alt="{keyword} 이미지" style="max-width:100%;height:auto;border-radius:8px;" />
  <figcaption style="font-size:13px;color:#888;margin-top:6px;">{keyword} 관련 이미지</figcaption>
  </figure>
- 이 이미지가 WordPress 대표 이미지(썸네일)로도 자동 설정됨
- 본문에 이미지는 이 1개만 (더 추가 금지)

【부제목 키워드 삽입 규칙 - 필수】
- H2 태그 중 최소 2개 이상에 포커스 키워드 "{keyword}" 포함
- H3 태그에도 포커스 키워드 또는 LSI 키워드 포함
- 예: <h2>{keyword}의 핵심 방법 3가지</h2>, <h3>{keyword} 시 주의할 점</h3>

【키워드 밀도 규칙 - 필수】
- 포커스 키워드 "{keyword}"를 본문 전체에 최소 15~20회 자연스럽게 배치
- 키워드 변형/조합도 활용: "{keyword} 방법", "{keyword} 주의사항", "{keyword} 완벽 정리" 등
- <strong> 태그로 키워드 강조 최소 3회 이상: <strong>{keyword}</strong>

【글씨 색상 강조 규칙 - 필수】

중요한 내용은 반드시 파란색 글씨:
<span style="color:#1a73e8;font-weight:bold;">중요한 내용</span>

주의사항 텍스트는 반드시 빨간색 글씨:
<span style="color:#dc3545;font-weight:bold;">주의사항 내용</span>

【강조 박스 스타일 - 필수】
핵심 포인트 박스:
<div style="background:#fff3cd;border-left:4px solid #ffc107;padding:12px 15px;margin:15px 0;border-radius:4px;">
<strong>💡 핵심 포인트</strong><br><span style="color:#1a73e8;font-weight:bold;">중요한 내용을 파란 글씨로</span>
</div>

주의사항 박스:
<div style="background:#f8d7da;border-left:4px solid #dc3545;padding:12px 15px;margin:15px 0;border-radius:4px;">
<strong>⚠️ 주의</strong><br><span style="color:#dc3545;font-weight:bold;">주의사항을 빨간 글씨로</span>
</div>

꿀팁 박스:
<div style="background:#d4edda;border-left:4px solid #28a745;padding:12px 15px;margin:15px 0;border-radius:4px;">
<strong>✅ 꿀팁</strong><br>팁 내용
</div>

【결론 섹션 필수 - 반드시 마지막에 포함】
<h2>{keyword} 핵심 정리 – 마치며</h2>
내용:
- 글 전체 핵심 3가지를 경험자 말투로 요약
- 독자가 지금 당장 실행할 수 있는 행동 1가지 구체적으로 제시
- 따뜻한 마무리 인사
- RELATED_POSTS_PLACEHOLDER (내부 링크 자리)

HTML만 출력하세요. 마크다운이나 설명 텍스트 없이."""

        result = self._call_claude(system, user, max_tokens=8000)

        # 잘림 감지: 마지막 태그가 제대로 닫혔는지 확인
        if not result.rstrip().endswith('>'):
            print("  ⚠ 본문이 잘린 것 같습니다. HTML 복구 시도...")
        return result

    def humanize_content(self, content: str, keyword: str) -> str:
        """
        Pass 3: 인간화 처리 - AI 감지 우회
        """
        system = """당신은 15년 경력의 블로거이자 카피라이터입니다.
AI가 쓴 글을 실제 사람이 직접 경험하고 쓴 것처럼 완전히 변환하는 전문가입니다.
구글 AI 감지, Originality.ai, GPTZero를 통과하는 수준으로 변환해야 합니다.

【최우선 목표: 경험담 블로그로 변환】

반드시 아래 5가지를 글 전체에 녹여야 합니다:

1. 도입부를 개인 에피소드로 시작
   - "제가 작년에 직접 겪은 일인데요..." 또는
   - "얼마 전에 지인이 이 문제로 연락이 왔더라고요..." 또는
   - "저도 처음에 이걸 몰라서 꽤 고생했거든요..."

2. 본문 중간에 시행착오/실패담 1개 이상 삽입
   - "처음엔 이렇게 했다가 낭패를 봤어요"
   - "이 부분을 모르고 진행했다가 한 달을 날렸습니다"

3. 구체적 경험 수치 삽입
   - "제가 직접 비교해봤을 때 약 ~원 차이가 났어요"
   - "주변 사례를 보면 평균 ~% 정도 절약이 가능하더라고요"

4. 감정 표현 자연 삽입
   - "솔직히 처음엔 너무 복잡해서 포기하고 싶었어요"
   - "이걸 알고 나서 진짜 후회가 됐습니다"
   - "생각보다 간단해서 오히려 당황했어요"

5. 마무리에 개인 소감/추천
   - "저는 이 방법을 쓰고 나서 확실히 달라졌어요"
   - "여러분도 한번 시도해보시길 진심으로 권해드립니다"

【AI 냄새 제거 규칙】
- "물론", "또한", "따라서", "이처럼" → 삭제하거나 구어체로 교체
- "~할 수 있습니다" → "~할 수 있어요", "~되더라고요"
- 비슷한 길이 문장 연속 → 짧은 문장(5-10자)과 긴 문장(30-50자) 교차
- 나열식 설명 → 경험담 + 설명 구조로 변환
- HTML 태그는 절대 건드리지 말 것"""

        user = f"""아래 HTML 글을 실제 사람이 직접 경험하고 쓴 블로그 글로 완전히 변환해주세요.
포커스 키워드 "{keyword}"와 HTML 구조는 유지하면서,
경험담·감정·시행착오가 자연스럽게 녹아든 글로 바꿔주세요.

읽는 사람이 "아, 이 사람이 직접 겪어본 얘기구나"라고 느껴야 합니다.

{content}

변환된 HTML만 출력하세요."""

        result = self._call_claude(system, user, max_tokens=8000)

        # 인간화 후 잘림 감지 및 복구
        if not result.rstrip().endswith('>'):
            print("  ⚠ 인간화 단계에서 내용이 잘렸습니다. 원본 유지...")
            # 인간화가 실패하면 원본 본문 반환
            return content
        return result

    def generate_focus_keywords(self, keyword: str, outline: dict) -> list:
        """
        Pass 4: Rank Math용 포커스 키워드 3개 생성
        - 메인 키워드 1개 + 검색량 높은 변형/조합 2개
        """
        system = """당신은 한국 SEO 전문가입니다.
주어진 메인 키워드를 바탕으로 Rank Math SEO에 등록할
포커스 키워드 3개를 선정해주세요.

조건:
- 1번: 메인 키워드 (그대로)
- 2번: 메인 키워드 + 가장 많이 검색되는 조합어 (예: "키워드 방법", "키워드 조건")
- 3번: 메인 키워드 + 두 번째로 많이 검색되는 조합어 (예: "키워드 주의사항", "키워드 비용")

JSON 배열로만 응답: ["키워드1", "키워드2", "키워드3"]"""

        lsi = outline.get("lsi_keywords", [])
        user = f"""메인 키워드: "{keyword}"
LSI 키워드 참고: {", ".join(lsi[:5])}

포커스 키워드 3개를 JSON 배열로만 출력하세요."""

        try:
            result = self._call_claude(system, user, max_tokens=200)
            match = re.search(r'\[.*?\]', result, re.DOTALL)
            if match:
                keywords = json.loads(match.group())
                if isinstance(keywords, list) and len(keywords) >= 3:
                    kws = keywords[:3]
                    # 반드시 3개인지 확인
                    return self._enforce_three_keywords(keyword, kws)
        except Exception as e:
            print(f"  포커스 키워드 생성 오류: {e}")

        # 실패 시 기본값 강제 생성
        return self._enforce_three_keywords(keyword, [])

    def _enforce_three_keywords(self, keyword: str, kws: list) -> list:
        """포커스 키워드가 반드시 3개가 되도록 강제"""
        fallbacks = [
            keyword,
            f"{keyword} 방법",
            f"{keyword} 주의사항",
            f"{keyword} 비용",
            f"{keyword} 신청방법",
            f"{keyword} 조건",
        ]
        result = list(kws)
        # 부족한 만큼 fallback으로 채우기
        for fb in fallbacks:
            if len(result) >= 3:
                break
            if fb not in result:
                result.append(fb)
        final = result[:3]
        print(f"  포커스 키워드 3개 확정: {' | '.join(final)}")
        return final

    def generate_seo_meta(self, outline: dict, keyword: str) -> dict:
        """
        Pass 4: SEO 메타데이터 최적화
        """
        return {
            "title": outline.get("main_title", f"{keyword} 완벽 가이드"),
            "meta_description": outline.get("meta_description", ""),
            "tags": outline.get("tags", [keyword]),
            "focus_keyword": keyword,
            "lsi_keywords": outline.get("lsi_keywords", [])
        }

    def generate_article(self, keyword_data: dict) -> dict:
        """
        전체 글 생성 파이프라인 실행
        """
        keyword = keyword_data["keyword"]
        category = keyword_data["category"]

        print(f"  [1/4] 아웃라인 생성 중...")
        outline = self.generate_outline(keyword_data)

        print(f"  [2/4] 본문 작성 중...")
        body = self.generate_article_body(keyword_data, outline)

        print(f"  [3/4] 자연스럽게 다듬는 중...")
        humanized_body = self.humanize_content(body, keyword)

        print(f"  [4/4] SEO 메타데이터 + 포커스 키워드 3개 생성 중...")
        seo_meta = self.generate_seo_meta(outline, keyword)

        # ★ 제목 숫자 강제 검증
        title = seo_meta["title"]
        title = self._enforce_title_number(title, keyword)
        seo_meta["title"] = title
        print(f"  제목: {title}")

        # ★ 포커스 키워드 3개 강제 확정
        focus_keywords = self.generate_focus_keywords(keyword, outline)
        # 혹시라도 3개 미만이면 강제로 채움
        if len(focus_keywords) < 3:
            focus_keywords = self._enforce_three_keywords(keyword, focus_keywords)

        # AI 생성 본문에서 RELATED_POSTS_PLACEHOLDER 제거 (위치 고정을 위해)
        humanized_body = humanized_body.replace("RELATED_POSTS_PLACEHOLDER", "")

        # 끊긴 HTML 태그 복구 (표/리스트가 중간에 잘린 경우)
        humanized_body = self._repair_html(humanized_body)

        # ── 최종 콘텐츠 조립 (순서 고정) ──────────────────
        # 1. 면책조항
        disclaimer = DISCLAIMER.get(category, DISCLAIMER["생활정보"])

        # 2. 본문
        body_section = disclaimer + "\n\n" + humanized_body

        # 3. 참고기관 (본문 바로 아래)
        references = self._get_references_section(category)

        # 4. 함께 읽으면 유용한 글 (맨 마지막)
        print(f"  [관련글] WordPress에서 추천 글 가져오는 중...")
        related_posts = self._get_related_posts(keyword, category)

        # 순서 보장: 본문 → 참고기관 → 유용한 글
        final_content = body_section + references + "\n" + related_posts

        return {
            "title": seo_meta["title"],
            "content": final_content,
            "meta_description": seo_meta["meta_description"],
            "tags": seo_meta["tags"],
            "focus_keyword": keyword,
            "focus_keywords": focus_keywords,           # Rank Math용 3개
            "focus_keywords_str": ",".join(focus_keywords),  # 쉼표 구분 문자열
            "url_slug": outline.get("url_slug", keyword.replace(" ", "-")),
            "category": category,
            "lsi_keywords": seo_meta["lsi_keywords"]
        }

    def _get_related_posts(self, keyword: str, category: str) -> str:
        """WordPress에서 실제 발행된 글 목록을 가져와 추천 섹션 생성"""
        wp_url = os.getenv("WP_URL", "").rstrip("/")
        username = os.getenv("WP_USERNAME")
        app_password = os.getenv("WP_APP_PASSWORD")

        try:
            credentials = f"{username}:{app_password}"
            token = base64.b64encode(credentials.encode()).decode()
            headers = {"Authorization": f"Basic {token}"}

            resp = requests.get(
                f"{wp_url}/wp-json/wp/v2/posts",
                headers=headers,
                params={"per_page": 10, "status": "publish", "orderby": "date"},
                timeout=10
            )

            if resp.status_code == 200:
                posts = resp.json()
                if posts:
                    links_html = ""
                    for post in posts[:5]:
                        title = post.get("title", {}).get("rendered", "")
                        link  = post.get("link", "")
                        if title and link:
                            links_html += f'<li><a href="{link}">{title}</a></li>\n'

                    if links_html:
                        return f"""
<div style="background:#f0f4ff;border:1px solid #c5d0f0;padding:20px;margin:25px 0;border-radius:8px;">
<h3 style="margin-top:0;color:#2c3e50;">📚 함께 읽으면 유용한 글</h3>
<ul style="margin:0;padding-left:20px;line-height:2;">
{links_html}</ul>
<p style="margin-bottom:0;font-size:13px;color:#888;">{wp_url.replace("https://", "").replace("http://", "")}의 다른 유용한 정보들도 확인해보세요.</p>
</div>"""
        except Exception as e:
            print(f"  관련 글 가져오기 오류: {e}")

        # 글이 없거나 실패 시 카테고리별 기본 링크
        site_name = wp_url.replace("https://", "").replace("http://", "")
        return f"""
<div style="background:#f0f4ff;border:1px solid #c5d0f0;padding:20px;margin:25px 0;border-radius:8px;">
<h3 style="margin-top:0;color:#2c3e50;">📚 함께 읽으면 유용한 글</h3>
<ul style="margin:0;padding-left:20px;line-height:2;">
<li><a href="{wp_url}">{site_name} 메인으로 이동</a></li>
</ul>
</div>"""

    def _get_references_section(self, category: str) -> str:
        """카테고리별 참고 기관 링크"""
        refs = {
            "금융": """
<hr>
<p><small><strong>참고 기관:</strong>
<a href="https://www.fss.or.kr" target="_blank" rel="noopener">금융감독원</a> |
<a href="https://www.kcb.or.kr" target="_blank" rel="noopener">한국신용정보원</a> |
<a href="https://www.nts.go.kr" target="_blank" rel="noopener">국세청</a>
</small></p>""",
            "의학/건강": """
<hr>
<p><small><strong>참고 기관:</strong>
<a href="https://www.mohw.go.kr" target="_blank" rel="noopener">보건복지부</a> |
<a href="https://www.hira.or.kr" target="_blank" rel="noopener">건강보험심사평가원</a> |
<a href="https://health.kdca.go.kr" target="_blank" rel="noopener">질병관리청</a>
</small></p>""",
            "생활정보": """
<hr>
<p><small><strong>참고:</strong>
<a href="https://www.gov.kr" target="_blank" rel="noopener">정부24</a> |
<a href="https://www.bokjiro.go.kr" target="_blank" rel="noopener">복지로</a>
</small></p>"""
        }
        return refs.get(category, refs["생활정보"])
