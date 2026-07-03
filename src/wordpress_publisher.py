"""
WordPress 자동 발행 모듈
- WordPress REST API 사용
- 카페24 호스팅 호환
- 이미지 업로드 + 포스트 생성 + SEO 메타 설정
"""

import os
import re
import json
import time
import mimetypes
from datetime import datetime
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth
from Crypto.Cipher import AES


# 카테고리 ID 매핑 (워드프레스에서 미리 만들어둔 카테고리 ID)
# 실제 사이트 카테고리 ID로 변경 필요
CATEGORY_IDS = {
    "금융": 2,       # 워드프레스 카테고리 ID
    "의학/건강": 3,
    "생활정보": 4,
}


class WordPressPublisher:
    def __init__(self):
        self.wp_url = os.getenv("WP_URL", "").rstrip("/")
        self.username = (os.getenv("WP_USERNAME") or "").strip()
        self.app_password = (os.getenv("WP_APP_PASSWORD") or "").strip()
        self.post_status = os.getenv("WP_POST_STATUS", "draft")

        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        # 세션으로 쿠키 유지 + HTTPBasicAuth로 리다이렉트 후에도 인증 유지
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.auth = HTTPBasicAuth(self.username, self.app_password)
        self._solve_cupid_challenge()

    def _solve_cupid_challenge(self):
        """카페24 cupid.js AES 챌린지 해결 후 세션 쿠키 설정"""
        try:
            resp = self.session.get(self.wp_url + "/wp-json/wp/v2/users/me", timeout=15)
            if "cupid.js" not in resp.text:
                return  # 챌린지 없음

            html = resp.text
            print("  [cupid] 카페24 봇 챌린지 감지 → 해결 시도 중...")

            # 카페24 형식: var a=toNumbers("KEY"),b=toNumbers("IV"),c=toNumbers("ENC");
            # slowAES.decrypt(c, 2, a, b) → decrypt(ciphertext=c, CBC, key=a, iv=b)
            abc = re.findall(r'toNumbers\("([0-9a-fA-F]+)"\)', html)
            decrypt_match = re.search(r'slowAES\.decrypt\((\w+),\s*2,\s*(\w+),\s*(\w+)\)', html)

            if len(abc) < 3 or not decrypt_match:
                print("  [cupid] 파라미터 추출 실패 - 전체 응답:")
                print(html)
                return

            # var a, b, c 순서대로 추출
            var_map = {}
            for i, letter in enumerate(['a', 'b', 'c']):
                var_map[letter] = abc[i]

            # decrypt(c, 2, a, b) → c=암호문, a=key, b=iv
            c_var = decrypt_match.group(1)  # 암호문 변수
            a_var = decrypt_match.group(2)  # key 변수
            b_var = decrypt_match.group(3)  # iv 변수

            enc_hex = var_map.get(c_var, abc[2])
            key_hex = var_map.get(a_var, abc[0])
            iv_hex  = var_map.get(b_var, abc[1])

            key       = bytes.fromhex(key_hex)
            iv        = bytes.fromhex(iv_hex)
            encrypted = bytes.fromhex(enc_hex)

            # AES-CBC 복호화
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted)
            cookie_value = decrypted.hex()

            # 쿠키 이름 추출 (document.cookie="CUPID=...")
            name_match = re.search(r'document\.cookie\s*=\s*"(\w+)=', html)
            cookie_name = name_match.group(1) if name_match else "CUPID"

            domain = urlparse(self.wp_url).hostname
            self.session.cookies.set(cookie_name, cookie_value, domain=domain)
            print(f"  [cupid] 챌린지 해결 완료 (쿠키: {cookie_name}={cookie_value[:8]}...)")

        except Exception as e:
            print(f"  [cupid] 챌린지 해결 오류: {e}")

    def _get(self, url, **kwargs):
        """GET 요청 (연결 끊김 시 1회 재시도)"""
        for attempt in range(2):
            try:
                return self.session.get(url, **kwargs)
            except requests.exceptions.ConnectionError:
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise

    def _post(self, url, **kwargs):
        """POST 요청 (연결 끊김 시 1회 재시도)"""
        for attempt in range(2):
            try:
                return self.session.post(url, **kwargs)
            except requests.exceptions.ConnectionError:
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise

    def _api_url(self, endpoint: str) -> str:
        return f"{self.wp_url}/wp-json/wp/v2/{endpoint}"

    def get_category_id(self, category_name: str) -> int:
        """카테고리 이름으로 ID 조회 (없으면 생성)"""
        # 먼저 매핑 테이블 확인
        mapped_id = CATEGORY_IDS.get(category_name)
        if mapped_id:
            return mapped_id

        # WordPress에서 카테고리 검색
        try:
            response = self._get(
                self._api_url("categories"),
                params={"search": category_name, "per_page": 5},
                timeout=15
            )
            if response.status_code == 200:
                categories = response.json()
                for cat in categories:
                    if cat["name"] == category_name:
                        return cat["id"]

            # 없으면 새로 생성
            response = self._post(
                self._api_url("categories"),
                json={"name": category_name},
                timeout=15
            )
            if response.status_code == 201:
                return response.json()["id"]
        except Exception as e:
            print(f"  카테고리 조회/생성 오류: {e}")

        return 1  # 기본 카테고리

    def get_or_create_tags(self, tag_names: list) -> list:
        """태그 조회 또는 생성, ID 목록 반환"""
        tag_ids = []
        for tag_name in tag_names[:3]:  # 최대 3개로 줄여서 API 호출 감소
            try:
                time.sleep(2)  # 태그마다 2초 대기
                response = self._get(
                    self._api_url("tags"),
                    params={"search": tag_name, "per_page": 5},
                    timeout=10
                )
                if response.status_code == 200:
                    tags = response.json()
                    found = next((t for t in tags if t["name"] == tag_name), None)
                    if found:
                        tag_ids.append(found["id"])
                        continue

                # 없으면 생성
                time.sleep(2)
                response = self._post(
                    self._api_url("tags"),
                    json={"name": tag_name},
                    timeout=10
                )
                if response.status_code == 201:
                    tag_ids.append(response.json()["id"])
            except Exception as e:
                print(f"  태그 처리 오류 ({tag_name}): {e}")

        return tag_ids

    def upload_image(self, image_data: dict) -> int | None:
        """이미지를 WordPress 미디어 라이브러리에 업로드 (429 재시도 포함)"""
        image_url = image_data.get("url") or image_data.get("medium_url")
        local_path = image_data.get("local_path")
        if not image_url and not local_path:
            return None

        try:
            if local_path and os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    img_content = f.read()
                filename = os.path.basename(local_path)
                if not filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    filename += '.png'
            else:
                # 이미지 다운로드
                img_response = requests.get(image_url, timeout=30)
                if img_response.status_code != 200:
                    return None
                img_content = img_response.content
                # 파일명 생성
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"featured_{timestamp}.jpg"

            # WordPress에 업로드 - multipart/form-data 방식 (WAF 우회)
            # Content-Type을 None으로 설정해 세션 기본값(application/json)을 제거
            # → requests가 multipart boundary를 자동으로 설정하게 함
            mime_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
            for attempt in range(3):
                files = {"file": (filename, img_content, mime_type)}
                response = self.session.post(
                    self._api_url("media"),
                    files=files,
                    headers={"Content-Type": None},
                    timeout=60
                )

                if response.status_code == 201:
                    break
                elif response.status_code == 429:
                    body_preview = response.text[:200] if response.text else "(빈 응답)"
                    wait = 20 * (attempt + 1)  # 20초, 40초, 60초
                    print(f"  이미지 업로드 429 - 서버 응답: {body_preview}")
                    print(f"  {wait}초 후 재시도 ({attempt+1}/3)...")
                    time.sleep(wait)
                else:
                    body_preview = response.text[:200] if response.text else "(빈 응답)"
                    print(f"  이미지 업로드 실패: {response.status_code} - {body_preview}")
                    return None
            else:
                print(f"  이미지 업로드 실패 (재시도 초과) - Hostinger WAF 차단 가능성")
                return None

            if response.status_code == 201:
                media_data = response.json()
                media_id  = media_data["id"]
                media_url = media_data.get("source_url", "")
                print(f"  이미지 업로드 완료 (ID: {media_id})")

                # Alt 텍스트 + 출처 캡션 설정
                focus_kw  = image_data.get("focus_keyword", image_data.get("alt", ""))
                alt_text  = f"{focus_kw} 이미지" if focus_kw else image_data.get("alt", "")
                source    = image_data.get("source", "").capitalize()
                credit    = image_data.get("photographer", "")
                caption   = f"출처: {source} / {credit}" if credit else f"출처: {source}"

                time.sleep(1)
                self._post(
                    self._api_url(f"media/{media_id}"),
                    json={"alt_text": alt_text, "caption": caption},
                    timeout=10
                )

                # media_url을 image_data에 저장 (본문 FEATURED_IMAGE 교체에 사용)
                image_data["_uploaded_url"] = media_url
                return media_id

        except Exception as e:
            print(f"  이미지 업로드 오류: {e}")
        return None

    def set_rankmath_seo(self, post_id: int, article: dict):
        """Rank Math 포커스 키워드 설정 - 3가지 방법으로 시도"""
        focus_keywords_str = article.get(
            "focus_keywords_str",
            article.get("focus_keyword", "")
        )
        kws = article.get("focus_keywords", [article.get("focus_keyword", "")])

        # 방법 1: REST API meta 업데이트
        try:
            resp = self._post(
                self._api_url(f"posts/{post_id}"),
                json={
                    "comment_status": "closed",
                    "ping_status":    "closed",
                    "meta": {
                        "rank_math_focus_keyword": focus_keywords_str,
                        "rank_math_title":         article["title"],
                        "rank_math_description":   article.get("meta_description", ""),
                        "_yoast_wpseo_focuskw":    article.get("focus_keyword", ""),
                        "_yoast_wpseo_title":      article["title"],
                        "_yoast_wpseo_metadesc":   article.get("meta_description", ""),
                    }
                },
                timeout=10
            )
        except Exception as e:
            print(f"  REST meta 업데이트 오류: {e}")

        # 방법 2: XML-RPC로 post meta 직접 설정
        self._set_meta_xmlrpc(post_id, "rank_math_focus_keyword", focus_keywords_str)

        print(f"  포커스 키워드 설정 시도 완료:")
        for i, kw in enumerate(kws, 1):
            print(f"    {i}. {kw}")

    def _set_meta_xmlrpc(self, post_id: int, meta_key: str, meta_value: str):
        """XML-RPC를 통한 post meta 직접 설정 (REST API 우회)"""
        try:
            import xmlrpc.client
            wp_url  = os.getenv("WP_URL", "").rstrip("/")
            xmlrpc_url = f"{wp_url}/xmlrpc.php"
            username = os.getenv("WP_USERNAME")
            password = os.getenv("WP_APP_PASSWORD", "").replace(" ", "")

            server = xmlrpc.client.ServerProxy(xmlrpc_url)
            # wp.editPost로 custom_fields 업데이트
            server.wp.editPost(
                1, username, password, post_id,
                {"custom_fields": [{"key": meta_key, "value": meta_value}]}
            )
        except Exception as e:
            print(f"  XML-RPC meta 설정 오류 (무시 가능): {e}")

    def publish(self, article: dict, image_data: dict) -> str:
        """
        완성된 글 WordPress에 발행
        Returns: 발행된 포스트 URL
        """
        print(f"  워드프레스 발행 준비 중...")

        # 카테고리 ID 가져오기
        category_id = self.get_category_id("기타정보")
        time.sleep(3)

        # 태그 생성/조회
        tag_ids = self.get_or_create_tags(article.get("tags", []))
        time.sleep(3)

        # 이미지 alt 및 다중 이미지 업로드 처리
        focus_kw = article.get("focus_keyword", "")
        if isinstance(image_data, dict):
            images_list = [image_data]
        elif isinstance(image_data, list):
            images_list = image_data
        else:
            images_list = []

        uploaded_urls = []
        featured_media_id = None

        for i, img in enumerate(images_list):
            if focus_kw:
                img["alt"] = f"{focus_kw} 이미지 {i+1}"
                img["focus_keyword"] = focus_kw
            
            print(f"  [이미지 {i+1}/{len(images_list)}] WordPress 업로드 중...")
            media_id = self.upload_image(img)
            time.sleep(3)  # Rate limiting 대비 대기
            
            if media_id:
                if featured_media_id is None:
                    featured_media_id = media_id
                uploaded_urls.append(img.get("_uploaded_url", ""))
            else:
                uploaded_urls.append("")

        # 본문의 이미지 플레이스홀더를 실제 업로드된 이미지 URL로 교체
        content = article["content"]
        
        # 1. FEATURED_IMAGE 치환
        url_1 = uploaded_urls[0] if len(uploaded_urls) >= 1 else ""
        if url_1:
            content = content.replace('FEATURED_IMAGE', url_1)
        else:
            content = re.sub(r'<figure[^>]*>[\s\S]*?FEATURED_IMAGE[\s\S]*?</figure>', '', content)
            content = re.sub(r'<img[^>]*FEATURED_IMAGE[^>]*/>', '', content)
            content = content.replace('FEATURED_IMAGE', '')

        # 2. BODY_IMAGE_1 치환
        url_2 = uploaded_urls[1] if len(uploaded_urls) >= 2 else ""
        if url_2:
            content = content.replace('BODY_IMAGE_1', url_2)
        else:
            content = re.sub(r'<figure[^>]*>[\s\S]*?BODY_IMAGE_1[\s\S]*?</figure>', '', content)
            content = re.sub(r'<img[^>]*BODY_IMAGE_1[^>]*/>', '', content)
            content = content.replace('BODY_IMAGE_1', '')

        # 3. BODY_IMAGE_2 치환
        url_3 = uploaded_urls[2] if len(uploaded_urls) >= 3 else ""
        if url_3:
            content = content.replace('BODY_IMAGE_2', url_3)
        else:
            content = re.sub(r'<figure[^>]*>[\s\S]*?BODY_IMAGE_2[\s\S]*?</figure>', '', content)
            content = re.sub(r'<img[^>]*BODY_IMAGE_2[^>]*/>', '', content)
            content = content.replace('BODY_IMAGE_2', '')

        # URL 슬러그 설정
        url_slug = article.get("url_slug", "")
        if not url_slug:
            url_slug = focus_kw.replace(" ", "-")[:60]

        # Rank Math 포커스 키워드 (3개, 쉼표 구분)
        focus_keywords_str = article.get(
            "focus_keywords_str",
            article.get("focus_keyword", "")
        )

        # 포스트 데이터 구성
        post_data = {
            "title":          article["title"],
            "content":        content,
            "status":         self.post_status,
            "categories":     [category_id],
            "tags":           tag_ids,
            "excerpt":        "",           # 공란 → 워드프레스 자동 요약
            "slug":           url_slug,
            "comment_status": "closed",     # 댓글 비허용
            "ping_status":    "closed",     # 트랙백/핑백 비허용
            "meta": {
                # Rank Math 포커스 키워드 3개
                "rank_math_focus_keyword":  focus_keywords_str,
                "rank_math_title":          article["title"],
                "rank_math_description":    article.get("meta_description", ""),
                # Yoast 대비
                "_yoast_wpseo_focuskw":     article.get("focus_keyword", ""),
                "_yoast_wpseo_title":       article["title"],
                "_yoast_wpseo_metadesc":    article.get("meta_description", ""),
            }
        }

        if featured_media_id:
            post_data["featured_media"] = featured_media_id

        # 포스트 생성 (이미지 업로드 후 충분히 대기)
        time.sleep(5)
        try:
            response = self._post(
                self._api_url("posts"),
                json=post_data,
                timeout=30
            )

            if response.status_code == 201:
                post = response.json()
                post_id = post["id"]
                post_url = post.get("link", "")

                # Rank Math / Yoast SEO 메타 설정
                self.set_rankmath_seo(post_id, article)

                status_text = "발행" if self.post_status == "publish" else "임시저장"
                print(f"  {status_text} 완료! URL: {post_url}")
                return post_url

            else:
                try:
                    error_msg = response.json().get("message", response.text[:200])
                except Exception:
                    error_msg = response.text[:200] or f"HTTP {response.status_code} (빈 응답)"
                print(f"  포스트 생성 실패 ({response.status_code}): {error_msg}")
                return ""

        except Exception as e:
            print(f"  워드프레스 발행 오류: {e}")
            return ""

    def test_connection(self) -> bool:
        """WordPress 연결 테스트"""
        try:
            response = self._get(self._api_url("users/me"), timeout=10)
            print(f"  [DEBUG] 연결 상태: HTTP {response.status_code}")
            print(f"  [DEBUG] 응답 본문 (100자): {response.text[:100]!r}")
            if response.status_code == 200:
                user = response.json()
                print(f"  WordPress 연결 성공! 사용자: {user.get('name')}")
                return True
            else:
                print(f"  WordPress 연결 실패: {response.status_code}")
                return False
        except Exception as e:
            print(f"  WordPress 연결 오류: {e}")
            return False

    def create_essential_pages(self):
        """애드센스 승인 필수 4대 페이지 자동 생성 (없을 경우에만)"""
        essential_pages = {
            "about-us": {
                "title": "사이트 소개",
                "content": """
<h2>WinOne 매체 소개</h2>
<p>저희 사이트는 일상생활 속에서 꼭 필요한 실용 정보와 팁을 제공하는 신뢰성 있는 전문 정보 플랫폼입니다.</p>
<p>독자 여러분의 일상(Life)과 근로(Worker) 전반에 걸쳐 유용하고 유익한 가이드를 제공하기 위해 항상 정확한 팩트와 최신 정책을 기반으로 글을 발행하고 있습니다.</p>
<h3>핵심 가치</h3>
<ul>
  <li><strong>정확성</strong>: 정부 부처 및 공신력 있는 기관의 공식 데이터를 바탕으로 신뢰할 수 있는 정보만을 다룹니다.</li>
  <li><strong>가독성</strong>: 복잡한 행정 정책이나 금융 용어를 직관적인 표와 요약본으로 재해석하여 누구나 이해하기 쉽게 전달합니다.</li>
  <li><strong>실용성</strong>: 당장 실생활이나 직장 업무에 적용할 수 있는 유익한 팁을 우선으로 발굴합니다.</li>
</ul>
<p>앞으로도 양질의 정보 서비스 제공을 위해 끊임없이 노력하겠습니다. 방문해 주셔서 감사합니다.</p>
"""
            },
            "privacy-policy": {
                "title": "개인정보처리방침",
                "content": """
<h2>개인정보처리방침</h2>
<p>본 사이트는 이용자의 개인정보를 중요시하며, '개인정보 보호법' 등 관련 법령을 준수하고 있습니다. 본 방침은 이용자께서 제공하시는 개인정보가 어떠한 용도와 방식으로 이용되고 있으며, 개인정보보호를 위해 어떠한 조치가 취해지고 있는지 알려드립니다.</p>
<h3>1. 수집하는 개인정보 항목</h3>
<p>본 사이트는 문의 접수, 댓글 작성 등을 위해 아래와 같은 개인정보를 수집할 수 있습니다.</p>
<ul>
  <li>수집 항목: 이름, 이메일 주소, 접속 로그, 쿠키, 접속 IP 정보 등</li>
  <li>수집 방법: 홈페이지 문의 폼 및 댓글 기능 이용 시 자발적 입력</li>
</ul>
<h3>2. 개인정보의 수집 및 이용목적</h3>
<p>수집한 개인정보는 다음의 목적을 위해 활용합니다.</p>
<ul>
  <li>이용자의 문의사항 답변 및 고객 관리</li>
  <li>서비스 이용 통계 분석 및 품질 향상</li>
</ul>
<h3>3. 개인정보의 보유 및 이용기간</h3>
<p>이용자의 개인정보는 원칙적으로 개인정보의 수집 및 이용목적이 달성되면 지체 없이 파기합니다. 단, 관계법령의 규정에 의하여 보존할 필요가 있는 경우 일정 기간 동안 보관합니다.</p>
<h3>4. 제3자 제공 및 위탁</h3>
<p>본 사이트는 이용자의 동의 없이 개인정보를 외부에 제공하거나 위탁하지 않습니다. 단, 법령의 규정에 의거하거나 수사 목적으로 법적 절차에 따라 요구가 있는 경우는 예외로 합니다.</p>
<h3>5. 쿠키(Cookie)의 운용 및 거부</h3>
<p>본 사이트는 방문자에게 맞춤형 서비스를 제공하기 위해 쿠키를 사용할 수 있습니다. 이용자는 웹 브라우저 설정을 통해 쿠키 지정을 거부하거나 삭제할 수 있습니다.</p>
"""
            },
            "terms": {
                "title": "이용약관",
                "content": """
<h2>이용약관</h2>
<h3>제1조 (목적)</h3>
<p>본 약관은 본 웹사이트(이하 '사이트')가 제공하는 모든 정보 및 서비스의 이용조건과 절차, 이용자와 사이트 간의 권리, 의무 및 책임 사항을 규정함을 목적으로 합니다.</p>
<h3>제2조 (이용의 제한 및 책임)</h3>
<p>1. 이용자는 본 사이트가 제공하는 정보를 자유롭게 이용할 수 있으나, 상업적인 목적으로 무단 복제, 배포 또는 도용하는 행위는 금지됩니다.</p>
<p>2. 사이트 내에 수록된 정보는 최대한 신뢰할 수 있는 자료를 바탕으로 작성되었으나, 시점의 경과나 법령 개정 등으로 인해 실제와 다를 수 있으므로 이용자 본인의 중요한 결정 시 반드시 공식 대조를 하시기 바랍니다. 본 사이트의 정보를 신뢰하여 발생한 직/간접적인 결과에 대해 사이트 운영자는 법적 책임을 지지 않습니다.</p>
<h3>제3조 (서비스의 변경 및 중단)</h3>
<p>본 사이트는 사전 고지 없이 사이트의 구성, 정보 제공 범위, 주소를 변경하거나 일시적으로 서비스를 중단할 수 있습니다.</p>
<h3>제4조 (관할 법원)</h3>
<p>본 서비스 이용과 관련하여 발생한 분쟁에 대해서는 사이트 운영자의 소재지를 관할하는 법원을 전담 관할 법원으로 합니다.</p>
"""
            },
            "contact": {
                "title": "문의하기",
                "content": """
<h2>문의하기</h2>
<p>저희 사이트의 콘텐츠 제휴, 오탈자 제보, 정보 오류 수정 요청, 혹은 광고 문의가 있으신 경우 아래 연락처로 메일을 보내주시기 바랍니다.</p>
<div style="background:#f8f9fa;border:1px solid #dee2e6;padding:15px;margin:20px 0;border-radius:6px;">
  <strong>📧 이메일 문의처</strong><br>
  이메일: <a href="mailto:mignito89@gmail.com">mignito89@gmail.com</a><br>
  (영업일 기준 2~3일 이내에 회신해 드립니다.)
</div>
<p>더 유익하고 정확한 직장인 및 일상 정보를 전달하기 위해 독자분들의 소중한 의견을 적극 반영하겠습니다. 감사합니다.</p>
"""
            }
        }

        print("\n[자가진단] 애드센스 승인 필수 정적 페이지 검사 중...")
        for slug, page_info in essential_pages.items():
            try:
                # 1. 페이지 조회 (slug로 확인)
                response = self._get(
                    f"{self.wp_url}/wp-json/wp/v2/pages",
                    params={"slug": slug, "status": "any"},
                    timeout=10
                )
                if response.status_code == 200:
                    pages = response.json()
                    if pages and len(pages) > 0:
                        p = pages[0]
                        if p.get("status") != "publish":
                            # 임시저장(draft)인 경우 공개 발행(publish)으로 전환
                            print(f"  → 발견: '{page_info['title']}' ({slug}) - 임시저장 상태 → 발행 상태로 공개 전환 중...")
                            self._post(
                                f"{self.wp_url}/wp-json/wp/v2/pages/{p['id']}",
                                json={"status": "publish"},
                                timeout=10
                            )
                        else:
                            print(f"  [OK] 이미 존재함: '{page_info['title']}' ({p.get('link')})")
                        continue
                
                # 2. 존재하지 않으면 생성
                print(f"  → 누락: '{page_info['title']}' ({slug}) 페이지 생성 중...")
                create_data = {
                    "title": page_info["title"],
                    "content": page_info["content"],
                    "status": "publish",
                    "slug": slug,
                    "comment_status": "closed",
                    "ping_status": "closed"
                }
                
                resp = self._post(
                    f"{self.wp_url}/wp-json/wp/v2/pages",
                    json=create_data,
                    timeout=15
                )
                if resp.status_code == 201:
                    print(f"    ✓ 생성 및 발행 완료: {resp.json().get('link')}")
                else:
                    print(f"    ❌ 생성 실패 (HTTP {resp.status_code}): {resp.text[:100]}")
                time.sleep(2)
            except Exception as e:
                print(f"  '{page_info['title']}' 페이지 처리 중 오류 (무시하고 계속): {e}")
