import React, { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import "./MyPage.css";

const StarDisplay = ({ value }) => (
  <span className="mp-stars">
    {[1, 2, 3, 4, 5].map((s) => (
      <span key={s} className={`mp-star ${s <= value ? "filled" : ""}`}>★</span>
    ))}
  </span>
);

const StarInput = ({ value, onChange }) => {
  const [hovered, setHovered] = useState(0);
  return (
    <span className="mp-stars">
      {[1, 2, 3, 4, 5].map((s) => (
        <span
          key={s}
          className={`mp-star clickable ${s <= (hovered || value) ? "filled" : ""}`}
          onMouseEnter={() => setHovered(s)}
          onMouseLeave={() => setHovered(0)}
          onClick={() => onChange(s)}
        >
          ★
        </span>
      ))}
    </span>
  );
};

const formatDate = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const MyPage = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);
  const [ratingMsgs, setRatingMsgs] = useState({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        const meRes = await axios.get("http://localhost:8000/me", { withCredentials: true });
        setUsername(meRes.data.username);

        const logsRes = await axios.get("http://localhost:8000/my-logs", { withCredentials: true });
        setLogs(logsRes.data);
      } catch (e) {
        navigate("/login");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [navigate]);

  const handleRate = async (logId, restaurantName, star, logIdx) => {
    try {
      await axios.post(
        "http://localhost:8000/rate",
        { search_log_id: logId, restaurant_name: restaurantName, rating: star },
        { withCredentials: true }
      );
      // 로컬 상태 업데이트
      setLogs((prev) =>
        prev.map((log, i) => {
          if (i !== logIdx) return log;
          return {
            ...log,
            ratings: { ...log.ratings, [restaurantName]: star },
          };
        })
      );
      setRatingMsgs((prev) => ({ ...prev, [logId]: "저장됨" }));
      setTimeout(() => setRatingMsgs((prev) => ({ ...prev, [logId]: "" })), 2000);
    } catch (e) {
      console.error(e);
    }
  };

  const handleLogout = async () => {
    await axios.post("http://localhost:8000/logout", {}, { withCredentials: true });
    navigate("/login");
  };

  if (loading) {
    return (
      <div className="mp-loading">
        <div className="mp-spinner"></div>
      </div>
    );
  }

  return (
    <div className="mp-container">
      <div className="mp-header">
        <div>
          <h1 className="mp-title">ChopChop</h1>
          <p className="mp-username">@{username}님의 마이페이지</p>
        </div>
        <div className="mp-header-actions">
          <button className="mp-nav-btn" onClick={() => navigate("/app")}>맛집 찾기</button>
          <button className="mp-nav-btn mp-logout-btn" onClick={handleLogout}>로그아웃</button>
        </div>
      </div>

      <div className="mp-content">
        <div className="mp-section-title">
          <h2>검색 기록</h2>
          <span className="mp-count">{logs.length}건</span>
        </div>

        {logs.length === 0 ? (
          <div className="mp-empty">
            <span className="mp-empty-icon">🍽️</span>
            <p>아직 검색 기록이 없습니다.</p>
            <button className="mp-go-btn" onClick={() => navigate("/app")}>
              맛집 찾으러 가기
            </button>
          </div>
        ) : (
          <div className="mp-logs">
            {logs.map((log, logIdx) => {
              const isExpanded = expandedId === log.id;
              const ratedCount = Object.keys(log.ratings || {}).length;
              return (
                <div key={log.id} className="mp-log-card">
                  <div
                    className="mp-log-header"
                    onClick={() => setExpandedId(isExpanded ? null : log.id)}
                  >
                    <div className="mp-log-meta">
                      <span className="mp-log-date">{formatDate(log.searched_at)}</span>
                      <div className="mp-log-tags">
                        {log.categories.map((c) => (
                          <span key={c} className="mp-tag">{c}</span>
                        ))}
                        {log.user_detail && (
                          <span className="mp-tag mp-tag-detail">"{log.user_detail}"</span>
                        )}
                      </div>
                    </div>
                    <div className="mp-log-summary">
                      <span className="mp-log-info">반경 {log.radius_km}km</span>
                      <span className="mp-log-info">추천 {log.stores.length}곳</span>
                      {ratedCount > 0 && (
                        <span className="mp-log-info mp-rated">별점 {ratedCount}개</span>
                      )}
                      <span className="mp-chevron">{isExpanded ? "▲" : "▼"}</span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mp-log-body">
                      {log.stores.length === 0 ? (
                        <p className="mp-no-stores">추천된 식당이 없습니다.</p>
                      ) : (
                        <>
                          <p className="mp-stores-label">추천 식당 및 별점</p>
                          {ratingMsgs[log.id] && (
                            <p className="mp-rating-saved">{ratingMsgs[log.id]}</p>
                          )}
                          <div className="mp-stores-list">
                            {log.stores.map((store, si) => {
                              const currentRating = log.ratings?.[store.name] || 0;
                              return (
                                <div key={si} className="mp-store-row">
                                  <span className="mp-store-num">{si + 1}</span>
                                  <span className="mp-store-name">{store.name}</span>
                                  <StarInput
                                    value={currentRating}
                                    onChange={(star) =>
                                      handleRate(log.id, store.name, star, logIdx)
                                    }
                                  />
                                  {currentRating > 0 && (
                                    <span className="mp-star-label">{currentRating}점</span>
                                  )}
                                </div>
                              );
                            })}
                          </div>

                          <details className="mp-result-detail">
                            <summary>추천 리포트 보기</summary>
                            <pre className="mp-result-text">{log.result_text}</pre>
                          </details>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default MyPage;
