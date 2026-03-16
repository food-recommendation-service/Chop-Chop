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
