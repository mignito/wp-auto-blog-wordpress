"""
이미지 가져오기 모듈
우선순위: Imagen (나노바나나) → Pexels → Pixabay → Picsum(항상 성공)
"""

import os
import requests
import random
import hashlib
from datetime import datetime


# 카테고리별 검색어
QUERIES = {
    "금융": ["finance money", "banking investment", "money saving", "financial planning"],
    "의학/건강": ["healthcare wellness", "healthy lifestyle", "medical health", "fitness nutrition"],
    "생활정보": ["daily lifestyle", "family home", "community people", "modern living"],
}

EXCLUDED = ["surgery", "blood", "injection", "needle", "operation"]


class ImageFetcher:
    def __init__(self):
        self.pexels_key  = os.getenv("PEXELS_API_KEY")
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "")  # 선택사항
        self.gemini_key  = os.getenv("GEMINI_API_KEY")
        self.client      = None
        if self.gemini_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.gemini_key)
            except Exception as e:
                print(f"  [경고] Google GenAI SDK 로드 실패: {e}")

    # ── 1순위: Pexels ────────────────────────────────────
    def _pexels(self, query: str, category: str) -> dict | None:
        if not self.pexels_key:
            return None

        search_query = query or random.choice(QUERIES.get(category, ["lifestyle"]))

        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": self.pexels_key},
                params={"query": search_query, "per_page": 10,
                        "orientation": "landscape", "size": "medium"},
                timeout=15
            )
            if resp.status_code == 200:
                photos = resp.json().get("photos", [])
                photos = [p for p in photos if not any(
                    kw in p.get("alt", "").lower() for kw in EXCLUDED
                )]
                if photos:
                    p = random.choice(photos[:5])
                    return {
                        "medium_url":   p["src"]["medium"],
                        "url":          p["src"]["large"],
                        "photographer": p.get("photographer", "Pexels"),
                        "alt":          p.get("alt", search_query),
                        "source":       "Pexels"
                    }
            else:
                print(f"  Pexels 응답 오류: {resp.status_code}")
        except Exception as e:
            print(f"  Pexels 연결 오류: {e}")
        return None

    # ── 2순위: Pixabay ───────────────────────────────────
    def _pixabay(self, query: str, category: str) -> dict | None:
        if not self.pixabay_key:
            return None

        search_query = query or random.choice(QUERIES.get(category, ["lifestyle"]))

        try:
            resp = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key":        self.pixabay_key,
                    "q":          search_query,
                    "image_type": "photo",
                    "orientation":"horizontal",
                    "per_page":   10,
                    "safesearch": "true"
                },
                timeout=15
            )
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])
                if hits:
                    h = random.choice(hits[:5])
                    return {
                        "medium_url":   h.get("webformatURL"),
                        "url":          h.get("largeImageURL"),
                        "photographer": h.get("user", "Pixabay"),
                        "alt":          search_query,
                        "source":       "Pixabay"
                    }
        except Exception as e:
            print(f"  Pixabay 오류: {e}")
        return None

    # ── 3순위: Picsum (항상 성공, API 키 불필요) ─────────
    def _picsum(self, keyword: str) -> dict:
        """
        Lorem Picsum - 항상 작동하는 무료 이미지
        keyword 기반 seed로 글마다 다른 이미지
        """
        seed = int(hashlib.md5(keyword.encode()).hexdigest(), 16) % 1000
        url = f"https://picsum.photos/seed/{seed}/800/450"
        return {
            "medium_url":   url,
            "url":          url,
            "photographer": "Lorem Picsum",
            "alt":          f"{keyword} 관련 이미지",
            "source":       "Picsum"
        }

    # ── 공개 API ────────────────────────────────────────
    def get_image(self, keyword_en: str, category: str = None, keyword_ko: str = "") -> dict:
        """하위 호환성을 위한 단일 이미지 가져오기"""
        images = self.get_images(keyword_en, category, keyword_ko, count=1)
        return images[0]

    def _pexels_multi(self, query: str, category: str, count: int = 3) -> list:
        if not self.pexels_key:
            return []
        search_query = query or random.choice(QUERIES.get(category, ["lifestyle"]))
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": self.pexels_key},
                params={"query": search_query, "per_page": 20,
                        "orientation": "landscape", "size": "medium"},
                timeout=15
            )
            if resp.status_code == 200:
                photos = resp.json().get("photos", [])
                photos = [p for p in photos if not any(
                    kw in p.get("alt", "").lower() for kw in EXCLUDED
                )]
                if len(photos) >= count:
                    selected = random.sample(photos, count)
                else:
                    selected = photos
                results = []
                for p in selected:
                    results.append({
                        "medium_url":   p["src"]["medium"],
                        "url":          p["src"]["large"],
                        "photographer": p.get("photographer", "Pexels"),
                        "alt":          p.get("alt", search_query),
                        "source":       "Pexels"
                    })
                return results
            else:
                print(f"  Pexels 응답 오류: {resp.status_code}")
        except Exception as e:
            print(f"  Pexels 연결 오류: {e}")
        return []

    def _pixabay_multi(self, query: str, category: str, count: int = 3) -> list:
        if not self.pixabay_key:
            return []
        search_query = query or random.choice(QUERIES.get(category, ["lifestyle"]))
        try:
            resp = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key":        self.pixabay_key,
                    "q":          search_query,
                    "image_type": "photo",
                    "orientation":"horizontal",
                    "per_page":   20,
                    "safesearch": "true"
                },
                timeout=15
            )
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])
                if len(hits) >= count:
                    selected = random.sample(hits, count)
                else:
                    selected = hits
                results = []
                for h in selected:
                    results.append({
                        "medium_url":   h.get("webformatURL"),
                        "url":          h.get("largeImageURL"),
                        "photographer": h.get("user", "Pixabay"),
                        "alt":          search_query,
                        "source":       "Pixabay"
                    })
                return results
        except Exception as e:
            print(f"  Pixabay 오류: {e}")
        return []

    def _picsum_multi(self, keyword: str, count: int = 3) -> list:
        results = []
        base_seed = int(hashlib.md5(keyword.encode()).hexdigest(), 16) % 1000
        for i in range(count):
            seed = (base_seed + i * 137) % 1000
            url = f"https://picsum.photos/seed/{seed}/800/450"
            results.append({
                "medium_url":   url,
                "url":          url,
                "photographer": f"Lorem Picsum {i+1}",
                "alt":          f"{keyword} 관련 이미지 {i+1}",
                "source":       "Picsum"
            })
        return results

    def _fill_missing_with_picsum(self, results: list, keyword: str, count: int) -> list:
        needed = count - len(results)
        if needed <= 0:
            return results
        picsums = self._picsum_multi(keyword, count)
        for i in range(needed):
            results.append(picsums[i])
        return results

    def get_images(self, keyword_en: str, category: str = None, keyword_ko: str = "", count: int = 3) -> list:
        """지정한 개수만큼 서로 다른 이미지 가져오기 (Imagen 우선, 스톡 이미지 대체)"""
        category = category or "생활정보"
        query = keyword_en.strip() if keyword_en else ""
        keyword_display = keyword_ko.strip() if keyword_ko else query

        # 1순위: 나노바나나 (Gemini Imagen)
        if self.client:
            print(f"  나노바나나(Imagen)로 '{keyword_display}' 관련 이미지 {count}개 생성 중...")
            prompt = (
                f"A high-quality, professional, clean photography representing '{query}' in the theme of '{category}'. "
                f"Sleek and modern, commercial photography style, 16:9 aspect ratio, no text, no watermark, highly detailed."
            )
            try:
                result = self.client.models.generate_images(
                    model='imagen-4.0-generate-001',
                    prompt=prompt,
                    config=dict(
                        number_of_images=count,
                        aspect_ratio='16:9',
                        output_mime_type='image/png'
                    )
                )
                if result.generated_images and len(result.generated_images) >= count:
                    os.makedirs("images", exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    images_list = []
                    for i, gen_img in enumerate(result.generated_images):
                        save_path = f"images/generated_{timestamp}_{i+1}.png"
                        with open(save_path, "wb") as f:
                            f.write(gen_img.image.image_bytes)
                        images_list.append({
                            "local_path": save_path,
                            "photographer": "Gemini Imagen",
                            "alt": f"{keyword_display} 관련 이미지 {i+1}",
                            "source": "나노바나나 (Imagen)"
                        })
                    print(f"  ✓ 나노바나나 이미지 {len(images_list)}개 생성 완료")
                    return images_list
            except Exception as e:
                print(f"  나노바나나 이미지 생성 실패 ({e}) → 기존 스톡 이미지 Fallback 적용")

        # 2순위: Pexels
        results = []
        if self.pexels_key:
            print("  Pexels 이미지 검색 중...")
            results = self._pexels_multi(query, category, count)
            if len(results) >= count:
                print(f"  [OK] Pexels 이미지 {len(results)}개 선택 완료")
                return results
            elif results:
                print(f"  Pexels에서 {len(results)}개 획득 (목표 {count}개 미달) → Pixabay/Picsum으로 보충 시도")

        # 3순위: Pixabay
        if self.pixabay_key:
            print("  Pixabay 이미지 검색 중...")
            pix_results = self._pixabay_multi(query, category, count)
            if len(pix_results) >= count:
                print(f"  [OK] Pixabay 이미지 {len(pix_results)}개 선택 완료")
                return pix_results
            elif pix_results and not results:
                results = pix_results

        # 4순위: Picsum (항상 성공)
        if not results:
            results = []
        results = self._fill_missing_with_picsum(results, query or category, count)
        print(f"  [OK] 이미지 {len(results)}개 최종 매핑 완료 (Picsum 포함)")
        return results

    def download_image(self, image_data: dict, save_path: str) -> bool:
        """이미지 다운로드 후 로컬 저장"""
        url = image_data.get("medium_url") or image_data.get("url")
        if not url:
            return False
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                return True
            else:
                print(f"  이미지 응답 오류: {resp.status_code}, 크기: {len(resp.content)}")
        except Exception as e:
            print(f"  이미지 다운로드 오류: {e}")
        return False
