# WordPress 자동 블로그 세팅 가이드

## 1단계: API 키 발급

### Gemini API (필수)
1. https://aistudio.google.com/ 접속
2. 회원가입 → API 키 발급 (Create API Key)

### Pexels API (무료 이미지)
1. https://www.pexels.com/api/ 접속
2. 회원가입 → Your API Key 복사

### Naver DataLab API (선택, 무료)
1. https://developers.naver.com 접속
2. Application 등록
3. 사용 API: "데이터랩 검색어통계" 체크
4. Client ID / Client Secret 복사

### WordPress 앱 비밀번호
1. 워드프레스 관리자 → 사용자 → 프로필
2. 맨 아래 "애플리케이션 비밀번호" 섹션
3. 이름: "AutoBlog" → 추가
4. 생성된 비밀번호 복사 (공백 포함해서 저장)

---

## 2단계: 로컬 설정

```bash
# 프로젝트 폴더로 이동
cd wp-auto-blog

# .env 파일 생성
cp .env.example .env

# .env 파일 열어서 API 키 입력
notepad .env

# 패키지 설치
pip install -r requirements.txt

# 연결 테스트
python main.py --test

# 글 생성 미리보기 (발행 안 함)
python main.py --dry

# 실제 발행 (임시저장)
python main.py
```

---

## 3단계: GitHub Actions 자동화

1. GitHub에 새 비공개 저장소 생성 (Private)
2. 이 폴더 전체를 업로드
3. Settings → Secrets → Actions → New repository secret

| Secret 이름 | 값 |
|-------------|-----|
| GEMINI_API_KEY | Gemini API 키 |
| PEXELS_API_KEY | Pexels API 키 |
| NAVER_CLIENT_ID | 네이버 Client ID |
| NAVER_CLIENT_SECRET | 네이버 Client Secret |
| WP_URL | https://winone-life.com |
| WP_USERNAME | 워드프레스 아이디 |
| WP_APP_PASSWORD | 앱 비밀번호 |

4. Actions 탭 → "매일 자동 블로그 포스팅" → Enable

이후 매일 오전 9시에 자동 실행됩니다.

---

## 워드프레스 카테고리 ID 설정

`src/wordpress_publisher.py` 파일의 CATEGORY_IDS를 실제 ID로 수정:

```python
CATEGORY_IDS = {
    "금융": 2,      # 실제 카테고리 ID로 변경
    "의학/건강": 3,
    "생활정보": 4,
}
```

카테고리 ID 확인: 워드프레스 관리자 → 글 → 카테고리 → 해당 카테고리 클릭 → URL의 tag_ID= 숫자

---

## 수동으로 특정 키워드 발행

```bash
python main.py --keyword "실손보험 청구방법" --category "금융"
python main.py --keyword "당뇨 초기증상" --category "의학/건강"
```

---

## 하나의 폴더에서 두 개의 사이트 관리하기 (Dual Site)

이 프로젝트는 하나의 폴더(Repo)에서 `winone-life.com`과 `winone-worker.com` 두 사이트를 편리하게 동시 관리할 수 있습니다.

1. **설정 파일 준비**:
   - `winone-life.com` 설정: `.env` 파일에 작성 (기본)
   - `winone-worker.com` 설정: `.env.worker` 파일에 작성 (기존 `.env`를 복사한 후 `WP_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` 항목만 `winone-worker.com` 계정 정보로 변경하여 생성)
2. **실행 명령어**:
   - `winone-life.com` 사이트 발행:
     ```bash
     python main.py --site life
     ```
   - `winone-worker.com` 사이트 발행:
     ```bash
     python main.py --site worker
     ```

---

## 발행 로그 확인

`logs/` 폴더에 월별 로그가 저장됩니다.

---

## 문제 해결

**WordPress 401 오류**: 앱 비밀번호 재발급, WP_USERNAME 확인
**이미지 업로드 실패**: 카페24 파일 업로드 용량 제한 확인
**Gemini API 오류**: API 키 및 할당량/잔액 확인
