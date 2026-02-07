import requests
import google.generativeai as genai
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import json
import re
import time
import os
import math
from dotenv import load_dotenv

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
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.rating,places.userRatingCount,places.reviews,places.location,places.formattedAddress,nextPageToken'
    }
    places_list = []
    next_token = None
    
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

def hybrid_filter_similarity(place_docs, user_query, threshold=0.15):
    """
    [하이브리드 필터링 업데이트]
    1. Rule-based: 검색 키워드가 이름이나 텍스트에 포함되면 무조건 합격 (최소 점수 보정)
    2. Vector-based: 임베딩 유사도가 threshold 이상이면 합격
    """
    if not place_docs: return []
    
    # 가게 이름 + 리뷰 텍스트 결합
    doc_texts = [f"{p['name']} {p['text']}" for p in place_docs]
    
    embeddings = embed_model.encode(doc_texts)
    query_emb = embed_model.encode([user_query])
    sim_scores = cosine_similarity(query_emb, embeddings)[0]
    
    passed = []
    clean_query = user_query.replace(" ", "") # 공백 제거 비교용
    
    for i, score in enumerate(sim_scores):
        p = place_docs[i]
        
        # [Rule 1] 직접적인 키워드 매칭 (이름이나 리뷰에 단어가 포함된 경우)
        if clean_query in p['name'].replace(" ","") or clean_query in p['text'].replace(" ",""):
            p['sim_score'] = max(score, 0.6) # 검색어 포함 시 점수 보정 (0.6 미만이어도 합격)
            p['filter_reason'] = "Keyword Match"
            passed.append(p)
            continue
            
        # [Rule 2] 벡터 유사도 매칭 (관대한 기준 0.15)
        if score >= threshold:
            p['sim_score'] = score
            p['filter_reason'] = "Vector Similarity"
            passed.append(p)
            
    print(f"✂️ 하이브리드 필터링: {len(place_docs)}개 중 {len(passed)}개 생존")
    return passed

# ==================================================================================
# [4] 메인 파이프라인
# ==================================================================================

def search_and_analyze(categories, user_detail, lat, lng, radius_km):
    search_keywords = [f"{cat} 맛집" for cat in categories]
    if user_detail: search_keywords.append(f"{user_detail} 맛집")
    if not search_keywords: search_keywords = ["맛집"]
    
    search_keywords = list(set(search_keywords))
    
    print(f"🕵️ 검색 키워드: {search_keywords} 수집 시작...")

    all_raw_places = {}
    for kw in search_keywords:
        batch = get_bulk_places(kw, lat, lng, radius_km)
        for p in batch:
            if p.get('id') not in all_raw_places:
                all_raw_places[p['id']] = p
        if len(all_raw_places) >= 200: break
    
    print(f"✅ 총 {len(all_raw_places)}개 식당 확보")

    filtered_places = []
    for p in all_raw_places.values():
        loc = p.get('location', {})
        dist = haversine_distance(lat, lng, loc.get('latitude', 0), loc.get('longitude', 0))
        
        if dist <= radius_km:
            reviews = p.get('reviews', [])
            review_text = " ".join([r.get('text', {}).get('text', '') for r in reviews])
            filtered_places.append({
                "name": p.get('displayName', {}).get('text', '이름없음'),
                "rating": p.get('rating', 0), "count": p.get('userRatingCount', 0),
                "reviews": reviews, "text": review_text,
                "lat": loc.get('latitude'), "lng": loc.get('longitude'), "address": p.get('formattedAddress', '')
            })

    # [하이브리드 필터링으로 교체]
    candidates = hybrid_filter_similarity(filtered_places, user_detail, threshold=0.15)
    
    if not candidates: return {"result": "❌ 관련 식당을 찾지 못했습니다.", "stores": []}

    for p in candidates:
        pop_score = min(np.log10(p['count'] + 1) / 4.0, 1.0) if p['count'] else 0
        rec_score = min(len(p['reviews']) / 5.0, 1.0) if p['reviews'] else 0
        p['total_score'] = (p['sim_score'] * 0.3) + (p['rating']/5 * 0.35) + (pop_score * 0.25) + (rec_score * 0.1)
        p['match_rate'] = int(p['total_score'] * 100)

    top_3 = sorted(candidates, key=lambda x: x['total_score'], reverse=True)[:3]
    
    report = f"\n{'='*60}\n🏆 추천 리포트 (필터링 통과 {len(candidates)}개 중 Top 3)\n{'='*60}\n"
    stores_data = []
    
    for rank, p in enumerate(top_3, 1):
        feats = get_naver_style_features(p['name'], p['reviews'])
        report += f"🏅 {rank}위: {p['name']} (매칭 {p['match_rate']}%)\n"
        report += f"   ✨ {feats.get('purpose', '맛집')} | {feats.get('atmosphere', '분위기 좋음')}\n"
        report += f"   🔑 {', '.join(feats.get('keywords', []))}\n"
        report += "-"*60 + "\n"
        stores_data.append({"name": p['name'], "lat": p['lat'], "lng": p['lng'], "rating": p['rating'], "address": p['address']})

    return {"result": report, "stores": stores_data, "scanned_count": len(filtered_places), "analyzed_count": len(candidates)}