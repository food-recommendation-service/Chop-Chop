import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional # ✅ Dict, Optional 추가됨

import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import jwt
from dotenv import load_dotenv

import recommender  # 작성한 recommender.py 임포트

load_dotenv()

# ==========================================
# 설정 및 DB
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "jeju_secret_123")
ALGORITHM = "HS256"
DATABASE_URL = "sqlite:///./users.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 개발 편의를 위해 전체 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 데이터 모델
# ==========================================
class UserCreate(BaseModel):
    username: str
    password: str

# [수정됨] 사용자 텍스트 입력(user_detail) 및 필터 추가
class RecommendRequest(BaseModel):
    radius_km: float
    categories: List[str]
    user_detail: str  # 예: "조용하고 바다가 보이는"
    lat: float
    lng: float
    # ✅ [변경점 1] 프론트엔드에서 보낸 필터 정보를 받기 위한 필드 추가
    # 예: {"BusinessParking": 1, "GoodForKids": 0}
    filters: Optional[Dict[str, int]] = None 

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ==========================================
# 엔드포인트
# ==========================================

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다.")
    new_user = User(username=user.username, hashed_password=pwd_context.hash(user.password))
    db.add(new_user)
    db.commit()
    return {"message": "회원가입 성공"}

@app.post("/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="로그인 실패")
    token = jwt.encode({"sub": db_user.username, "exp": datetime.utcnow() + timedelta(hours=1)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.post("/recommend")
def get_recommendations(req: RecommendRequest):
    try:
        # ✅ [변경점 2] recommender.py로 필터 정보(req.filters) 전달
        data = recommender.search_and_analyze(
            categories=req.categories,
            user_detail=req.user_detail,
            lat=req.lat,
            lng=req.lng,
            radius_km=req.radius_km,
            filters=req.filters # 여기가 핵심 추가 사항입니다
        )
        
        # ✅ [변경점 3] 개수 정보도 같이 반환 (UI 표시용)
        return {
            "result": data["result"], 
            "stores": data["stores"],
            "scanned_count": data.get("scanned_count", 0),
            "analyzed_count": data.get("analyzed_count", 0)
        }
    except Exception as e:
        print(f"Error: {e}")
        return {"result": f"오류 발생: {str(e)}", "stores": []}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)