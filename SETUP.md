# ChopChop 실행 가이드

## 🚀 빠른 시작 (3단계)

### 1️⃣ 레포 클론
```bash
git clone https://github.com/본인레포주소/ChopChop.git
cd ChopChop
```

---

### 2️⃣ 백엔드 설정 및 실행

```bash
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install fastapi uvicorn pydantic sqlalchemy passlib bcrypt python-jose cryptography python-dotenv sentence-transformers scikit-learn numpy google-generativeai requests
```

**backend/.env 파일 만들기:**
```
GOOGLE_MAPS_API_KEY=여기에_구글맵_키(똑같음)
GEMINI_API_KEY=여기에_제미나이_키(똑같음)
```

**frontend/.env 파일 만들기:**
```
REACT_APP_GOOGLE_MAPS_API_KEY=여기에_구글맵_키
```

**실행:**
```bash
uvicorn main:app --reload
```

---

### 3️⃣ 프론트엔드 설정 및 실행 (새 터미널 파야 합니다)

```bash
cd frontend
npm install
```


**실행:**
```bash
npm start
```

---

## ✅ 접속

- 브라우저: http://localhost:3000
- 백엔드: http://localhost:8000

---

## 🔑 API 키 발급 (제 것 말고 본인것을 쓰려면)

**Google Maps API:** https://console.cloud.google.com/google/maps-apis/credentials
- Places API (New) 활성화 필수
- Billing 계정 연결 필수

**Gemini API:** https://aistudio.google.com/app/apikey

---

## 🐛 에러 해결

**패키지 설치 에러:**
```bash
pip install --upgrade pip
```

**API 키 인식 안 됨:**
- .env 파일 위치 확인 (backend/.env, frontend/.env)
- 서버 재시작

**CORS 에러:**
- main.py 확인: `allow_origins=["http://localhost:3000"]`


노션에 바로 붙여넣기 좋게 정리했어:

---

# LLM 호출 구조 전체 흐름

> LLM은 Google Gemini (gemini-2.0-flash) 2곳에서 호출됨

---

## 1차 호출 (메인): 식당 리랭킹 — `llm_reranker.py:133`

**[입력 변수]**

- `radius_km` → "2km 이내" 같은 거리 텍스트
- `hard_filters` → ["주차가능", "예스키즈존"] 등 필수 조건
- `user_detail` → 사용자 자유텍스트 ("조용한 분위기" 등)
- `top_15_stores` → recommender.py에서 점수 계산된 상위 15개 식당 (name, rating, review_count, address, review_text 포함)

**[프롬프트 조립]**

- `build_user_prompt()` → "근처 2km 이내에 주차가능하고 조용한 식당 추천해줘."
- `format_candidates_for_llm()` → 식당 15개 텍스트 목록으로 포맷

**[API 호출 - llm_reranker.py:133]**

```
response = _llm.generate_content(prompt)
```

**[출력 파싱 - lines 137-156]**

```
response.text → regex로 JSON 추출 → top3 배열
{"top3": [{"rank":1, "name":"...", "reason":"..."}...]}
```

**[이름 매칭]**

- `difflib.get_close_matches()`로 LLM이 반환한 이름 → 원본 데이터 매핑
- → lat, lng, rating, address 복구

**[최종 반환]**

```
result_stores: [{rank, name, lat, lng, rating, address, reason}] × 3
```

---

## 2차 호출 (서브): 리뷰 피처 추출 — `recommender.py:66`

**[입력]**

- `place_name` → 식당 이름
- `reviews[:5]` → 리뷰 텍스트 최대 5개 (800자 잘림)

**[프롬프트]**

```
"식당명: OOO\n리뷰: ...\n정보 JSON 추출: {atmosphere, purpose, keywords}"
```

**[API 호출 - recommender.py:66]**

```
response = llm_model.generate_content(prompt)
```

**[출력]**

```json
{"atmosphere": "...", "purpose": "...", "keywords": [...]}
```

> ⚠️ 이 2차 호출은 GEMINI_API_KEY가 있을 때만 실행되는데, 현재 메인 플로우에서 실제로 사용되지 않는 것으로 보임.

---

## 전체 파이프라인

```
App.js:163  →  POST /recommend
                ↓
main.py:176  →  search_and_analyze()
                ↓
recommender.py  →  Google Maps로 장소 수집 (최대 150개)
                →  반경 필터 + hard_filter 적용
                →  SentenceTransformer 임베딩 유사도 계산
                →  가중치 점수 (유사도 0.6 + 평점 0.2 + 인기 0.15 + 신뢰 0.05)
                →  상위 15개 추출
                ↓
llm_reranker.py:133  →  Gemini 호출 → TOP 3 + 이유
                ↓
main.py:189  →  DB 저장 (SearchLog)
                ↓
App.js  →  결과 렌더링 (지도 + 텍스트)
```

---

## 잠재적 이슈 포인트

| 위치 | 문제 |
|---|---|
| `llm_reranker.py:133` | 응답이 항상 valid JSON이 아닐 수 있음 → regex fallback 있긴 함 |
| `llm_reranker.py:144` | fuzzy matching으로 이름 매핑 → 오매핑 가능성 |
| `recommender.py:66` | 2차 LLM 호출이 메인 플로우에 연결 안 됨 → dead code 가능성 |
| `.env` | GOOGLE_MAPS_API_KEY와 GEMINI_API_KEY가 동일한 키 사용 |