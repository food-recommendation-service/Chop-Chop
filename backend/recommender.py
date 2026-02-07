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

# [보안 및 경로 강화] 현재 파일의 위치를 기준으로 .env 로드
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# ==================================================================================
# [1] 설정 및 환경 변수 로드 (BOM 제거 기능 추가)
# ==================================================================================
def clean_api_key(key):
    if not key: return ""
    # 1. 공백 제거
    key = key.strip()
    # 2. 보이지 않는 특수문자(BOM 등) 및 한글 강제 제거 (순수 아스키만 남김)
    try:
        return key.encode('ascii', 'ignore').decode('ascii')
    except:
        return ""

# 환경 변수 로드 후 클리닝 함수 통과
raw_google_key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_API_KEY")
raw_gemini_key = os.getenv("GEMINI_API_KEY")

GOOGLE_API_KEY = clean_api_key(raw_google_key)
GEMINI_API_KEY = clean_api_key(raw_gemini_key)

# 디버깅: 키가 정상적으로 로드되었는지 확인 (앞 5자리만 출력)
print(f"🔑 구글 키 로드 확인: {GOOGLE_API_KEY[:5]}..." if GOOGLE_API_KEY else "🚨 구글 키 없음")
print(f"🔑 제미나이 키 로드 확인: {GEMINI_API_KEY[:5]}..." if GEMINI_API_KEY else "🚨 제미나이 키 없음")

if not GOOGLE_API_KEY:
    print("🚨 [ERROR] GOOGLE_API_KEY가 유효하지 않습니다.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    llm_model = genai.GenerativeModel('models/gemini-2.0-flash')
else:
    print("🚨 [WARNING] GEMINI_API_KEY가 없습니다. LLM 분석 기능이 제한됩니다.")

print("⏳ 임베딩 모델 로딩 중 (ko-sroberta)...")
embed_model = SentenceTransformer('jhgan/ko-sroberta-multitask')
print("✅ 시스템 준비 완료!\n")

# ==================================================================================
# [2] 유틸리티 함수
# ==================================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371  # 지구 반지름 (km)
    lat1_rad, lon1_rad = np.radians(lat1), np.radians(lon1)
    lat2_rad, lon2_rad = np.radians(lat2), np.radians(lon2)
    dlon, dlat = lon2_rad - lon1_rad, lat2_rad - lat1_rad
    a = np.sin(dlat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

def get_naver_style_features(place_name, reviews):
    if not reviews or not GEMINI_API_KEY: return {}
    
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
    except:
        return {}

# ==================================================================================
# [3] 핵심 로직 (수집 -> 필터링 -> 스코어링)
# ==================================================================================

def get_bulk_places(search_query, center_lat, center_lng, radius_km):
    if not GOOGLE_API_KEY:
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,  # .strip() 처리된 깨끗한 키 사용
        'X-Goog-FieldMask': 'places.id,places.displayName,places.rating,places.userRatingCount,places.reviews,places.location,places.formattedAddress,nextPageToken'
    }
    
    places_list = []
    next_token = None
    
    # 디버깅: 요청 정보 출력
    print(f"📡 API 요청: [{search_query}] | 위치: ({center_lat}, {center_lng}) | 반경: {radius_km}km")

    for i in range(3):
        payload = {
            "textQuery": search_query,
            "locationBias": {
                "circle": {
                    "center": {"latitude": float(center_lat), "longitude": float(center_lng)},
                    "radius": float(radius_km) * 1000  # 미터 단위 변환
                }
            },
            "languageCode": "ko", 
            "maxResultCount": 20, 
            "pageToken": next_token
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            
            if response.status_code != 200:
                print(f"❌ API 에러 ({response.status_code}): {response.text}")
                break
                
            resp_data = response.json()
            batch = resp_data.get('places', [])
            places_list.extend(batch)
            
            print(f"   └ 페이지 {i+1}: {len(batch)}개 확보")
            
            next_token = resp_data.get('nextPageToken')
            if not next_token: break
            time.sleep(1.0) # API 할당량 준수 및 과열 방지
        except Exception as e:
            print(f"🚨 시스템 에러 발생: {e}")
            break
            
    return places_list

def hybrid_filter_similarity(place_docs, user_query, threshold=0.15):
    if not place_docs: return []
    
    doc_texts = [f"{p['name']} {p['text']}" for p in place_docs]
    embeddings = embed_model.encode(doc_texts)
    query_emb = embed_model.encode([user_query])
    sim_scores = cosine_similarity(query_emb, embeddings)[0]
    
    passed = []
    clean_query = user_query.replace(" ", "")
    
    for i, score in enumerate(sim_scores):
        p = place_docs[i]
        # Rule 1: 키워드 직접 포함 시 가점
        if clean_query in p['name'].replace(" ","") or clean_query in p['text'].replace(" ",""):
            p['sim_score'] = max(score, 0.6)
            p['filter_reason'] = "Keyword Match"
            passed.append(p)
            continue
        # Rule 2: 벡터 유사도 기준
        if score >= threshold:
            p['sim_score'] = score
            p['filter_reason'] = "Vector Similarity"
            passed.append(p)
            
    print(f"✂️ 필터링 결과: {len(place_docs)}개 중 {len(passed)}개 통과")
    return passed

# ==================================================================================
# [4] 메인 파이프라인
# ==================================================================================

def search_and_analyze(categories, user_detail, lat, lng, radius_km):
    search_keywords = [f"{cat} 맛집" for cat in categories]
    if user_detail: search_keywords.append(f"{user_detail} 맛집")
    if not search_keywords: search_keywords = ["맛집"]
    
    search_keywords = list(set(search_keywords))
    print(f"🕵️ 수집 시작: {search_keywords}")

    all_raw_places = {}
    for kw in search_keywords:
        batch = get_bulk_places(kw, lat, lng, radius_km)
        for p in batch:
            if p.get('id') not in all_raw_places:
                all_raw_places[p['id']] = p
        if len(all_raw_places) >= 150: break # 최대 수집량 조절
    
    print(f"✅ 총 {len(all_raw_places)}개 유니크 식당 확보")

    # 거리 필터링 및 데이터 정규화
    filtered_places = []
    for p in all_raw_places.values():
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
                "lat": loc.get('latitude'), 
                "lng": loc.get('longitude'), 
                "address": p.get('formattedAddress', '')
            })

    # 하이브리드 추천 필터링 적용
    candidates = hybrid_filter_similarity(filtered_places, user_detail, threshold=0.15)
    
    if not candidates: 
        return {"result": "❌ 주변에서 조건에 맞는 식당을 찾지 못했습니다.", "stores": []}

    # 최종 스코어 계산 (유사도 + 별점 + 리뷰수 + 인기 점수)
    for p in candidates:
        pop_score = min(np.log10(p['count'] + 1) / 4.0, 1.0) if p['count'] else 0
        rec_score = min(len(p['reviews']) / 5.0, 1.0) if p['reviews'] else 0
        p['total_score'] = (p['sim_score'] * 0.3) + (p['rating']/5 * 0.35) + (pop_score * 0.25) + (rec_score * 0.1)
        p['match_rate'] = int(p['total_score'] * 100)

    top_3 = sorted(candidates, key=lambda x: x['total_score'], reverse=True)[:3]
    
    # 결과 리포트 생성
    report = f"\n🏆 추천 리포트 (필터링 통과 {len(candidates)}개 중 Top 3)\n"
    stores_data = []
    
    for rank, p in enumerate(top_3, 1):
        feats = get_naver_style_features(p['name'], p['reviews'])
        report += f"🏅 {rank}위: {p['name']} (매칭 {p['match_rate']}%)\n"
        report += f"   ✨ {feats.get('purpose', '맛집')} | {feats.get('atmosphere', '분위기 좋음')}\n"
        report += f"   🔑 {', '.join(feats.get('keywords', []))}\n"
        stores_data.append({
            "name": p['name'], "lat": p['lat'], "lng": p['lng'], 
            "rating": p['rating'], "address": p['address'],
            "match_rate": p['match_rate']
        })

    return {
        "result": report, 
        "stores": stores_data, 
        "scanned_count": len(filtered_places), 
        "analyzed_count": len(candidates)
    }