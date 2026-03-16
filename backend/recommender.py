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
import llm_reranker

load_dotenv()

# ==================================================================================
# [1] 설정
# ==================================================================================
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyC-gSjkrWo8mjx8N_NR4h6a6Bk7taseW7s")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyC-gSjkrWo8mjx8N_NR4h6a6Bk7taseW7s")

genai.configure(api_key=GEMINI_API_KEY)
llm_model = genai.GenerativeModel('models/gemini-2.0-flash')

print("⏳ 임베딩 모델 로딩 중...")
embed_model = SentenceTransformer('jhgan/ko-sroberta-multitask')
print("✅ 시스템 준비 완료!\n")

# ==================================================================================
# [2] 유틸리티 함수
# ==================================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1_rad, lon1_rad = np.radians(lat1), np.radians(lon1)
    lat2_rad, lon2_rad = np.radians(lat2), np.radians(lon2)
    dlon, dlat = lon2_rad - lon1_rad, lat2_rad - lat1_rad
    a = np.sin(dlat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

def get_naver_style_features(place_name, reviews):
    if not reviews: return {}
    combined_review = " ".join([r.get('text', {}).get('text', '') for r in reviews[:5]])
    prompt = f"""
    식당명: {place_name}
    리뷰: {combined_review[:800]}
    정보를 JSON으로 추출하세요: {{"atmosphere": "...", "companion": "...", "purpose": "...", "keywords": [...]}}
    """
    try:
        response = llm_model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except: return {}

# ==================================================================================
# [3] 핵심 로직 (수집 -> 필터링 -> 스코어링)
# ==================================================================================

def get_bulk_places(search_query, center_lat, center_lng, radius_km):
    """
    구글 API 호출 함수 (단일 키워드당 최대 60개)
    깔끔하게 API 호출 역할만 수행합니다.
    """
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.rating,places.userRatingCount,places.reviews,places.location,places.formattedAddress,nextPageToken'
    }
    places_list = []
    next_token = None
    
    # 3페이지(60개)까지만 수집 (구글 제한)
    for _ in range(3):
        payload = {
            "textQuery": search_query,
            "locationBias": {"circle": {"center": {"latitude": center_lat, "longitude": center_lng}, "radius": radius_km * 1000}},
            "languageCode": "ko", "maxResultCount": 20, "pageToken": next_token
        }
        try:
            resp = requests.post(url, json=payload, headers=headers).json()
            batch = resp.get('places', [])
            places_list.extend(batch)
            next_token = resp.get('nextPageToken')
            if not next_token: break
            time.sleep(1.0)
        except: break
    return places_list

def hard_filter_by_similarity(place_docs, user_query, threshold=0.3):
    """
    하드 필터링: 가게 이름 + 리뷰 텍스트로 유사도 검사
    """
    if not place_docs: return []
    
    # [중요 보완] 리뷰뿐만 아니라 '가게 이름'도 같이 봅니다. (허니콤보/방어 찾기 필수)
    doc_texts = [f"{p['name']} {p['text']}" for p in place_docs]
    
    embeddings = embed_model.encode(doc_texts)
    query_emb = embed_model.encode([user_query])
    sim_scores = cosine_similarity(query_emb, embeddings)[0]
    
    passed = []
    for i, score in enumerate(sim_scores):
        if score >= threshold:
            place_docs[i]['sim_score'] = score
            passed.append(place_docs[i])
            
    print(f"✂️ 하드 필터링: {len(place_docs)}개 중 {len(passed)}개 생존 (기준: {threshold})")
    return passed

# ==================================================================================
# [4] 메인 파이프라인
# ==================================================================================

def search_and_analyze(categories, user_detail, lat, lng, radius_km, hard_filters=None):
    # 1. 검색어 준비 (200개 수집을 위한 키워드 분할)
    search_keywords = [f"{cat} 맛집" for cat in categories]
    if user_detail: search_keywords.append(f"{user_detail} 맛집")
    if not search_keywords: search_keywords = ["맛집"]
    
    search_keywords = list(set(search_keywords)) # 중복 제거
    
    print(f"🕵️ 검색 키워드: {search_keywords} 로 수집 시작...")

    # 2. 200개 데이터 수집 (키워드별로 돌면서 모으기)
    all_raw_places = {}
    for kw in search_keywords:
        batch = get_bulk_places(kw, lat, lng, radius_km)
        for p in batch:
            if p.get('id') not in all_raw_places:
                all_raw_places[p['id']] = p
        if len(all_raw_places) >= 200: break # 200개 차면 중단
    
    print(f"✅ 총 {len(all_raw_places)}개 식당 확보 완료")

    # 3. 전처리 (거리 계산 및 텍스트 추출)
    filtered_places = []
    for p in all_raw_places.values():
        loc = p.get('location', {})
        dist = haversine_distance(lat, lng, loc.get('latitude', 0), loc.get('longitude', 0))
        
        if dist <= radius_km:
            reviews = p.get('reviews', [])
            # 빈 텍스트라도 이름으로 검색되게 처리
            review_text = " ".join([r.get('text', {}).get('text', '') for r in reviews])
            filtered_places.append({
                "name": p.get('displayName', {}).get('text', '이름없음'),
                "rating": p.get('rating', 0), "count": p.get('userRatingCount', 0),
                "reviews": reviews, "text": review_text,
                "lat": loc.get('latitude'), "lng": loc.get('longitude'), "address": p.get('formattedAddress', '')
            })

    # 4. 하드 필터링 (사용자 상세 입력 기준)
    # 리뷰가 없어도 가게 이름으로 살리기 위해 빈 텍스트 체크 제거
    candidates = hard_filter_by_similarity(filtered_places, user_detail, threshold=0.3)
    
    if not candidates: return {"result": "❌ 관련 식당을 찾지 못했습니다.", "stores": []}

    # 5. 스코어링 (평점, 리뷰수, 유사도 반영)
    for p in candidates:
        # 인기도 점수 계산 (로그 스케일)
        pop_score = min(np.log10(p['count'] + 1) / 4.0, 1.0) if p['count'] else 0
        # 최신성 점수
        rec_score = min(len(p['reviews']) / 5.0, 1.0) if p['reviews'] else 0
        
        p['total_score'] = (p['sim_score'] * 0.3) + (p['rating']/5 * 0.35) + (pop_score * 0.25) + (rec_score * 0.1)
        p['match_rate'] = int(p['total_score'] * 100)

    # 6. 상위 15개 선정 후 LLM 리랭킹으로 최종 Top 3 결정
    top_15 = sorted(candidates, key=lambda x: x['total_score'], reverse=True)[:15]
    print(f"📋 Top {len(top_15)}개 후보를 LLM 리랭킹에 전달...")

    llm_result = llm_reranker.rerank_with_llm(
        top_candidates=top_15,
        radius_km=radius_km,
        hard_filters=hard_filters or [],
        user_detail=user_detail
    )

    return {
        "result": llm_result["result"],
        "stores": llm_result["stores"],
        "scanned_count": len(filtered_places),
        "analyzed_count": len(candidates)
    }