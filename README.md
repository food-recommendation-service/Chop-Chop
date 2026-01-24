<div align="center">

# 🍽️ Smart_Dining_Recommender
### **개인 프로젝트**
**"사용자의 위치와 복합적인 취향을 반영한 머신러닝 기반 맛집 추천 서비스"**

<br>

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-%23F7931E.svg?style=for-the-badge&logo=scikit-learn&logoColor=white)
![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=%23F7DF1E)
![Google Maps](https://img.shields.io/badge/Google_Maps-4285F4?style=for-the-badge&logo=google-maps&logoColor=white)

</div>

---

## 1. 프로젝트 제작 배경 💡

기존의 지도 서비스(Naver Maps, Google Maps)는 풍부한 데이터를 제공하지만, 사용자의 세밀한 니즈를 충족하기엔 다음과 같은 불편함이 있었습니다.

* **복합 조건 검색의 어려움:** "별점 높고 리뷰 많은 한식집", "분위기 좋은 술집" 등 다중 조건을 한 번에 필터링하기 어렵습니다.
* **반복적인 탐색 비용:** 식당의 분위기나 상세 정보를 파악하기 위해 모든 리스트를 일일이 클릭하고 리뷰를 대조해야 합니다.
* **지능형 추천의 부재:** LLM(ChatGPT)처럼 사용자의 맥락을 이해하는 스마트한 추천 기능이 지도 앱 내에 부족합니다.

> **"내가 원하는 조건의 식당을 한 번에, 직관적으로 추천받을 수는 없을까?"** 라는 고민에서 이 프로젝트를 시작하게 되었습니다.

<br>

## 2. 프로젝트 목표 🎯

* **위치 기반 최적화:** 도로명 주소 기준 설정된 반경(N km) 내 맛집 분석 및 추천.
* **데이터 기반 큐레이션:** 단순 인기순 나열이 아닌, 머신러닝 알고리즘을 통한 사용자 맞춤형 랭킹 제공.
* **직관적인 정보 전달:** 분석된 데이터를 지도 API와 연동하여 시각적으로 구현.

<br>

## 3. 주요 기능 🚀

* **📍 위치 기반 탐색:** 도로명 주소와 반경을 설정하여 정확한 타겟팅 검색.
* **🔍 스마트 필터링:** 별점, 리뷰 수, 업태(한/중/일/양), 분위기, 주류 판매 여부 종합 고려.
* **🤖 머신러닝 추천:** `Scikit-learn`을 활용해 수집된 데이터를 학습하고 우선순위 기반 추천 리스트 생성.
* **🗺️ 시각화:** `Google Maps API`를 연동하여 추천 식당의 위치를 지도에 표시.

<br>

## 4. 기술 스택 (Tech Stack) 🛠️

### **Frontend**
* **HTML5 / CSS3 / JavaScript (ES6+)**

### **Backend & Machine Learning**
* **Python:** 데이터 전처리 및 분석 로직 구현
* **Flask:** Python 기반 ML 모델과 프론트엔드를 연결하는 API 서버
* **Scikit-learn:** 추천 모델 구현 및 가중치 기반 스코어링

### **API**
* **Google Maps API:** 지도 렌더링 및 위치 데이터 활용

<br>

## 5. 기대 효과 ✨

1.  **검색 시간 단축:** 리뷰를 일일이 대조할 필요 없이 최적의 리스트를 즉시 확인.
2.  **방문 만족도 향상:** 분위기와 방문 목적(식사/음주)에 최적화된 추천으로 실패 없는 장소 선택.
3.  **기술적 내재화:** 프론트엔드부터 머신러닝 백엔드까지 전체 서비스 라이프사이클 경험.

---

### 📅 프로젝트 기간
**26.1~26.2**
