import requests
import google.generativeai as genai
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import json
import re
import time
import os
from dotenv import load_dotenv

load_dotenv()

# ==================================================================================
# [1] API 키 및 모델 설정
# ==================================================================================
GOOGLE_API_KEY = "AIzaSyC-gSjkrWo8mjx8N_NR4h6a6Bk7taseW7s"
GEMINI_API_KEY = "AIzaSyC-gSjkrWo8mjx8N_NR4h6a6Bk7taseW7s"

genai.configure(api_key=GEMINI_API_KEY)
llm_model = genai.GenerativeModel('models/gemini-2.0-flash')

print("⏳ 임베딩 모델 로딩 중...")
embed_model = SentenceTransformer('jhgan/ko-sroberta-multitask')
print("✅ 시스템 준비 완료!\n")

# ==================================================================================
# [2] 핵심 분석 및 스코어링 함수 (원본 로직 유지)
# ==================================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """두 지점의 위도, 경도를 받아 거리를 km 단위로 계산"""
    R = 6371
    lat1_rad, lon1_rad = np.radians(lat1), np.radians(lon1)
    lat2_rad, lon2_rad = np.radians(lat2), np.radians(lon2)
    dlon, dlat = lon2_rad - lon1_rad, lat2_rad - lat1_rad
    a = np.sin(dlat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

def calculate_recency_score(reviews):
    """[활성도 점수] 리뷰 5개 이상 시 만점"""
    if not reviews: return 0.0
    return min(len(reviews) / 5.0, 1.0) 

def calculate_popularity_score(count):
    """[인기도 점수] 리뷰 개수를 로그 스케일로 변환"""
    if not count: return 0.0
    return min(np.log10(count + 1) / 4.0, 1.0)

def hard_filter_by_similarity(place_docs, user_query, threshold=0.3):
    """
    [하드 필터링] 의미적 유사도가 낮은 식당 즉시 제거
    '두바이쫀득쿠키' 입력 시 유사도 0.3 미만인 식당은 가차없이 탈락시킵니다.
    """
    if not place_docs: return []
    doc_texts = [p['text'] for p in place_docs]
    embeddings = embed_model.encode(doc_texts)
    query_embedding = embed_model.encode([user_query])
    sim_scores = cosine_similarity(query_embedding, embeddings)[0]
    
    passed_docs = []
    for i, score in enumerate(sim_scores):
        if score >= threshold:
            place_docs[i]['sim_score'] = score
            passed_docs.append(place_docs[i])
    
    print(f"✂️ 하드 필터링: {len(place_docs)}개 중 {len(passed_docs)}개 생존 (기준: {threshold})")
    return passed_docs

def get_naver_style_features(place_name, reviews):
    """[LLM 분석] 리뷰에서 분위기, 동행, 목적 추출"""
    if not reviews: return {}
    combined_review = " ".join([r.get('text', {}).get('text', '') for r in reviews[:5]])
    prompt = f"""
    당신은 맛집 데이터 분석가입니다. 아래 식당의 리뷰를 분석하여 정보를 JSON 포맷으로 추출하세요.
    식당명: {place_name}
    리뷰데이터: {combined_review[:800]}
    반드시 JSON 형식만 출력하세요: {{"atmosphere": "...", "companion": "...", "purpose": "...", "keywords": [...]}}
    """
    try:
        response = llm_model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except Exception: return {}

# ==================================================================================
# [3] 데이터 수집 함수 (Pagination 적용하여 200개 확보)
# ==================================================================================

def get_bulk_places(search_query, center_lat, center_lng, radius_km, target_count=200):
    """[대량 수집] 최대 10페이지(200개)까지 반복 호출"""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.rating,places.userRatingCount,places.reviews,places.location,places.formattedAddress,nextPageToken'
    }
    all_places_dict = {}
    next_token = None
    
    print(f"🕵️ '{search_query}' 대량 수집 시작 (목표: {target_count}개)...")
    
    for page in range(10):
        payload = {
            "textQuery": search_query,
            "locationBias": {"circle": {"center": {"latitude": center_lat, "longitude": center_lng}, "radius": radius_km * 1000}},
            "languageCode": "ko", "maxResultCount": 20, "pageToken": next_token
        }
        try:
            response = requests.post(url, json=payload, headers=headers)
            data = response.json()
            places = data.get('places', [])
            
            added = 0
            for p in places:
                pid = p.get('id')
                if pid and pid not in all_places_dict:
                    all_places_dict[pid] = p
                    added += 1
            print(f"  📄 {page+1}페이지 수집 중... (+{added}개)")
            
            next_token = data.get('nextPageToken')
            if not next_token or len(all_places_dict) >= target_count: break
            time.sleep(1.0) # 구글 API 딜레이 준수
        except Exception as e:
            print(f"  ❌ 에러 발생: {e}")
            break
            
    return list(all_places_dict.values())

# ==================================================================================
# [4] 메인 분석 파이프라인
# ==================================================================================

def search_and_analyze(categories, user_detail, lat, lng, radius_km):
    category_str = " ".join(categories)
    search_query = f"{category_str} {user_detail}".strip()
    if not search_query: search_query = "맛집"

    # 1. 200개 대량 수집
    places = get_bulk_places(search_query, lat, lng, radius_km, target_count=200)
    if not places: return {"result": "❌ 검색 결과가 없습니다.", "stores": []}

    # 2. 거리 필터링 및 전처리
    filtered_places = []
    for p in places:
        loc = p.get('location', {})
        dist = haversine_distance(lat, lng, loc.get('latitude', 0), loc.get('longitude', 0))
        if dist <= radius_km:
            reviews = p.get('reviews', [])
            review_text = " ".join([r.get('text', {}).get('text', '') for r in reviews])
            filtered_places.append({
                "name": p.get('displayName', {}).get('text', '이름없음'),
                "rating": p.get('rating', 0),
                "count": p.get('userRatingCount', 0),
                "reviews": reviews,
                "text": review_text,
                "lat": loc.get('latitude'), "lng": loc.get('longitude'), "address": p.get('formattedAddress', '')
            })
    
    scanned_count = len(filtered_places)
    
    # 3. 하드 필터링 (의미적 유사도 0.3 기준)
    valid_docs = [p for p in filtered_places if p['text'].strip()]
    candidates = hard_filter_by_similarity(valid_docs, search_query, threshold=0.3)
    analyzed_count = len(candidates)

    if not candidates: return {"result": "⚠️ 충분히 관련 있는 식당이 없습니다.", "stores": []}

    # 4. 종합 스코어링 (유사도 30, 평점 35, 리뷰수 25, 최신성 10)
    for p in candidates:
        p['total_score'] = (p['sim_score'] * 0.30) + (p['rating']/5 * 0.35) + (calculate_popularity_score(p['count']) * 0.25) + (calculate_recency_score(p['reviews']) * 0.10)
        p['match_rate'] = int(p['total_score'] * 100)

    # 5. 최종 리포트 생성 (상위 3개 분석)
    top_3 = sorted(candidates, key=lambda x: x['total_score'], reverse=True)[:3]
    result_report = f"\n{'='*65}\n🏆 '{search_query}' AI 추천 리포트 (분석 대상: {len(candidates)}개)\n{'='*65}\n"
    stores_data = []
    
    for rank, p in enumerate(top_3, 1):
        features = get_naver_style_features(p['name'], p['reviews'])
        kws = ", ".join(features.get('keywords', [])) if features.get('keywords') else "분석중..."
        
        result_report += f"🏅 {rank}위: {p['name']} (매칭 {p['match_rate']}%)\n"
        result_report += f"   ⭐️ 평점: {p['rating']}점 | 리뷰 {p['count']}개\n"
        result_report += f"   🏠 분위기: {features.get('atmosphere', '-')} | 👥 추천: {features.get('companion', '-')}\n"
        result_report += f"   🎯 목  적: {features.get('purpose', '-')} | 🔑 키워드: {kws}\n"
        result_report += "-" * 65 + "\n"
        
        stores_data.append({"name": p['name'], "lat": p['lat'], "lng": p['lng'], "rating": p['rating'], "address": p['address']})

    return {"result": result_report, "stores": stores_data, "scanned_count": scanned_count, "analyzed_count": analyzed_count}