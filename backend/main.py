import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from dotenv import load_dotenv

import recommender

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

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

class SearchLog(Base):
    __tablename__ = "search_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    searched_at = Column(DateTime, default=datetime.utcnow)
    radius_km = Column(Float)
    categories = Column(String)   # JSON 문자열
    user_detail = Column(String)
    lat = Column(Float)
    lng = Column(Float)
    result_text = Column(String)
    stores = Column(String)       # JSON 문자열: [{name, lat, lng}]

class RestaurantRating(Base):
    __tablename__ = "restaurant_ratings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    search_log_id = Column(Integer, ForeignKey("search_logs.id"), index=True)
    restaurant_name = Column(String)
    rating = Column(Integer)      # 1~5
    rated_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# ==========================================
# 데이터 모델
# ==========================================
class UserCreate(BaseModel):
    username: str
    password: str

class RecommendRequest(BaseModel):
    radius_km: float = Field(gt=0, le=50)
    categories: List[str] = Field(default=[])
    user_detail: str = Field(default="", max_length=500)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    filters: Optional[Dict[str, int]] = None

    @validator("filters")
    def validate_filters(cls, v):
        if v is None:
            return v
        for key, val in v.items():
            if val not in (0, 1):
                raise ValueError(f"필터 값은 0 또는 1이어야 합니다: {key}={val}")
        return v

class RateRequest(BaseModel):
    search_log_id: int
    restaurant_name: str
    rating: int = Field(ge=1, le=5)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def get_current_user(access_token: Optional[str] = Cookie(default=None)):
    if not access_token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

# ==========================================
# 엔드포인트
# ==========================================

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다.")
    if len(user.password.encode('utf-8')) > 72:
        raise HTTPException(status_code=400, detail="비밀번호는 72자 이하로 입력해주세요.")
    new_user = User(username=user.username, hashed_password=pwd_context.hash(user.password))
    db.add(new_user)
    db.commit()
    return {"message": "회원가입 성공"}

@app.post("/login")
def login(user: UserCreate, response: Response, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="로그인 실패")
    token = jwt.encode(
        {"sub": db_user.username, "exp": datetime.utcnow() + timedelta(hours=1)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=3600,
        samesite="lax",
    )
    return {"message": "로그인 성공", "username": db_user.username}

@app.get("/me")
def get_me(username: str = Depends(get_current_user)):
    return {"username": username}

@app.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "로그아웃 성공"}

@app.post("/recommend")
def get_recommendations(req: RecommendRequest, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"추천 요청 - 사용자: {username}, 반경: {req.radius_km}km, 카테고리: {req.categories}")
    try:
        data = recommender.search_and_analyze(
            categories=req.categories,
            user_detail=req.user_detail,
            lat=req.lat,
            lng=req.lng,
            radius_km=req.radius_km,
            filters=req.filters
        )

        # 검색 로그 저장
        db_user = db.query(User).filter(User.username == username).first()
        if db_user:
            log = SearchLog(
                user_id=db_user.id,
                searched_at=datetime.utcnow(),
                radius_km=req.radius_km,
                categories=json.dumps(req.categories, ensure_ascii=False),
                user_detail=req.user_detail,
                lat=req.lat,
                lng=req.lng,
                result_text=data["result"],
                stores=json.dumps(data.get("stores", []), ensure_ascii=False),
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            log_id = log.id
        else:
            log_id = None

        return {
            "result": data["result"],
            "stores": data["stores"],
            "scanned_count": data.get("scanned_count", 0),
            "analyzed_count": data.get("analyzed_count", 0),
            "log_id": log_id,
        }
    except Exception as e:
        logger.exception(f"추천 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail="추천 처리 중 오류가 발생했습니다.")

@app.post("/rate")
def rate_restaurant(req: RateRequest, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # 해당 검색 로그가 이 사용자 것인지 확인
    log = db.query(SearchLog).filter(
        SearchLog.id == req.search_log_id,
        SearchLog.user_id == db_user.id
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="검색 기록을 찾을 수 없습니다.")

    # 이미 평가한 경우 업데이트, 없으면 새로 생성
    existing = db.query(RestaurantRating).filter(
        RestaurantRating.user_id == db_user.id,
        RestaurantRating.search_log_id == req.search_log_id,
        RestaurantRating.restaurant_name == req.restaurant_name,
    ).first()

    if existing:
        existing.rating = req.rating
        existing.rated_at = datetime.utcnow()
    else:
        new_rating = RestaurantRating(
            user_id=db_user.id,
            search_log_id=req.search_log_id,
            restaurant_name=req.restaurant_name,
            rating=req.rating,
            rated_at=datetime.utcnow(),
        )
        db.add(new_rating)

    db.commit()
    return {"message": "별점이 저장되었습니다."}

@app.get("/my-logs")
def get_my_logs(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    logs = db.query(SearchLog).filter(
        SearchLog.user_id == db_user.id
    ).order_by(SearchLog.searched_at.desc()).all()

    # 각 로그에 대한 별점도 함께 조회
    ratings_by_log = {}
    all_ratings = db.query(RestaurantRating).filter(
        RestaurantRating.user_id == db_user.id
    ).all()
    for r in all_ratings:
        if r.search_log_id not in ratings_by_log:
            ratings_by_log[r.search_log_id] = {}
        ratings_by_log[r.search_log_id][r.restaurant_name] = r.rating

    result = []
    for log in logs:
        stores = json.loads(log.stores) if log.stores else []
        categories = json.loads(log.categories) if log.categories else []
        log_ratings = ratings_by_log.get(log.id, {})

        result.append({
            "id": log.id,
            "searched_at": log.searched_at.isoformat() if log.searched_at else None,
            "radius_km": log.radius_km,
            "categories": categories,
            "user_detail": log.user_detail,
            "lat": log.lat,
            "lng": log.lng,
            "result_text": log.result_text,
            "stores": stores,
            "ratings": log_ratings,  # {restaurant_name: rating}
        })

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
