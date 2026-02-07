// frontend/src/App.js
import React, { useState } from 'react';
import axios from 'axios';
import { GoogleMap, useJsApiLoader, Marker, Circle } from '@react-google-maps/api';

const GOOGLE_MAPS_API_KEY = "YOUR_GOOGLE_MAPS_API_KEY_HERE"; // [준성] 키 입력

const containerStyle = { width: '100%', height: '100vh' };
const circleOptions = {
  strokeColor: "#FF6B00",
  strokeOpacity: 0.8,
  strokeWeight: 2,
  fillColor: "#FF6B00",
  fillOpacity: 0.2,
  clickable: false,
};

const TAGS = ["회", "흑돼지", "고기국수", "로컬맛집", "가성비", "뷰맛집", "조용한", "데이트", "가족과함께"];

function App() {
  const [myLocation, setMyLocation] = useState({ lat: 33.5043, lng: 126.5262 }); // 제주공항 근처
  const [distance, setDistance] = useState(1.5);
  const [selectedTags, setSelectedTags] = useState([]);
  const [userText, setUserText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");     // 텍스트 결과
  const [stores, setStores] = useState([]);     // 지도 마커용 데이터

  const { isLoaded } = useJsApiLoader({
    id: 'google-map-script',
    googleMapsApiKey: GOOGLE_MAPS_API_KEY
  });

  // 태그 토글 함수
  const toggleTag = (tag) => {
    setSelectedTags(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]);
  };

  // 추천 요청 함수
  const handleRecommend = async () => {
    setLoading(true);
    setResult("");
    try {
      // FastAPI 백엔드로 요청
      const res = await axios.post('http://localhost:8000/recommend', {
        lat: myLocation.lat,
        lng: myLocation.lng,
        radius_km: parseFloat(distance),
        categories: selectedTags,
        user_detail: userText
      });
      
      setResult(res.data.result);
      setStores(res.data.stores);
      
    } catch (err) {
      console.error(err);
      alert("추천 중 오류가 발생했습니다.");
    }
    setLoading(false);
  };

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "sans-serif" }}>
      {/* 1. 사이드바 (컨트롤러 & 결과창) */}
      <div style={{ width: "400px", padding: "20px", background: "white", overflowY: "auto", boxShadow: "2px 0 5px rgba(0,0,0,0.1)", zIndex: 10 }}>
        <h2 style={{ color: "#FF6B00" }}>🍊 AI 제주 맛집 추천</h2>
        
        {/* 거리 조절 */}
        <div style={{ marginBottom: "20px" }}>
          <label><b>탐색 반경:</b> {distance}km</label>
          <input type="range" min="0.5" max="5.0" step="0.5" value={distance} onChange={e=>setDistance(e.target.value)} style={{ width: "100%" }} />
        </div>

        {/* 텍스트 입력 (RAG 핵심) */}
        <div style={{ marginBottom: "20px" }}>
          <label><b>원하는 분위기:</b></label>
          <textarea 
            placeholder="예: 부모님 모시고 갈 조용한 룸식당, 바다 보이는 카페"
            value={userText}
            onChange={e => setUserText(e.target.value)}
            style={{ width: "100%", height: "60px", padding: "10px", marginTop: "5px" }}
          />
        </div>

        {/* 태그 버튼 */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", marginBottom: "20px" }}>
          {TAGS.map(tag => (
            <button key={tag} onClick={() => toggleTag(tag)}
              style={{
                padding: "8px 12px", borderRadius: "20px", border: "1px solid #ddd", cursor: "pointer",
                background: selectedTags.includes(tag) ? "#FF6B00" : "white",
                color: selectedTags.includes(tag) ? "white" : "black"
              }}>
              {tag}
            </button>
          ))}
        </div>

        <button onClick={handleRecommend} disabled={loading} 
          style={{ width: "100%", padding: "15px", background: "#333", color: "white", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "bold" }}>
          {loading ? "AI 분석 중..." : "맛집 추천 받기 🚀"}
        </button>

        {/* 결과 출력 */}
        <div style={{ marginTop: "20px", whiteSpace: "pre-wrap", background: "#f9f9f9", padding: "15px", borderRadius: "8px", fontSize: "14px", lineHeight: "1.6" }}>
          {result || "조건을 입력하고 추천을 받아보세요!"}
        </div>
      </div>

      {/* 2. 구글 맵 */}
      <div style={{ flex: 1 }}>
        {isLoaded ? (
          <GoogleMap mapContainerStyle={containerStyle} center={myLocation} zoom={14}>
            {/* 내 위치 (드래그 가능) */}
            <Marker position={myLocation} draggable={true} onDragEnd={(e) => setMyLocation({lat: e.latLng.lat(), lng: e.latLng.lng()})} label="📍" />
            
            {/* 반경 표시 */}
            <Circle center={myLocation} radius={distance * 1000} options={circleOptions} />
            
            {/* 추천된 식당 마커 */}
            {stores.map((store, idx) => (
              <Marker key={idx} position={{ lat: store.lat, lng: store.lng }} label={{ text: `${idx+1}`, color: "white", fontWeight: "bold" }} />
            ))}
          </GoogleMap>
        ) : <div>지도 로딩 중...</div>}
      </div>
    </div>
  );
}

export default App;