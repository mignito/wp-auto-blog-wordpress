"""
WordPress 자동 블로그 포스팅 - 메인 실행 파일
사용법:
  python main.py          # 일반 실행 (트렌드 탐색 → 글 생성 → 발행)
  python main.py --test   # WordPress 연결 테스트만
  python main.py --dry    # 글만 생성, 발행 안 함 (내용 확인용)
"""

import os
import sys
import json
import argparse
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

# 한글/특수문자 콘솔 출력 보장 (cp949 인코딩 오류 방지)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# --site 인자 확인하여 해당하는 환경 설정 로드
site = "life"
for i, arg in enumerate(sys.argv):
    if arg == "--site" and i + 1 < len(sys.argv):
        site = sys.argv[i + 1]
    elif arg.startswith("--site="):
        site = arg.split("=")[1]

# 기본 .env 로드 (공용 API 키 포함)
load_dotenv()

# 사이트가 worker인 경우 .env.worker로 덮어쓰기
if site == "worker":
    if os.path.exists(".env.worker"):
        print("  [안내] winone-worker.com 설정(.env.worker) 로드 중...")
        load_dotenv(".env.worker", override=True)
    else:
        print("  [경고] .env.worker 파일이 존재하지 않아 기본 .env 설정을 사용합니다.")

# src 폴더 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from trend_finder import TrendFinder
from content_generator import ContentGenerator
from image_fetcher import ImageFetcher
from wordpress_publisher import WordPressPublisher


def get_recent_post_keywords(count: int = 5) -> list:
    """
    WordPress에서 최근 발행된 글의 키워드/제목 목록을 가져옴
    중복 주제 방지에 사용
    """
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
            params={"per_page": count, "status": "publish", "orderby": "date"},
            timeout=10
        )
        if resp.status_code == 200:
            posts = resp.json()
            keywords = []
            for post in posts:
                title = post.get("title", {}).get("rendered", "")
                # 태그도 가져오기 위해 tags 필드 확인
                tags_ids = post.get("tags", [])
                keywords.append(title)
            print(f"  최근 {len(keywords)}개 글 제목 확인 완료")
            return keywords
    except Exception as e:
        print(f"  최근 글 확인 오류 (무시하고 계속): {e}")
    return []


def is_duplicate_topic(keyword: str, recent_titles: list) -> bool:
    """
    키워드가 최근 글 제목과 주제가 겹치는지 확인
    핵심 명사 2개 이상 겹치면 중복으로 판단
    """
    if not recent_titles:
        return False

    # 키워드에서 의미 있는 단어 추출 (2글자 이상)
    kw_words = set(w for w in keyword.split() if len(w) >= 2)

    for title in recent_titles:
        # 제목에서 의미 있는 단어 추출
        title_words = set(w for w in title.replace("-", " ").split() if len(w) >= 2)
        overlap = kw_words & title_words
        # 2개 이상 단어가 겹치면 중복 주제로 판단
        if len(overlap) >= 2:
            print(f"  [!] 중복 주제 감지: '{keyword}' - '{title}' (겹치는 단어: {overlap})")
            return True
    return False


def check_env_vars():
    """필수 환경변수 확인"""
    required = ["GEMINI_API_KEY", "WP_URL", "WP_USERNAME", "WP_APP_PASSWORD"]
    optional = ["PEXELS_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]

    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"오류: 다음 환경변수가 설정되지 않았습니다: {', '.join(missing)}")
        print(".env 파일을 확인해주세요. (.env.example 참고)")
        sys.exit(1)

    missing_optional = [v for v in optional if not os.getenv(v)]
    if missing_optional:
        print(f"참고: 선택 환경변수 미설정 (일부 기능 제한): {', '.join(missing_optional)}")


def save_article_log(keyword_data: dict, article: dict, post_url: str):
    """발행 로그 저장"""
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/{datetime.now().strftime('%Y-%m')}_posts.jsonl"

    log_entry = {
        "date": datetime.now().isoformat(),
        "keyword": keyword_data["keyword"],
        "category": keyword_data["category"],
        "title": article["title"],
        "post_url": post_url,
        "tags": article.get("tags", []),
        "google_score": keyword_data.get("google_score", 0),
        "naver_ratio": keyword_data.get("naver_ratio", 0)
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

def check_sitemap():
    """사이트맵 활성화 자가진단"""
    wp_url = os.getenv("WP_URL", "").rstrip("/")
    sitemaps = [f"{wp_url}/sitemap.xml", f"{wp_url}/sitemap_index.xml"]
    print("\n[자가진단] 사이트맵 활성화 검사 중...")
    
    found = False
    for url in sitemaps:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=10)
            if resp.status_code == 200:
                print(f"  [OK] 사이트맵 주소 발견: {url} (HTTP 200)")
                found = True
                break
        except Exception as e:
            pass
            
    if not found:
        print("  [경고] 사이트맵(sitemap.xml 또는 sitemap_index.xml)이 감지되지 않았습니다.")
        print("  → 구글 애드센스 승인을 위해 Rank Math 또는 Yoast SEO 플러그인 설정에서 XML 사이트맵이 활성화되어 있는지 확인해 주세요.")


def delete_old_media(publisher, days_to_keep: int = 7):
    """
    WordPress에서 days_to_keep(기본 7일)이 경과한 미디어 파일을 조회하여
    영구 삭제(force=true) 처리하는 로직 (디스크 공간 절약용)
    """
    try:
        from datetime import datetime, timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        before_iso = cutoff_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        print(f"\n[미디어 정리] {days_to_keep}일이 경과한 오래된 미디어 파일 정리 중...")

        # publisher의 _get 메서드를 사용하여 챌린지 쿠키가 탑재된 세션으로 요청
        resp = publisher._get(
            publisher._api_url("media"),
            params={"before": before_iso, "per_page": 50, "_fields": "id,date"},
            timeout=15
        )
        
        if resp.status_code == 200:
            media_list = resp.json()
            if media_list and isinstance(media_list, list):
                print(f"  발견된 정리 대상 미디어: {len(media_list)}개")
                for item in media_list:
                    media_id = item.get("id")
                    try:
                        # publisher의 session을 사용해 force=true로 영구 삭제
                        del_resp = publisher.session.delete(
                            publisher._api_url(f"media/{media_id}"),
                            params={"force": "true"},
                            timeout=10
                        )
                        if del_resp.status_code == 200:
                            print(f"  [성공] 미디어 #{media_id} 영구 삭제 완료")
                    except Exception as e:
                        print(f"  [경고] 미디어 #{media_id} 삭제 시도 실패: {e}")
            else:
                print("  정리 대상 미디어가 없습니다.")
        else:
            print(f"  미디어 조회 실패 (HTTP {resp.status_code})")
    except Exception as e:
        print(f"  [경고] 오래된 미디어 삭제 정리 실패 (무시하고 계속): {e}")


def main():
    parser = argparse.ArgumentParser(description="WordPress 자동 블로그 포스팅")
    parser.add_argument("--site", type=str, default="life", choices=["life", "worker"], help="대상 사이트 지정 (life 또는 worker)")
    parser.add_argument("--test", action="store_true", help="연결 테스트만 실행")
    parser.add_argument("--dry", action="store_true", help="글 생성만 하고 발행 안 함")
    parser.add_argument("--test-post", action="store_true", help="더미 글로 WordPress 발행만 테스트 (AI API 미사용)")
    parser.add_argument("--keyword", type=str, help="직접 키워드 지정 (트렌드 탐색 건너뜀)")
    parser.add_argument("--category", type=str, default="금융", help="카테고리 지정 (keyword 옵션 사용 시)")
    args = parser.parse_args()

    print("=" * 50)
    print(f"WordPress 자동 포스팅 시작 (사이트: {args.site}): {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    check_env_vars()

    # WordPress 연결 사전 확인 (이 인스턴스를 발행에도 재사용)
    print("\n[사전 확인] WordPress 연결 테스트")
    publisher = WordPressPublisher()
    if not publisher.test_connection():
        print("  WordPress 연결 실패 - 환경변수(WP_URL, WP_USERNAME, WP_APP_PASSWORD)를 확인하세요.")
        sys.exit(1)

    # 애드센스 승인 필수 정적 페이지 자가진단 및 자동 생성
    publisher.create_essential_pages()

    # 사이트맵 검사 자가진단
    check_sitemap()

    # 7일 경과한 오래된 썸네일 이미지 자동 삭제 (웹용량 자동 순환)
    delete_old_media(publisher, 7)

    # 연결 테스트 모드
    if args.test:
        print("\n[연결 테스트 모드] 자가진단 및 연결 테스트 성공")
        return

    # 더미 발행 테스트 (AI API 미사용)
    if args.test_post:
        print("\n[테스트 발행 모드] AI API 없이 더미 글로 WordPress 발행 테스트")
        dummy_article = {
            "title": "[테스트] GitHub Actions 연동 확인용 글",
            "content": "<p>이 글은 GitHub Actions 연동 테스트용입니다. 자동으로 삭제해주세요.</p>",
            "tags": ["테스트"],
            "focus_keyword": "테스트",
            "focus_keywords": ["테스트"],
            "focus_keywords_str": "테스트",
            "meta_description": "테스트 글입니다.",
            "url_slug": "github-actions-test",
        }
        dummy_image = {"url": "", "alt": "테스트", "photographer": "", "source": ""}
        url = publisher.publish(dummy_article, dummy_image)
        if url:
            print(f"\n테스트 발행 성공! URL: {url}")
        else:
            print("\n테스트 발행 실패.")
            sys.exit(1)
        return

    # Step 1: 트렌드 키워드 탐색
    if args.keyword:
        keyword_data = {
            "keyword": args.keyword,
            "category": args.category,
            "keyword_en": args.keyword,
            "google_score": 0,
            "naver_ratio": 0,
            "total_score": 0
        }
        print(f"\n[수동 키워드] {args.keyword} ({args.category})")
    else:
        print("\n[Step 1] 트렌드 키워드 탐색")
        trend_finder = TrendFinder(site=args.site)
        ranked_keywords = trend_finder.find_ranked_keywords()

        # 최근 10개 글 제목 가져오기 (중복 방지)
        print("\n  최근 발행 글 확인 중 (중복 주제 방지)...")
        recent_titles = get_recent_post_keywords(10)

        # 순위 순서대로 중복 아닌 키워드 선택
        keyword_data = None
        for rank, candidate in enumerate(ranked_keywords, 1):
            kw = candidate["keyword"]
            if is_duplicate_topic(kw, recent_titles):
                print(f"  {rank}위 '{kw}' → 최근 발행글과 주제 중복, 다음 순위로 넘어갑니다.")
                continue
            keyword_data = candidate
            print(f"  [OK] {rank}위 '{kw}' 선택 (중복 없음)")
            break

        # 모두 중복이면 1위 사용 (최후 fallback)
        if keyword_data is None:
            keyword_data = ranked_keywords[0]
            print(f"  [!] 모든 후보가 최근 글과 유사 -> 1위 '{keyword_data['keyword']}' 사용")

    print(f"  키워드: {keyword_data['keyword']} | 카테고리: {keyword_data['category']}")
    print(f"  Google 점수: {keyword_data.get('google_score', 'N/A')} | Naver 비율: {keyword_data.get('naver_ratio', 'N/A')}")

    # Step 2: 콘텐츠 생성 (publisher의 인증 세션을 전달해 관련글 로딩)
    print("\n[Step 2] 콘텐츠 생성")
    content_gen = ContentGenerator(site=args.site)
    article = content_gen.generate_article(keyword_data, session=publisher.session)
    print(f"  제목: {article['title']}")
    print(f"  태그: {', '.join(article['tags'])}")

    # --dry 모드: 내용 미리보기만
    if args.dry:
        print("\n[미리보기 모드 - 발행 안 함]")

        # 이미지 실제 다운로드 (미리보기용 3장)
        print("  이미지 3장 가져오는 중...")
        image_fetcher = ImageFetcher()
        images_list = image_fetcher.get_images(
            keyword_data.get("keyword_en", keyword_data["keyword"]),
            keyword_data["category"],
            keyword_data["keyword"],
            count=3
        )

        content = article['content']
        placeholders = ['FEATURED_IMAGE', 'BODY_IMAGE_1', 'BODY_IMAGE_2']

        for i, img_data in enumerate(images_list):
            placeholder = placeholders[i]
            img_filename = f"preview_img_{i+1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            success = False
            
            if img_data.get("local_path"):
                import shutil
                try:
                    shutil.copy(img_data["local_path"], img_filename)
                    success = True
                except Exception as e:
                    print(f"  로컬 이미지 {i+1} 복사 실패: {e}")
                    success = False
            elif img_data.get("medium_url") or img_data.get("url"):
                success = image_fetcher.download_image(img_data, img_filename)

            if success:
                credit = img_data.get("photographer", "")
                source = img_data.get("source", "").capitalize()
                credit_text = f"{source} / {credit}" if credit else source
                print(f"  이미지 {i+1} 저장 완료: {img_filename}")
                content = content.replace(placeholder, img_filename)
            else:
                print(f"  이미지 {i+1} 저장 실패 → 플레이스홀더 제거")
                content = content.replace(placeholder, "")

        # 미치환 플레이스홀더 정리
        for placeholder in placeholders:
            content = content.replace(placeholder, "")

        # 빈 src 이미지 태그 및 관련 figure 제거
        import re as _re
        content = _re.sub(r'<figure[^>]*>\s*<img[^>]*src=""[^>]*>\s*(?:<figcaption[^>]*>.*?</figcaption>\s*)?</figure>', '', content)
        content = _re.sub(r'<img src=""[^/]*/>', '', content)
        content = _re.sub(r'<img src="" [^>]*/>', '', content)

        preview_file = f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write(f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{article['title']}</title>
<style>
  body {{ font-family: 'Malgun Gothic', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.8; color: #333; }}
  h1 {{ font-size: 26px; color: #1a1a1a; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
  h2 {{ font-size: 20px; color: #2c3e50; margin-top: 30px; }}
  h3 {{ font-size: 17px; color: #34495e; }}
  table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: bold; }}
  ul, ol {{ padding-left: 20px; }}
  li {{ margin-bottom: 6px; }}
  .meta-box {{ background: #f0f4ff; border: 1px solid #c5d0f0; padding: 12px; border-radius: 6px; margin-bottom: 20px; font-size: 14px; color: #555; }}
  img {{ max-width: 100%; height: auto; border-radius: 8px; margin: 10px 0; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 25px 0; }}
  dl dt {{ font-weight: bold; margin-top: 10px; }}
  dl dd {{ margin-left: 15px; color: #555; }}
</style>
</head>
<body>
<div class="meta-box">
  <strong>SEO 미리보기</strong><br>
  제목: {article['title']}<br>
  메타설명: {article.get('meta_description', '')}<br>
  포커스 키워드: {article.get('focus_keyword', '')}<br>
  URL 슬러그: {article.get('url_slug', '')}<br>
  태그: {', '.join(article.get('tags', []))}
</div>
{content}
</body>
</html>""")
        print(f"  미리보기 저장: {preview_file}")
        print(f"  → 파일을 크롬으로 열어서 확인하세요!")
        return

    # Step 3: 이미지 가져오기 (3장)
    print("\n[Step 3] 이미지 선택 (3장)")
    image_fetcher = ImageFetcher()
    images_list = image_fetcher.get_images(
        keyword_data.get("keyword_en", keyword_data["keyword"]),
        keyword_data["category"],
        keyword_data["keyword"],
        count=3
    )
    print(f"  이미지 선택 완료: {len(images_list)}개 획득")

    # Step 4: 워드프레스 발행 (연결 확인 시 생성한 인스턴스 재사용)
    print("\n[Step 4] WordPress 발행")
    post_url = publisher.publish(article, images_list)

    # 로그 저장
    save_article_log(keyword_data, article, post_url)

    print("\n" + "=" * 50)
    if post_url:
        status = os.getenv("WP_POST_STATUS", "draft")
        status_text = "발행" if status == "publish" else "임시저장"
        print(f"완료! {status_text} URL: {post_url}")
    else:
        print("발행 실패. 로그를 확인해주세요.")
    print("=" * 50)


if __name__ == "__main__":
    main()
