"""
llm_reranker.py

recommender.py의 Top 15 후보를 받아 LLM으로 최종 Top 3 + 선정이유를 반환합니다.
현재는 테스트용 Gemini 모델 사용 → 추후 팀원의 파인튜닝 모델로 교체 예정.

교체 시 rerank_with_llm() 내부의 LLM 호출 부분만 수정하면 됩니다.
"""

import google.generativeai as genai
import json
import re
import os
import difflib
from dotenv import load_dotenv

load_dotenv()

# ==================================================================================
# [1] 모델 설정 (추후 파인튜닝 모델로 교체할 부분)
# ==================================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)
_llm = genai.GenerativeModel('models/gemini-2.0-flash')


# ==================================================================================
# [2] 프롬프트 조합 유틸
# ==================================================================================

def build_user_prompt(radius_km: float, hard_filters: list, user_detail: str) -> str:
    """
    사용자 입력을 자연어 문장으로 조합합니다.
    예: "근처 2km 이내에 주차가능, 예스키즈존가 가능하고, 조용한 분위기한 식당을 추천해줘."
    """
    filters_str = ", ".join(hard_filters) if hard_filters else ""

    if filters_str and user_detail:
        return f"근처 {radius_km}km 이내에 {filters_str}가 가능하고, {user_detail}한 식당을 추천해줘."
    elif filters_str:
        return f"근처 {radius_km}km 이내에 {filters_str}가 가능한 식당을 추천해줘."
    elif user_detail:
        return f"근처 {radius_km}km 이내에 {user_detail}한 식당을 추천해줘."
    else:
        return f"근처 {radius_km}km 이내에 좋은 식당을 추천해줘."


def format_candidates_for_llm(candidates: list) -> str:
    """후보 식당 리스트를 LLM이 읽기 좋은 텍스트 블록으로 변환"""
    blocks = []
    for i, p in enumerate(candidates, 1):
        snippet = p.get('text', '')[:200].strip()
        blocks.append(
            f"{i}. 식당명: {p['name']}\n"
            f"   평점: {p.get('rating', 'N/A')} (리뷰 {p.get('count', 0)}개)\n"
            f"   주소: {p.get('address', '정보없음')}\n"
            f"   리뷰 요약: {snippet if snippet else '리뷰 없음'}"
        )
    return "\n\n".join(blocks)


def match_name_to_candidate(llm_name: str, candidates: list) -> dict:
    """
    LLM이 반환한 식당명과 후보 목록을 퍼지 매칭합니다.
    LLM이 이름을 약간 다르게 쓸 경우 대비.
    """
    names = [p['name'] for p in candidates]
    close = difflib.get_close_matches(llm_name, names, n=1, cutoff=0.5)
    if close:
        return next(p for p in candidates if p['name'] == close[0])
    # 완전 일치 시도
    exact = next((p for p in candidates if p['name'] == llm_name), None)
    return exact if exact else candidates[0]


# ==================================================================================
# [3] 핵심 함수: LLM 리랭킹
# ==================================================================================

def rerank_with_llm(
    top_candidates: list,
    radius_km: float,
    hard_filters: list,
    user_detail: str
) -> dict:
    """
    recommender.py에서 스코어링된 Top 15 후보를 LLM에 넣어 Top 3 + 선정이유를 반환합니다.

    Args:
        top_candidates: recommender.py의 스코어링 결과 (최대 15개)
        radius_km: 사용자가 설정한 반경 (km)
        hard_filters: 버튼 필터 목록 (예: ["주차가능", "예스키즈존"])
        user_detail: 사용자 자유 텍스트 or 분위기 버튼 (예: "조용한 분위기")

    Returns:
        {
            "result": 텍스트 리포트 (str),
            "stores": [
                {"rank": 1, "name": ..., "lat": ..., "lng": ...,
                 "rating": ..., "address": ..., "reason": ...},
                ...
            ]
        }
    """
    user_prompt = build_user_prompt(radius_km, hard_filters, user_detail)
    candidates_text = format_candidates_for_llm(top_candidates)

    # ------------------------------------------------------------------
    # LLM 프롬프트
    # 교체 포인트: 이 prompt를 파인튜닝 모델 입력 포맷에 맞게 수정하거나,
    # _llm.generate_content() 호출을 파인튜닝 모델 API 호출로 교체하세요.
    # ------------------------------------------------------------------
    prompt = f"""당신은 식당 추천 전문가입니다. 사용자 요청과 후보 식당 목록을 분석해 가장 적합한 TOP 3를 선정해주세요.

[사용자 요청]
{user_prompt}

[후보 식당 목록]
{candidates_text}

위 조건에 가장 잘 맞는 식당 TOP 3를 선정하고, 반드시 아래 JSON 형식으로만 응답해주세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "top3": [
    {{"rank": 1, "name": "식당명", "reason": "선정 이유를 2~3문장으로 설명"}},
    {{"rank": 2, "name": "식당명", "reason": "선정 이유를 2~3문장으로 설명"}},
    {{"rank": 3, "name": "식당명", "reason": "선정 이유를 2~3문장으로 설명"}}
  ]
}}"""

    try:
        print(f"🤖 LLM 리랭킹 시작 ({len(top_candidates)}개 후보 → Top 3)...")
        response = _llm.generate_content(prompt)
        raw = response.text.strip()

        # JSON 파싱 (마크다운 코드블록 안에 있을 경우 대비)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise ValueError(f"LLM 응답에서 JSON을 찾지 못했습니다. 응답: {raw[:200]}")

        parsed = json.loads(match.group(0))
        top3_llm = parsed.get("top3", [])

        # LLM이 반환한 이름 → 원본 후보 데이터 매칭 (lat/lng/address 복원)
        result_stores = []
        for item in top3_llm[:3]:
            candidate = match_name_to_candidate(item["name"], top_candidates)
            result_stores.append({
                "rank": item["rank"],
                "name": candidate["name"],
                "lat": candidate["lat"],
                "lng": candidate["lng"],
                "rating": candidate["rating"],
                "address": candidate["address"],
                "reason": item["reason"]
            })

        # 텍스트 리포트 생성
        report = f"\n{'='*60}\n"
        report += f"🤖 AI 추천 리포트 (Top {len(top_candidates)} → LLM 리랭킹 → Top 3)\n"
        report += f"📍 요청: {user_prompt}\n"
        report += f"{'='*60}\n"
        for s in result_stores:
            report += f"🏅 {s['rank']}위: {s['name']} (⭐ {s['rating']})\n"
            report += f"   💬 {s['reason']}\n"
            report += "-" * 60 + "\n"

        print("✅ LLM 리랭킹 완료")
        return {"result": report, "stores": result_stores}

    except Exception as e:
        # LLM 실패 시 스코어링 기준 Top 3 그대로 반환 (서비스 중단 방지)
        print(f"❌ LLM 리랭킹 오류: {e} → 스코어 기준 Top 3로 fallback")
        fallback_stores = []
        for rank, p in enumerate(top_candidates[:3], 1):
            fallback_stores.append({
                "rank": rank,
                "name": p["name"],
                "lat": p["lat"],
                "lng": p["lng"],
                "rating": p["rating"],
                "address": p["address"],
                "reason": f"스코어 기준 {rank}위 식당입니다. (LLM 분석 오류로 자동 선정)"
            })

        report = f"\n⚠️ LLM 오류 발생 - 스코어 기준 Top 3\n"
        for s in fallback_stores:
            report += f"🏅 {s['rank']}위: {s['name']} | {s['reason']}\n"

        return {"result": report, "stores": fallback_stores}
