"""
트렌드 키워드 탐색 모듈
- Google Trends (pytrends) + Naver DataLab API 조합
- 금융/의학/건강 카테고리 자동 선별
"""

import os
import json
import random
import requests
import time
from datetime import datetime, timedelta
from pytrends.request import TrendReq


# 탐색할 시드 키워드 목록 (금융/의학/건강/생활 트래픽 높은 분야)
SEED_KEYWORDS = {
    "금융": [
        # 대출 관련 실제 검색어
        "신용대출 금리 낮추는 방법", "주택담보대출 한도 계산",
        "전세자금대출 조건 2026", "소상공인 대출 신청방법",
        "햇살론 신청 자격 조건", "카드론 이자 줄이는 방법",
        # 보험 실제 검색어
        "실손보험 청구 방법 총정리", "실손보험 안되는 항목",
        "암보험 가입 전 확인사항", "자동차보험 할인 받는 방법",
        # 세금/절세 실제 검색어
        "연말정산 환급금 늘리는 방법", "종합소득세 절세 방법",
        "상속세 절세 방법 2026", "증여세 면제 한도 기준",
        "부동산 양도소득세 줄이는 방법",
        # 투자/저축 실제 검색어
        "ISA 계좌 가입 방법 혜택", "IRP 세액공제 한도",
        "ETF 투자 초보 시작 방법", "청약통장 1순위 조건",
        # 신용 관련
        "신용점수 올리는 방법 빠르게", "개인회생 신청 자격 조건",
        "채무조정 신청 방법 절차"
    ],
    "의학/건강": [
        # 질환별 실제 검색어
        "당뇨 초기증상 확인 방법", "고혈압 낮추는 생활습관",
        "고지혈증 콜레스테롤 낮추는 음식", "역류성식도염 치료 방법",
        "갑상선 기능저하증 증상 원인", "허리디스크 자가 치료법",
        "무릎 관절염 통증 완화 방법", "불면증 해결 방법 꿀팁",
        # 건강관리 실제 검색어
        "혈당 정상수치 관리 방법", "내장지방 빼는 방법 빠르게",
        "탈모 예방 방법 초기 대응", "피부 아토피 원인 치료법",
        "갱년기 증상 완화 방법", "골다공증 예방 칼슘 섭취",
        # 의료비 실제 검색어
        "실손보험 청구 안되는 경우", "건강검진 항목 나이별 정리",
        "MRI 비용 건강보험 적용", "약 부작용 확인 방법",
        "한방 치료 건강보험 적용 항목"
    ],
    "생활정보": [
        # 정부지원 실제 검색어
        "2026년 청년 지원금 신청 방법", "실업급여 신청 자격 조건",
        "육아휴직 급여 신청 방법", "출산지원금 신청 총정리",
        "에너지바우처 신청 대상 방법", "근로장려금 신청 조건",
        # 생활비 절약 실제 검색어
        "전기세 절약 방법 꿀팁", "자동차보험 저렴하게 가입하는 법",
        "관리비 줄이는 방법 아파트", "통신비 절약 알뜰폰 비교",
        # 기타 실제 검색어
        "운전면허 갱신 방법 준비물", "주민등록증 재발급 방법",
        "여권 갱신 신청 방법 비용", "교통위반 벌점 조회 방법"
    ]
}

# 영문 키워드 매핑 (Pexels 이미지 검색용)
KEYWORD_TO_ENGLISH = {
    "금융": "finance money",
    "의학/건강": "healthcare medical",
    "생활정보": "lifestyle information",
    "대출": "loan finance",
    "보험": "insurance",
    "ETF": "stock market investment",
    "당뇨": "diabetes healthcare",
    "고혈압": "blood pressure health",
    "탈모": "hair loss treatment",
    "다이어트": "diet healthy food",
    "정부지원금": "government support",
}


class TrendFinder:
    def __init__(self):
        self.naver_client_id = os.getenv("NAVER_CLIENT_ID")
        self.naver_client_secret = os.getenv("NAVER_CLIENT_SECRET")
        self.pytrends = TrendReq(hl='ko-KR', tz=540)  # 한국 시간대

    def get_google_trend_score(self, keyword: str) -> int:
        """Google Trends에서 키워드 관심도 점수 가져오기"""
        for attempt in range(2):
            try:
                self.pytrends.build_payload(
                    kw_list=[keyword],
                    cat=0,
                    timeframe='now 7-d',
                    geo='KR'
                )
                data = self.pytrends.interest_over_time()
                if data.empty:
                    return random.randint(20, 60)
                score = int(data[keyword].mean())
                time.sleep(3)  # 레이트 제한 방지 (3초)
                return score
            except Exception as e:
                err_str = str(e)
                if "429" in err_str:
                    if attempt == 0:
                        print(f"  Google Trends 429 제한 → 15초 대기 후 재시도...")
                        time.sleep(15)
                    else:
                        print(f"  Google Trends 429 재시도 실패 → 랜덤 점수 사용")
                        return random.randint(20, 60)
                else:
                    print(f"Google Trends 오류 ({keyword}): {e}")
                    return random.randint(20, 60)
        return random.randint(20, 60)

    def get_naver_search_volume(self, keyword: str) -> dict:
        """Naver DataLab에서 키워드 검색량 가져오기"""
        if not self.naver_client_id or not self.naver_client_secret:
            return {"ratio": random.randint(20, 80)}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        url = "https://openapi.naver.com/v1/datalab/search"
        headers = {
            "X-Naver-Client-Id": self.naver_client_id,
            "X-Naver-Client-Secret": self.naver_client_secret,
            "Content-Type": "application/json"
        }
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": "week",
            "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
        }

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [{}])[0].get("data", [])
                if results:
                    avg_ratio = sum(r["ratio"] for r in results) / len(results)
                    return {"ratio": avg_ratio}
            return {"ratio": 0}
        except Exception as e:
            print(f"Naver DataLab 오류 ({keyword}): {e}")
            return {"ratio": random.randint(20, 80)}

    def get_rising_queries(self) -> list:
        """Google Trends 급상승 검색어 가져오기"""
        try:
            rising = self.pytrends.trending_searches(pn='south_korea')
            return rising[0].tolist()[:10]
        except:
            return []

    def find_ranked_keywords(self) -> list:
        """
        트렌드 점수 순위 리스트 반환 (중복 방지용)
        Returns: [{keyword, category, google_score, naver_ratio, keyword_en}, ...]
        """
        print("트렌드 키워드 탐색 중...")

        # 급상승 검색어도 체크
        rising = self.get_rising_queries()
        print(f"Google 급상승: {rising[:5]}")

        # 각 카테고리에서 랜덤으로 후보 선별
        candidates = []
        for category, keywords in SEED_KEYWORDS.items():
            sample = random.sample(keywords, min(4, len(keywords)))
            for kw in sample:
                candidates.append({"keyword": kw, "category": category})

        # 급상승 키워드 중 관련 있는 것 추가
        finance_medical_terms = set()
        for kws in SEED_KEYWORDS.values():
            finance_medical_terms.update(kws)

        for rising_kw in rising:
            for seed in finance_medical_terms:
                if seed in rising_kw or rising_kw in seed:
                    category = next(
                        (cat for cat, kws in SEED_KEYWORDS.items() if seed in kws),
                        "생활정보"
                    )
                    candidates.append({"keyword": rising_kw, "category": category})
                    break

        # 점수 계산 (상위 후보만 실제 API 호출)
        scored = []
        sample_candidates = random.sample(candidates, min(6, len(candidates)))

        for item in sample_candidates:
            kw = item["keyword"]
            print(f"  점수 계산 중: {kw}")
            google_score = self.get_google_trend_score(kw)
            naver_data = self.get_naver_search_volume(kw)
            naver_ratio = naver_data.get("ratio", 0)

            total_score = (google_score * 0.5) + (naver_ratio * 0.5)
            scored.append({
                "keyword": kw,
                "category": item["category"],
                "google_score": google_score,
                "naver_ratio": naver_ratio,
                "total_score": total_score
            })
            time.sleep(0.5)

        # 점수 기준 정렬
        scored.sort(key=lambda x: x["total_score"], reverse=True)

        # 영문 키워드 매핑 (이미지 검색용)
        for item in scored:
            item["keyword_en"] = KEYWORD_TO_ENGLISH.get(
                item["keyword"],
                KEYWORD_TO_ENGLISH.get(item["category"], "finance health")
            )

        print(f"트렌드 후보 순위:")
        for i, item in enumerate(scored[:5], 1):
            print(f"  {i}위: {item['keyword']} (점수: {item['total_score']:.1f})")

        return scored

    def find_best_keyword(self) -> dict:
        """하위 호환용 - 1위 키워드만 반환"""
        return self.find_ranked_keywords()[0]
