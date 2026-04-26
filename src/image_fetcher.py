"""
이미지 가져오기 모듈
우선순위: Pexels → Pixabay → Picsum(항상 성공)
"""

import os
import requests
import random
import hashlib


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
    def get_image(self, keyword_en: str, category: str = None) -> dict:
        category = category or "생활정보"
        query = keyword_en.strip() if keyword_en else ""

        # 1순위: Pexels
        if self.pexels_key:
            print("  Pexels 이미지 검색 중...")
            result = self._pexels(query, category)
            if result:
                print(f"  ✓ Pexels 이미지 선택 ({result['photographer']})")
                return result

        # 2순위: Pixabay
        if self.pixabay_key:
            print("  Pixabay 이미지 검색 중...")
            result = self._pixabay(query, category)
            if result:
                print(f"  ✓ Pixabay 이미지 선택 ({result['photographer']})")
                return result

        # 3순위: Picsum (항상 성공)
        print("  Picsum 이미지 사용 중...")
        result = self._picsum(query or category)
        print("  ✓ Picsum 이미지 선택 완료")
        return result

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
