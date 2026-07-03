"""
콘텐츠 생성 모듈 - 비용 최적화 버전
- 3단계 생성 (아웃라인 → 본문+인간화 통합 → 메타)
- 아웃라인/키워드: claude-haiku (저렴)
- 본문: claude-sonnet (고품질)
- Pass 3 인간화 단계 제거 → 본문 생성 시 통합 처리
"""

import os
from google import genai
from google.genai import types
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

    # 본문 생성 system prompt의 정적 부분 — 매 호출마다 동일하므로 prompt cache 대상
    _BODY_SYSTEM_STATIC = """직접 겪은 경험담을 바탕으로 SEO 최적화된 블로그 글을 씁니다.

【글쓰기 규칙】
1. 도입부: 개인 경험 에피소드로 시작 ("제가 작년에...", "지인이 이 문제로...")
2. 본문: 시행착오/실패담 1개 이상 포함, 구체적 수치 언급
3. 문체: 구어체 (거든요/더라고요/잖아요), 짧은 문장+긴 문장 교차
4. 금지: "물론", "또한", "따라서", "이처럼", "결론적으로" 사용 금지
5. HTML 구조 엄수, 마크다운 절대 금지

【SEO/GEO 필수 규칙】
- H2 2개 이상에 포커스 키워드 포함
- 첫 문단 10% 이내 키워드 자연 배치
- 키워드 밀도 1.5~2.5% (15~20회)
- <strong> 태그로 키워드 강조 3회 이상
- 외부 링크: 제공된 외부 링크 목록의 URL과 앵커 텍스트를 활용하여 2개 이상 본문에 자연스럽게 DoFollow 링크로 삽입하십시오. 링크는 정보의 근거를 보강하는 인라인 인용 형태로 구성하십시오. (예: "국세청의 [양도세 세율 안내](URL)에 따르면...")
- 내부 링크: 가짜 내부 링크(예: /관련글/)는 웹사이트 크롤링 에러(404)를 유발하여 SEO 감점 요인이 되므로 절대 본문에 직접 작성하지 마십시오. (하단에 관련 글 섹션이 시스템에서 자동 추가됩니다.)
- 총 분량: 1500~2000자

【정보 신뢰도 & GEO(Generative Engine Optimization) 규칙】
1. Direct Answer (피처드 스니펫 최적화): 도입부 극초반(첫 번째 H2 이전)에 검색 키워드에 대한 결론이나 정답을 2-3줄 내외로 일목요연하게 정리한 요점 요약 박스(<div style="background:#f1f3f4;border-left:4px solid #1a73e8;padding:12px 15px;margin:15px 0;border-radius:4px;"><strong>💡 핵심 요약</strong><br>내용</div>)를 작성하십시오.
2. 구체적 통계 및 데이터 강조: 본문에 관련 조사결과, 퍼센트(%), 금액 등 구체적인 데이터 수치를 명시하고 이를 표(Table)나 강조 텍스트로 시각화하십시오.

【스타일】
중요 내용: <span style="color:#1a73e8;font-weight:bold;">내용</span>
주의사항: <span style="color:#dc3545;font-weight:bold;">내용</span>
핵심박스: <div style="background:#fff3cd;border-left:4px solid #ffc107;padding:12px 15px;margin:15px 0;border-radius:4px;"><strong>💡 핵심 포인트</strong><br>내용</div>
주의박스: <div style="background:#f8d7da;border-left:4px solid #dc3545;padding:12px 15px;margin:15px 0;border-radius:4px;"><strong>⚠️ 주의</strong><br>내용</div>
꿀팁박스: <div style="background:#d4edda;border-left:4px solid #28a745;padding:12px 15px;margin:15px 0;border-radius:4px;"><strong>✅ 꿀팁</strong><br>내용</div>

【이미지 삽입】
본문 흐름에 맞추어 3개의 이미지를 아래 지정된 위치에 각각 정확히 삽입하십시오. (user 메시지에서 전달된 이미지 HTML 템플릿의 src 플레이스홀더를 그대로 사용하십시오)
- 첫 번째 이미지 (FEATURED_IMAGE): 첫 번째 H2 바로 아래에 삽입
- 두 번째 이미지 (BODY_IMAGE_1): 세 번째 H2 바로 아래에 삽입
- 세 번째 이미지 (BODY_IMAGE_2): 다섯 번째 H2 바로 아래(또는 FAQ 바로 전 H2 아래)에 삽입

【구성순서】도입부 → Direct Answer 핵심 요약 박스 → H2(정의/개요+FEATURED_IMAGE+표) → H2(방법/절차+ol) → H2(주의사항+BODY_IMAGE_1+표) → H2(사례/팁) → H2(마치며/FAQ전+BODY_IMAGE_2) → H2(FAQ: <dl><dt><dd>) → H2(맺음말+RELATED_POSTS_PLACEHOLDER)

HTML만 출력."""

    TITLE_PATTERNS = [
        "{year}년 {keyword} 완벽 정리 | 꼭 알아야 할 핵심 정보",
        "{keyword} 관련 {n}가지 핵심 정보 완벽 정리",
        "{year}년 {keyword} {n}가지 주의사항 알아보기",
        "{keyword}로 알아보는 {n}가지 꿀팁 총정리",
        "{year}년 {keyword} {n}단계 실전 가이드",
    ]

    def __init__(self, site: str = "life"):
        self.site = site
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = "gemini-3.1-flash-lite"                 # 본문 생성용 (고품질)
        self.cheap_model = "gemini-3.1-flash-lite"         # 아웃라인/키워드용 (저렴)

    def _call_gemini(self, system_prompt, user_prompt: str, max_tokens: int = 4000, cheap: bool = False) -> str:
        """Gemini API 호출 (503/429 대기 및 재시도 포함)"""
        import time
        model = self.cheap_model if cheap else self.model
        
        if isinstance(system_prompt, list):
            system_str = "\n".join([item["text"] for item in system_prompt if "text" in item])
        else:
            system_str = str(system_prompt)
            
        config = types.GenerateContentConfig(
            system_instruction=system_str,
            max_output_tokens=max_tokens,
            temperature=0.7,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
            ]
        )
        
        last_error = None
        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config
                )
                return self._clean_response(response.text)
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_retryable = any(
                    term in err_str
                    for term in ["429", "503", "quota", "overloaded", "unavailable", "demand", "resource_exhausted"]
                )
                if is_retryable:
                    wait = 15 * (attempt + 1)
                    print(f"  Gemini API 과부하/할당량 대기... {wait}초 후 재시도 (에러: {str(e)[:60]})")
                    time.sleep(wait)
                else:
                    raise
        raise last_error

    def _enforce_title_number(self, title: str, keyword: str) -> str:
        import random
        n = random.choice([3, 5, 6, 7, 8, 10])
        if re.search(r'\d', title):
            return title
        if title.endswith('방법') or keyword.endswith('방법'):
            base = keyword.rstrip('방법').rstrip()
            new_title = f"{base} {n}가지 방법 완벽 정리"
        elif '확인' in keyword:
            new_title = f"{keyword}부터 {n}가지 체크포인트 총정리"
        elif '신청' in keyword or '절차' in keyword:
            new_title = f"{keyword} {n}단계로 쉽게 정리"
        elif any(w in keyword for w in ['절세', '줄이는', '낮추는', '올리는', '늘리는']):
            new_title = f"{keyword} {n}가지 꿀팁 {self.CURRENT_YEAR}년 최신"
        elif any(w in keyword for w in ['증상', '원인', '치료']):
            new_title = f"{keyword} {n}가지 핵심 정보 {self.CURRENT_YEAR}년 정리"
        else:
            new_title = f"{self.CURRENT_YEAR}년 {keyword} {n}가지 핵심 정리"
        print(f"  제목 숫자 강제 삽입: {new_title}")
        return new_title

    def _repair_html(self, html: str) -> str:
        open_tables  = html.count('<table')
        close_tables = html.count('</table>')
        for _ in range(open_tables - close_tables):
            html += '</tbody></table>'
        open_tr  = html.count('<tr')
        close_tr = html.count('</tr>')
        for _ in range(open_tr - close_tr):
            html += '</tr>'
        for tag in ['ul', 'ol']:
            opens  = html.count(f'<{tag}')
            closes = html.count(f'</{tag}>')
            for _ in range(opens - closes):
                html += f'</{tag}>'
        return html

    def _clean_response(self, text: str) -> str:
        text = re.sub(r'^```html\s*', '', text.strip())
        text = re.sub(r'^```\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text.strip())
        text = re.sub(r'```html', '', text)
        text = re.sub(r'```', '', text)
        
        # DOCTYPE, html, head, body 랩퍼 태그 제거 (워드프레스 삽입 최적화)
        text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'</?html[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<head>[\s\S]*?</head>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'</?body[^>]*>', '', text, flags=re.IGNORECASE)
        
        return text.strip()

    def generate_outline(self, keyword_data: dict) -> dict:
        """Pass 1: SEO 아웃라인 생성 (Haiku - 저렴)"""
        keyword = keyword_data["keyword"]
        category = keyword_data["category"]

        system = """한국 SEO 전문가. JSON 형식으로만 응답.
핵심 원칙: 검색 의도 분석, 제목에 숫자+연도 포함, Featured Snippet 최적화, YMYL 신뢰도."""

        user = f"""키워드: "{keyword}" (카테고리: {category})

Rank Math SEO 만점 기준 아웃라인을 JSON으로 작성:
- main_title: 포커스 키워드 앞배치 + 숫자(N가지/연도) 포함 (40-55자)
- meta_description: 포커스 키워드 포함 (120-155자)
- url_slug: 영문 하이픈, 60자 이하
- search_intent: 정보형/거래형/탐색형
- target_reader: 주요 독자층
- sections: 5-6개 [{{"h2":"","key_points":[],"include_table":bool,"include_list":bool}}]
- faq: 3-4개 [{{"question":"","answer_hint":""}}]
- lsi_keywords: 5개 배열
- external_links: [{{"anchor":"","url":"https://공신력기관.go.kr","purpose":""}}] 2개
- tags: 5개 배열

JSON만 출력."""

        result = self._call_gemini(system, user, max_tokens=1000, cheap=True)

        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass

        return {
            "main_title": f"{keyword} 완벽 정리 | 꼭 알아야 할 핵심 정보",
            "meta_description": f"{keyword}에 대한 정확하고 신뢰할 수 있는 정보를 제공합니다.",
            "sections": [{"h2": "핵심 정보", "key_points": [keyword]}],
            "faq": [],
            "lsi_keywords": [keyword],
            "tags": [keyword, category]
        }

    def generate_article_body(self, keyword_data: dict, outline: dict) -> str:
        """Pass 2: 본문 작성 + 인간화 통합 (Sonnet, prompt cache 적용)"""
        keyword = keyword_data["keyword"]
        category = keyword_data["category"]

        # 사이트별 블로거 페르소나 설정 (E-E-A-T 대응)
        if self.site == "worker":
            persona = "당신은 근로기준법 및 직장인 복지/재테크 분야 15년 경력의 인사(HR) 전문 블로거입니다. 직장인과 근로자들에게 실질적이고 정확한 법률/혜택 정보를 이해하기 쉽게 전달합니다."
        else:
            persona = f"당신은 {category} 분야 15년 경력 블로거입니다."

        system = [
            {
                "type": "text",
                "text": self._BODY_SYSTEM_STATIC,
                "cache_control": {"type": "ephemeral"}
            },
            {
                "type": "text",
                "text": persona
            }
        ]

        sections_text = json.dumps(outline.get("sections", []), ensure_ascii=False)
        lsi_keywords = ", ".join(outline.get("lsi_keywords", []))
        faq_text = json.dumps(outline.get("faq", []), ensure_ascii=False)

        # 이미지 HTML 템플릿들을 user 메시지로 이동 (system을 정적으로 유지하기 위함)
        image_html_1 = (
            f'<figure style="margin:25px 0;text-align:center;">\n'
            f'  <img src="FEATURED_IMAGE" alt="{keyword} 이미지 1" style="max-width:100%;height:auto;border-radius:8px;" />\n'
            f'  <figcaption style="font-size:13px;color:#888;margin-top:6px;">{keyword} 관련 설명</figcaption>\n'
            f'</figure>'
        )
        image_html_2 = (
            f'<figure style="margin:25px 0;text-align:center;">\n'
            f'  <img src="BODY_IMAGE_1" alt="{keyword} 이미지 2" style="max-width:100%;height:auto;border-radius:8px;" />\n'
            f'  <figcaption style="font-size:13px;color:#888;margin-top:6px;">{keyword} 상세 분석</figcaption>\n'
            f'</figure>'
        )
        image_html_3 = (
            f'<figure style="margin:25px 0;text-align:center;">\n'
            f'  <img src="BODY_IMAGE_2" alt="{keyword} 이미지 3" style="max-width:100%;height:auto;border-radius:8px;" />\n'
            f'  <figcaption style="font-size:13px;color:#888;margin-top:6px;">{keyword} 요약 정리</figcaption>\n'
            f'</figure>'
        )

        ext_links = outline.get("external_links", [])
        ext_links_text = json.dumps(ext_links, ensure_ascii=False) if ext_links else "없음"

        user = f"""키워드: "{keyword}"
제목: {outline.get('main_title', '')}
검색의도: {outline.get('search_intent', '')}
독자: {outline.get('target_reader', '')}

아웃라인:
{sections_text}

FAQ:
{faq_text}

LSI 키워드: {lsi_keywords}

외부 링크 목록 (인라인 출처 링크로 본문 내 자연스럽게 인용하여 삽입):
{ext_links_text}

이미지 HTML 템플릿:
- 이미지 1 (첫 번째 H2 직후 삽입):
{image_html_1}
- 이미지 2 (세 번째 H2 직후 삽입):
{image_html_2}
- 이미지 3 (다섯 번째 H2 직후 삽입):
{image_html_3}

위 내용으로 HTML 블로그 글을 작성하세요. HTML만 출력."""

        result = self._call_gemini(system, user, max_tokens=5000)

        if not result.rstrip().endswith('>'):
            print("  본문이 잘린 것 같습니다. HTML 복구 시도...")
        return result

    def generate_focus_keywords(self, keyword: str, outline: dict) -> list:
        """포커스 키워드 3개 생성 (Haiku - 저렴)"""
        system = """한국 SEO 전문가. JSON 배열로만 응답: ["키워드1", "키워드2", "키워드3"]
1번: 메인 키워드 그대로, 2번: 키워드+조합어, 3번: 키워드+다른조합어"""

        lsi = outline.get("lsi_keywords", [])
        user = f"""메인 키워드: "{keyword}"
LSI 참고: {", ".join(lsi[:5])}
JSON 배열만 출력."""

        try:
            result = self._call_gemini(system, user, max_tokens=150, cheap=True)
            match = re.search(r'\[.*?\]', result, re.DOTALL)
            if match:
                keywords = json.loads(match.group())
                if isinstance(keywords, list) and len(keywords) >= 3:
                    return self._enforce_three_keywords(keyword, keywords[:3])
        except Exception as e:
            print(f"  포커스 키워드 생성 오류: {e}")

        return self._enforce_three_keywords(keyword, [])

    def _enforce_three_keywords(self, keyword: str, kws: list) -> list:
        fallbacks = [keyword, f"{keyword} 방법", f"{keyword} 주의사항",
                     f"{keyword} 비용", f"{keyword} 신청방법", f"{keyword} 조건"]
        result = list(kws)
        for fb in fallbacks:
            if len(result) >= 3:
                break
            if fb not in result:
                result.append(fb)
        final = result[:3]
        print(f"  포커스 키워드: {' | '.join(final)}")
        return final

    def generate_seo_meta(self, outline: dict, keyword: str) -> dict:
        return {
            "title": outline.get("main_title", f"{keyword} 완벽 가이드"),
            "meta_description": outline.get("meta_description", ""),
            "tags": outline.get("tags", [keyword]),
            "focus_keyword": keyword,
            "lsi_keywords": outline.get("lsi_keywords", [])
        }

    def generate_article(self, keyword_data: dict, session=None) -> dict:
        """전체 글 생성 (3단계: 아웃라인 → 본문 → 메타)
        session: WordPressPublisher의 인증된 세션 (관련글 로딩에 사용)
        """
        keyword = keyword_data["keyword"]
        category = keyword_data["category"]

        print(f"  [1/3] 아웃라인 생성 중... (Haiku)")
        outline = self.generate_outline(keyword_data)

        print(f"  [2/3] 본문 작성 중... (Sonnet)")
        body = self.generate_article_body(keyword_data, outline)

        print(f"  [3/3] SEO 메타 + 포커스 키워드 생성 중... (Haiku)")
        seo_meta = self.generate_seo_meta(outline, keyword)

        title = self._enforce_title_number(seo_meta["title"], keyword)
        seo_meta["title"] = title
        print(f"  제목: {title}")

        focus_keywords = self.generate_focus_keywords(keyword, outline)
        if len(focus_keywords) < 3:
            focus_keywords = self._enforce_three_keywords(keyword, focus_keywords)

        body = body.replace("RELATED_POSTS_PLACEHOLDER", "")
        body = self._repair_html(body)

        disclaimer = DISCLAIMER.get(category, DISCLAIMER["생활정보"])
        body_section = disclaimer + "\n\n" + body
        references = self._get_references_section(category)

        print(f"  [관련글] WordPress에서 추천 글 가져오는 중...")
        related_posts = self._get_related_posts(keyword, category, session=session)

        final_content = body_section + references + "\n" + related_posts

        return {
            "title": seo_meta["title"],
            "content": final_content,
            "meta_description": seo_meta["meta_description"],
            "tags": seo_meta["tags"],
            "focus_keyword": keyword,
            "focus_keywords": focus_keywords,
            "focus_keywords_str": ",".join(focus_keywords),
            "url_slug": outline.get("url_slug", keyword.replace(" ", "-")),
            "category": category,
            "lsi_keywords": seo_meta["lsi_keywords"]
        }

    def _get_related_posts(self, keyword: str, category: str, session=None) -> str:
        """WordPress 최근 글 3개를 가져와 추천 섹션 생성
        session: 인증된 세션(카페24 cupid 쿠키 포함)이 있으면 그대로 사용
        """
        wp_url = os.getenv("WP_URL", "").rstrip("/")
        username = os.getenv("WP_USERNAME")
        app_password = os.getenv("WP_APP_PASSWORD")

        try:
            api_url = f"{wp_url}/wp-json/wp/v2/posts"
            params = {"per_page": 10, "status": "publish", "orderby": "date"}

            if session:
                resp = session.get(api_url, params=params, timeout=10)
            else:
                credentials = f"{username}:{app_password}"
                token = base64.b64encode(credentials.encode()).decode()
                headers = {"Authorization": f"Basic {token}"}
                resp = requests.get(api_url, headers=headers, params=params, timeout=10)

            if resp.status_code == 200:
                posts = resp.json()
                if posts and isinstance(posts, list):
                    import random
                    # 최대 10개 중 랜덤 3개 선택
                    sample = random.sample(posts, min(3, len(posts)))
                    links_html = ""
                    for post in sample:
                        title = post.get("title", {}).get("rendered", "")
                        link  = post.get("link", "")
                        if title and link:
                            links_html += f'<li><a href="{link}">{title}</a></li>\n'

                    if links_html:
                        print(f"  관련 글 {len(sample)}개 로딩 완료")
                        return f"""
<div style="background:#f0f4ff;border:1px solid #c5d0f0;padding:20px;margin:25px 0;border-radius:8px;">
<h3 style="margin-top:0;color:#2c3e50;">📚 함께 읽으면 유용한 글</h3>
<ul style="margin:0;padding-left:20px;line-height:2;">
{links_html}</ul>
<p style="margin-bottom:0;font-size:13px;color:#888;">{wp_url.replace("https://", "").replace("http://", "")}의 다른 유용한 정보들도 확인해보세요.</p>
</div>"""
        except Exception as e:
            print(f"  관련 글 가져오기 오류: {e}")

        # 글이 없거나 실패 시 빈 섹션 반환 (메인 링크 노출 안 함)
        return ""

    def _get_references_section(self, category: str) -> str:
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
