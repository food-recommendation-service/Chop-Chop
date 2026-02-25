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
from mapping_utils import map_google_to_yelp_style

# 1. 환경 변수 및 설정
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

def clean_api_key(key):
    if not key: return ""
    try: return key.strip().encode('ascii', 'ignore').decode('ascii')
    except: return ""

GOOGLE_API_KEY = clean_api_key(os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_API_KEY"))
GEMINI_API_KEY = clean_api_key(os.getenv("GEMINI_API_KEY"))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    llm_model = genai.GenerativeModel('models/gemini-2.0-flash')

embed_model = SentenceTransformer('jhgan/ko-sroberta-multitask')

# 2. 유틸리티 함수
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))

def get_naver_style_features(place_name, reviews):
    if not reviews or not GEMINI_API_KEY: return {}
    combined_review = " ".join([r.get('text', {}).get('text', '') for r in reviews[:5]])
    prompt = f"식당명: {place_name}\n리뷰: {combined_review[:800]}\n정보 JSON 추출: {{'atmosphere': '...', 'purpose': '...', 'keywords': [...]}}"
    try:
        response = llm_model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except: return {}

def get_bulk_places(search_query, center_lat, center_lng, radius_km):
    if not GOOGLE_API_KEY: return []
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.rating,places.userRatingCount,places.reviews,places.location,places.formattedAddress,places.editorialSummary,places.priceLevel,places.servesBeer,places.servesWine,places.parkingOptions,places.goodForGroups,places.menuForChildren,places.accessibilityOptions,places.outdoorSeating,places.dineIn,places.servesCocktails,places.servesVegetarianFood,nextPageToken'
    }
    places_list = []
    next_token = None
    for i in range(3):
        payload = {
            "textQuery": search_query,
            "locationBias": {"circle": {"center": {"latitude": center_lat, "longitude": center_lng}, "radius": radius_km*1000}},
            "languageCode": "ko", "maxResultCount": 20, "pageToken": next_token
        }
        try:
            resp = requests.post(url, json=payload, headers=headers)
            data = resp.json()
            places_list.extend(data.get('places', []))
            next_token = data.get('nextPageToken')
            if not next_token: break
            time.sleep(1)
        except: break
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
        if clean_query in p['name'].replace(" ","") or clean_query in p['text'].replace(" ",""):
            p['sim_score'] = max(score, 0.6)
            passed.append(p)
        elif score >= threshold:
            p['sim_score'] = score
            passed.append(p)
    return passed

# ✅ 3. 메인 파이프라인 (디버그 로그 + 안전장치 추가)
def search_and_analyze(categories, user_detail, lat, lng, radius_km, filters=None):
    # 1. 검색 키워드 생성
    search_keywords = list(set([f"{cat} 맛집" for cat in categories] + ([f"{user_detail} 맛집"] if user_detail else [])))
    
    # 2. 데이터 수집
    print(f"🕵️ 수집 시작: {search_keywords}")
    all_raw_places = {}
    for kw in search_keywords:
        batch = get_bulk_places(kw, lat, lng, radius_km)
        for p in batch:
            if p.get('id') not in all_raw_places:
                all_raw_places[p['id']] = p
        if len(all_raw_places) >= 150: 
            break
    
    print(f"✅ 총 {len(all_raw_places)}개 유니크 식당 확보")

    # 3. [Stage 1] 반경 및 하드 필터링
    print("\n🔍 [Stage 1] 반경 및 하드 필터링 진행 중...")
    filtered_places = []
    hard_dropped_count = 0
    radius_dropped_count = 0

    safe_filters = filters if isinstance(filters, dict) else (dict(filters) if filters else {})
    if safe_filters:
        print(f"🐛 [DEBUG] 적용될 필수 필터: {safe_filters}")

    for p in all_raw_places.values():
        loc = p.get('location', {})
        dist = haversine_distance(lat, lng, loc.get('latitude', 0), loc.get('longitude', 0))
        
        # 반경 체크
        if dist > radius_km:
            radius_dropped_count += 1
            continue
        
        # 하드 필터 체크
        yelp_style_attr = map_google_to_yelp_style(p)
        is_match = True
        drop_reason = ""
        
        if safe_filters:
            for key, required in safe_filters.items():
                if required == 1 and yelp_style_attr.get(key) == 0:
                    is_match = False
                    drop_reason = key
                    break
        
        if not is_match: 
            print(f"   🚫 [제외됨] {p.get('displayName', {}).get('text')} (이유: {drop_reason} 없음)")
            hard_dropped_count += 1
            continue 

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
            "address": p.get('formattedAddress', ''),
            "summary": p.get('editorialSummary', {}).get('text', ''),
            "yelp_attrs": yelp_style_attr
        })

    print(f"✂️ 반경 필터링 결과: 총 {radius_dropped_count}개 식당 반경 초과로 제외됨.")
    print(f"✂️ 하드 필터링 결과: 총 {hard_dropped_count}개 식당 필수 옵션 미달로 제외됨.")
    print(f"✅ Stage 1 통과 식당: {len(filtered_places)}개")

    # 4. 🔥 [Stage 2] 소프트 필터링 (임베딩 유사도 분석) - 여기가 빠져서 에러 났던 것!
    print("\n🧠 [Stage 2] 소프트 필터링(유사도 분석) 진행 중...")
    threshold = 0.01 
    candidates = []
    soft_dropped_count = 0

    if filtered_places:
        doc_texts = [f"{p['name']} {p['text']}" for p in filtered_places]
        embeddings = embed_model.encode(doc_texts)
        query_text = user_detail if user_detail else " ".join(categories)
        query_emb = embed_model.encode([query_text])
        sim_scores = cosine_similarity(query_emb, embeddings)[0]

        for i, score in enumerate(sim_scores):
            p = filtered_places[i]
            p['sim_score'] = float(score)
            
            if score >= threshold:
                candidates.append(p)
            else:
                print(f"   📉 [유사도 탈락] {p['name']} (점수: {score:.4f} < 기준: {threshold})")
                soft_dropped_count += 1
    
    print(f"✂️ 소프트 필터링 결과: 총 {soft_dropped_count}개 식당 제외됨.")
    print(f"✅ 최종 후보군: {len(candidates)}개 식당 (스코어링 대상)")

    if not candidates: 
        return {"result": "❌ 조건에 맞는 식당이 없습니다.", "stores": []}

    # 5. 스코어링 및 가중치 계산
    print("\n📊 [Scoring] 각 후보 점수 분해:")
    for p in candidates:
        pop_score = min(np.log10(p['count'] + 1) / 4.0, 1.0) if p['count'] else 0
        rec_score = min(len(p['reviews']) / 5.0, 1.0) if p['reviews'] else 0

        s_sim    = p['sim_score'] * 0.6
        s_rating = (p['rating'] / 5) * 0.2
        s_pop    = pop_score * 0.15
        s_rec    = rec_score * 0.05

        p['total_score'] = s_sim + s_rating + s_pop + s_rec
        p['match_rate'] = int(p['total_score'] * 100)

        # 어떤 요소가 점수를 가장 많이 올렸는지 dominant factor 계산
        factor_map = {
            "유사도": s_sim,
            "별점": s_rating,
            "리뷰수(인기)": s_pop,
            "리뷰신뢰도": s_rec
        }
        dominant = max(factor_map, key=factor_map.get)

        print(
            f"   📌 {p['name']:<20} | "
            f"유사도: {p['sim_score']:.3f}→{s_sim:.3f}  "
            f"별점: {p['rating']:.1f}→{s_rating:.3f}  "
            f"인기: {p['count']}건→{s_pop:.3f}  "
            f"신뢰도: {s_rec:.3f}  "
            f"합계: {p['total_score']:.3f}  "
            f"🏆dominant: {dominant}"
        )

    # 6. 상위 15개 추출
    top_candidates = sorted(candidates, key=lambda x: x['total_score'], reverse=True)[:15]

    print(f"\n🥇 [Top {len(top_candidates)} 확정]")
    for rank, p in enumerate(top_candidates, 1):
        print(f"   {rank}위: {p['name']} ({p['match_rate']}%)")

    # 7. 리포트 생성
    report = f"\n🏆 추천 리포트 (통과 {len(candidates)}개 중 상위 {len(top_candidates)}개)\n"
    stores_data = []
    for rank, p in enumerate(top_candidates, 1):
        feats = get_naver_style_features(p['name'], p['reviews']) if rank <= 5 else {}
        report += f"🏅 {rank}위: {p['name']} (매칭 {p['match_rate']}%)\n"
        if feats:
            report += f"   ✨ {feats.get('purpose', '맛집')} | {feats.get('atmosphere', '분위기 좋음')}\n"

        stores_data.append({
            "name": p['name'],
            "lat": p['lat'],
            "lng": p['lng']
        })
    
    return {
        "result": report,
        "stores": stores_data,
        "scanned_count": len(all_raw_places),
        "analyzed_count": len(candidates)
    }