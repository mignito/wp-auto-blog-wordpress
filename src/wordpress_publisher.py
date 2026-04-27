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
        if not image_url:
            return None

        try:
            # 이미지 다운로드
            img_response = requests.get(image_url, timeout=30)
            if img_response.status_code != 200:
                return None

            # 파일명 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"featured_{timestamp}.jpg"

            # WordPress에 업로드 - multipart/form-data 방식 (WAF 우회)
            # Content-Type을 None으로 설정해 세션 기본값(application/json)을 제거
            # → requests가 multipart boundary를 자동으로 설정하게 함
            for attempt in range(3):
                files = {"file": (filename, img_response.content, "image/jpeg")}
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

        # 이미지 alt에 포커스 키워드 설정
        focus_kw = article.get("focus_keyword", "")
        if focus_kw:
            image_data["alt"] = f"{focus_kw} 이미지"
            image_data["focus_keyword"] = focus_kw

        # 이미지 업로드 (업로드 후 image_data["_uploaded_url"] 에 실제 URL 저장됨)
        featured_media_id = self.upload_image(image_data)

        # 본문의 FEATURED_IMAGE 플레이스홀더를 실제 업로드된 이미지 URL로 교체
        content = article["content"]
        uploaded_url = image_data.get("_uploaded_url", "")
        if uploaded_url:
            img_tag = (
                f'<figure style="margin:20px 0;text-align:center;">'
                f'<img src="{uploaded_url}" alt="{focus_kw} 이미지" '
                f'style="max-width:100%;height:auto;border-radius:8px;" />'
                f'<figcaption style="font-size:12px;color:#888;margin-top:6px;">'
                f'{focus_kw} 관련 이미지</figcaption></figure>'
            )
            content = content.replace('<img src="FEATURED_IMAGE"', f'<img src="{uploaded_url}"')
            # 이미지가 figure로 감싸지지 않았다면 교체
            if 'FEATURED_IMAGE' in content:
                content = content.replace('FEATURED_IMAGE', uploaded_url)
        else:
            # 업로드 실패 시 플레이스홀더 제거
            content = re.sub(r'<img src="FEATURED_IMAGE"[^>]*/>', '', content)

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
