import React, { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import {
  GoogleMap,
  useJsApiLoader,
  Marker,
  Circle,
} from "@react-google-maps/api";
import "./App.css";

const GOOGLE_API_KEY = process.env.REACT_APP_GOOGLE_MAPS_API_KEY;

const circleOptions = {
  strokeColor: "#007AFF",
  strokeOpacity: 0.8,
  strokeWeight: 2,
  fillColor: "#007AFF",
  fillOpacity: 0.15,
  clickable: false,
  draggable: false,
  editable: false,
  visible: true,
  zIndex: 1,
};

const TAGS = [
  "카페",
  "술집",
  "베이커리",
  "한식",
  "이탈리안",
  "일식",
  "중식",
  "멕시칸",
  "인도요리",
  "파인다이닝",
  "가성비",
  "브런치",
  "뷔페",
  "혼밥",
  "데이트",
  "조용한",
  "야외석",
];

const StarRating = ({ value, onChange }) => {
  const [hovered, setHovered] = useState(0);
  return (
    <div className="star-rating">
      {[1, 2, 3, 4, 5].map((star) => (
        <span
          key={star}
          className={`star ${star <= (hovered || value) ? "filled" : ""}`}
          onMouseEnter={() => setHovered(star)}
          onMouseLeave={() => setHovered(0)}
          onClick={() => onChange(star)}
        >
          ★
        </span>
      ))}
    </div>
  );
};

const App = () => {
  const navigate = useNavigate();
  const [myLocation, setMyLocation] = useState({ lat: 37.5665, lng: 126.978 });
  const [distance, setDistance] = useState(2.0);
  const [showCircle, setShowCircle] = useState(true);
  const [selectedTags, setSelectedTags] = useState([]);
  const [userText, setUserText] = useState("");

  const [activeFilters, setActiveFilters] = useState({
    BusinessParking: 0,
    RestaurantsGoodForGroups: 0,
    GoodForKids: 0,
    DineIn: 0,
    Vegetarian: 0,
  });

  const [stores, setStores] = useState([]);
  const [result, setResult] = useState("");
  const [scannedCount, setScannedCount] = useState(0);
  const [analyzedCount, setAnalyzedCount] = useState(0);
  const [logId, setLogId] = useState(null);
  const [ratings, setRatings] = useState({});       // {restaurant_name: rating}
  const [ratingMsg, setRatingMsg] = useState("");   // 저장 성공/실패 메시지

  const [loading, setLoading] = useState(false);

  const { isLoaded } = useJsApiLoader({
    id: "google-map-script",
    googleMapsApiKey: GOOGLE_API_KEY,
    language: "ko",
  });

  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setMyLocation({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
          });
        },
        (error) => {
          console.log("위치 권한 거부 또는 에러:", error);
        }
      );
    }
  }, []);

  useEffect(() => {
    setShowCircle(false);
    const timer = setTimeout(() => setShowCircle(true), 10);
    return () => clearTimeout(timer);
  }, [myLocation.lat, myLocation.lng, distance]);

  const toggleFilter = (key) => {
    setActiveFilters((prev) => ({
      ...prev,
      [key]: prev[key] === 0 ? 1 : 0,
    }));
  };

  const handleRecommend = async () => {
    if (selectedTags.length === 0 && userText.trim() === "") {
      alert("키워드를 선택하거나 찾고싶은 맛집을 입력해주세요.");
      return;
    }

    setLoading(true);
    setResult("");
    setStores([]);
    setScannedCount(0);
    setAnalyzedCount(0);
    setLogId(null);
    setRatings({});
    setRatingMsg("");

    // OpenStreetMap Nominatim으로 현재 위치 → 지역명 변환 (무료, API 키 불필요)
    let regionName = null;
    try {
      const geoRes = await fetch(
        `https://nominatim.openstreetmap.org/reverse?lat=${myLocation.lat}&lon=${myLocation.lng}&format=json&accept-language=ko`,
        { headers: { "Accept-Language": "ko" } }
      );
      const geoData = await geoRes.json();
      const addr = geoData.address || {};
      regionName =
        (addr.borough || addr.city_district || "") +
        (addr.suburb ? " " + addr.suburb : "") ||
        addr.city ||
        geoData.display_name?.split(",")[0] ||
        null;
      if (regionName) regionName = regionName.trim();
    } catch (e) {
      // 지오코딩 실패 시 무시
    }

    try {
      const res = await axios.post(
        "http://localhost:8000/recommend",
        {
          radius_km: parseFloat(distance),
          categories: selectedTags,
          user_detail: userText,
          lat: myLocation.lat,
          lng: myLocation.lng,
          region_name: regionName,
          filters: activeFilters,
        },
        { withCredentials: true }
      );
      setResult(res.data.result);
      setStores(res.data.stores || []);
      setScannedCount(res.data.scanned_count || 0);
      setAnalyzedCount(res.data.analyzed_count || 0);
      setLogId(res.data.log_id || null);
    } catch (e) {
      console.error(e);
      alert("추천 중 오류가 발생했습니다.");
    }
    setLoading(false);
  };

  const handleRate = async (restaurantName, star) => {
    if (!logId) return;
    setRatings((prev) => ({ ...prev, [restaurantName]: star }));
    try {
      await axios.post(
        "http://localhost:8000/rate",
        { search_log_id: logId, restaurant_name: restaurantName, rating: star },
        { withCredentials: true }
      );
      setRatingMsg("별점이 저장되었습니다.");
      setTimeout(() => setRatingMsg(""), 2000);
    } catch (e) {
      console.error(e);
      setRatingMsg("별점 저장에 실패했습니다.");
      setTimeout(() => setRatingMsg(""), 2000);
    }
  };

  const toggleTag = (tag) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const handleLocationReset = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition((position) => {
        setMyLocation({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
      });
    }
  };

  const handleLogout = async () => {
    await axios.post("http://localhost:8000/logout", {}, { withCredentials: true });
    navigate("/login");
  };

  return (
    <div className="App">
      {loading && (
        <div className="loading-overlay">
          <div className="spinner"></div>
        </div>
      )}

      <aside className="sidebar">
        <header className="header">
          <div className="header-top">
            <div>
              <h1 className="title">ChopChop</h1>
              <p className="subtitle">AI 맛집 추천 서비스</p>
            </div>
            <div className="header-actions">
              <button className="nav-btn" onClick={() => navigate("/mypage")}>마이페이지</button>
              <button className="nav-btn logout-btn" onClick={handleLogout}>로그아웃</button>
            </div>
          </div>
        </header>

        <div className="control-group">
          <label className="control-label">
            탐색 반경: <span>{distance} km</span>
          </label>
          <input
            type="range"
            min="0.5"
            max="10.0"
            step="0.5"
            value={distance}
            onChange={(e) => setDistance(e.target.value)}
            className="radius-slider"
          />
        </div>

        <div className="control-group">
          <label className="control-label">필수 옵션 (클릭시 필터링)</label>
          <div
            className="filter-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "8px",
            }}
          >
            <button
              className={`filter-btn ${activeFilters.BusinessParking ? "active" : ""}`}
              onClick={() => toggleFilter("BusinessParking")}
              style={btnStyle(activeFilters.BusinessParking)}
            >
              🚗 주차 가능
            </button>
            <button
              className={`filter-btn ${activeFilters.RestaurantsGoodForGroups ? "active" : ""}`}
              onClick={() => toggleFilter("RestaurantsGoodForGroups")}
              style={btnStyle(activeFilters.RestaurantsGoodForGroups)}
            >
              👨‍👩‍👧‍👦 단체석
            </button>
            <button
              className={`filter-btn ${activeFilters.GoodForKids ? "active" : ""}`}
              onClick={() => toggleFilter("GoodForKids")}
              style={btnStyle(activeFilters.GoodForKids)}
            >
              👶 예스키즈존
            </button>
            <button
              className={`filter-btn ${activeFilters.DineIn ? "active" : ""}`}
              onClick={() => toggleFilter("DineIn")}
              style={btnStyle(activeFilters.DineIn)}
            >
              🍽️ 매장 식사
            </button>
            <button
              className={`filter-btn ${activeFilters.Vegetarian ? "active" : ""}`}
              onClick={() => toggleFilter("Vegetarian")}
              style={btnStyle(activeFilters.Vegetarian)}
            >
              🥗 채식 옵션
            </button>
          </div>
        </div>

        <div className="control-group">
          <label className="control-label">원하는 맛집을 설명해주세요</label>
          <textarea
            value={userText}
            onChange={(e) => setUserText(e.target.value)}
            placeholder="예: 조용한 분위기에서 커피가 맛있는 카페"
            className="text-input"
          />
        </div>

        <div className="control-group">
          <label className="control-label">또는 키워드를 선택하세요</label>
          <div className="tag-list">
            {TAGS.map((tag) => (
              <button
                key={tag}
                onClick={() => toggleTag(tag)}
                className={`tag-btn ${selectedTags.includes(tag) ? "selected" : ""}`}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        <div className="results-panel">
          {result ? (
            <>
              <div className="stats-bar">
                <div className="stat-item">
                  탐색된 식당: <span>{scannedCount}</span>
                </div>
                <div className="stat-item">
                  분석된 식당: <span>{analyzedCount}</span>
                </div>
              </div>
              <pre className="results-content">{result}</pre>

              {stores.length > 0 && logId && (
                <div className="rating-section">
                  <p className="rating-title">추천 식당 별점 평가</p>
                  {ratingMsg && <p className="rating-msg">{ratingMsg}</p>}
                  {stores.map((s, idx) => (
                    <div key={idx} className="rating-row">
                      <span className="rating-name">
                        {idx + 1}. {s.name}
                      </span>
                      <StarRating
                        value={ratings[s.name] || 0}
                        onChange={(star) => handleRate(s.name, star)}
                      />
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="results-placeholder">
              <span className="results-placeholder-icon">🍽️</span>
              <p>
                AI 추천 결과가
                <br />
                여기에 표시됩니다.
              </p>
            </div>
          )}
        </div>

        <button
          onClick={handleRecommend}
          disabled={loading}
          className="action-button"
        >
          {loading ? "분석 중..." : "맛집 찾기"}
        </button>
      </aside>

      <main className="map-container">
        <button
          className="location-button"
          onClick={handleLocationReset}
          title="현재 위치로 이동"
        >
          📍
        </button>

        {isLoaded && (
          <GoogleMap
            mapContainerStyle={{ width: "100%", height: "100%" }}
            center={myLocation}
            zoom={13}
            options={{
              styles: [
                { elementType: "geometry", stylers: [{ color: "#1a1a1c" }] },
                { elementType: "labels.text.stroke", stylers: [{ color: "#1a1a1c" }] },
                { elementType: "labels.text.fill", stylers: [{ color: "#636366" }] },
                {
                  featureType: "administrative.locality",
                  elementType: "labels.text.fill",
                  stylers: [{ color: "#ffffff" }, { visibility: "on" }],
                },
                {
                  featureType: "administrative.neighborhood",
                  elementType: "labels.text.fill",
                  stylers: [{ color: "#8d8d92" }, { visibility: "on" }],
                },
                {
                  featureType: "poi",
                  elementType: "labels.text.fill",
                  stylers: [{ color: "#636366" }],
                },
                {
                  featureType: "poi.business",
                  stylers: [{ visibility: "off" }],
                },
                {
                  featureType: "road",
                  elementType: "geometry",
                  stylers: [{ color: "#2c2c2e" }, { visibility: "simplified" }],
                },
                {
                  featureType: "road",
                  elementType: "labels",
                  stylers: [{ visibility: "off" }],
                },
                {
                  featureType: "road.highway",
                  elementType: "geometry",
                  stylers: [{ color: "#3a3a3c" }],
                },
                {
                  featureType: "water",
                  elementType: "geometry",
                  stylers: [{ color: "#0a1929" }],
                },
                {
                  featureType: "water",
                  elementType: "labels.text.fill",
                  stylers: [{ color: "#007aff" }],
                },
                {
                  featureType: "transit",
                  stylers: [{ visibility: "off" }],
                },
              ],
              disableDefaultUI: true,
              gestureHandling: "greedy",
            }}
          >
            <Marker
              position={myLocation}
              draggable={true}
              onDragEnd={(e) => {
                const newPos = { lat: e.latLng.lat(), lng: e.latLng.lng() };
                setMyLocation(newPos);
                setStores([]);
                setResult("");
                setScannedCount(0);
                setAnalyzedCount(0);
                setLogId(null);
                setRatings({});
              }}
              title="현재 위치 (드래그로 이동)"
              icon={{
                path:
                  window.google && window.google.maps
                    ? window.google.maps.SymbolPath.CIRCLE
                    : "",
                scale: 8,
                fillColor: "#007AFF",
                fillOpacity: 1,
                strokeWeight: 2,
                strokeColor: "white",
              }}
            />

            {stores.map((s, idx) => (
              <Marker
                key={`store-${idx}`}
                position={{ lat: s.lat, lng: s.lng }}
                label={{
                  text: (idx + 1).toString(),
                  color: "white",
                  fontWeight: "bold",
                }}
                title={s.name}
              />
            ))}

            {showCircle && (
              <Circle
                center={myLocation}
                radius={parseFloat(distance) * 1000}
                options={circleOptions}
              />
            )}
          </GoogleMap>
        )}
      </main>
    </div>
  );
};

const btnStyle = (isActive) => ({
  padding: "8px",
  border: "1px solid #444",
  borderRadius: "8px",
  backgroundColor: isActive ? "#007AFF" : "#2c2c2c",
  color: "white",
  cursor: "pointer",
  fontSize: "0.9rem",
  transition: "all 0.2s",
});

export default App;
