#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import ast
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn


# -----------------------------
# Feature utils (must match training)
# -----------------------------
def _stable_hash(s: str) -> int:
    h = hashlib.md5(s.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "little", signed=False)

def _tokenize_categories(cat_str: Optional[str]) -> List[str]:
    if not cat_str:
        return []
    out = []
    for x in str(cat_str).split(","):
        t = x.strip()
        if t:
            out.append("cat:" + t.replace(" ", "_"))
    return out

def _parse_attr_value(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, bool):
        return ["true" if v else "false"]
    if isinstance(v, (int, float)):
        return [str(v)]
    if not isinstance(v, str):
        return [str(v)]
    s = v.strip()
    if not s:
        return []
    # Yelp-style dict string: "{'garage': False, 'street': True, ...}"
    if s.startswith("{") and s.endswith("}"):
        try:
            d = ast.literal_eval(s)
            if isinstance(d, dict):
                on = [str(k) for k, vv in d.items() if vv is True]
                return ["dict"] + (["on:" + x for x in on] if on else [])
        except Exception:
            return ["dict"]
    return [s.replace("u'", "").replace("'", "")]

def _build_item_tokens(place: Dict[str, Any], max_tokens: int) -> List[str]:
    toks: List[str] = []
    city = place.get("city")
    state = place.get("state")
    if city:
        toks.append("city:" + str(city).replace(" ", "_"))
    if state:
        toks.append("state:" + str(state))

    toks.extend(_tokenize_categories(place.get("categories")))

    attrs = place.get("attributes") or {}
    if isinstance(attrs, dict):
        for k, v in attrs.items():
            base = "attr:" + str(k)
            vals = _parse_attr_value(v)
            if not vals:
                toks.append(base)
            else:
                for vv in vals[:2]:
                    toks.append(base + "=" + vv)

    return toks[:max_tokens]

def _build_item_numeric(place: Dict[str, Any]) -> np.ndarray:
    def f(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    attrs = place.get("attributes") or {}
    pr = attrs.get("RestaurantsPriceRange2") if isinstance(attrs, dict) else None

    lat = f(place.get("latitude"))
    lng = f(place.get("longitude"))
    stars = f(place.get("stars"))
    rcnt = f(place.get("review_count"))
    is_open = f(place.get("is_open"))
    pr = f(pr)

    return np.array([lat, lng, stars, math.log1p(rcnt), is_open, pr], dtype=np.float32)

def _parse_dt_any(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
    return None

def _clip15(x: float) -> float:
    return 1.0 if x < 1.0 else 5.0 if x > 5.0 else x


# -----------------------------
# Model
# -----------------------------
class ItemEncoder(nn.Module):
    def __init__(self, hash_dim: int, k: int, num_dim: int, hidden: int = 256, dropout: float = 0.2):
        super().__init__()
        self.k = k
        self.emb = nn.Embedding(hash_dim, k)
        self.lin_num = nn.Linear(num_dim, k)
        self.mlp = nn.Sequential(
            nn.Linear(k + num_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.head_q = nn.Linear(hidden, k)
        self.head_b = nn.Linear(hidden, 1)

    def forward(self, flat_idx, flat_b, lens, xnum):
        B = xnum.shape[0]
        device = xnum.device
        sum_v = torch.zeros((B, self.k), device=device)
        if flat_idx.numel() > 0:
            vi = self.emb(flat_idx)
            sum_v.index_add_(0, flat_b, vi)
        lens_safe = torch.clamp(lens, min=1.0).unsqueeze(1)
        pooled = sum_v / torch.sqrt(lens_safe)
        h = self.mlp(torch.cat([pooled, xnum], dim=1))
        q_hat = self.head_q(h) + self.lin_num(xnum)
        b_hat = self.head_b(h).squeeze(1)
        return q_hat, b_hat


# -----------------------------
# Config
# -----------------------------
@dataclass(frozen=True)
class PredictorConfig:
    # service gating
    min_history: int = 10

    # online-fit policy (grid best on your run)
    fit_N: int = 20               # use most recent N for fitting
    recent_cap: int = 200         # hard cap; if >= fit_N it won't affect
    tau_days: float = 240.0       # recency weight strength
    lam_base: float = 10.0        # ridge base; schedule depends on n_used
    use_time_if_available: bool = True

    # fallback when history < min_history
    # "mu" -> return global mean only
    # "mu_item" -> return mu + item_bias (from encoder)
    fallback: str = "mu_item"

    # caching
    enable_cache: bool = True


# -----------------------------
# Math: weighted ridge + schedules
# -----------------------------
def _lam_schedule(n: int, base: float) -> float:
    if n < 10:
        return base * 3.0
    if n < 30:
        return base * 2.0
    if n < 100:
        return base
    if n < 300:
        return base * 0.5
    return base * 0.3

def _recency_weights_time(dts: List[datetime], tau_days: float) -> np.ndarray:
    tmax = dts[-1]
    w = np.empty((len(dts),), dtype=np.float32)
    for i, dt in enumerate(dts):
        delta_days = (tmax - dt).total_seconds() / 86400.0
        w[i] = math.exp(-delta_days / max(tau_days, 1e-6))
    return w

def _recency_weights_rank(n: int, tau_rank: float) -> np.ndarray:
    # recent=0, old=n-1
    ages = np.arange(n - 1, -1, -1, dtype=np.float32)
    return np.exp(-ages / max(tau_rank, 1e-6)).astype(np.float32)

def _weighted_ridge_fit(Q: np.ndarray, y: np.ndarray, mu: float, b_i: np.ndarray,
                        lam: float, w: Optional[np.ndarray]) -> Tuple[np.ndarray, float]:
    """
    Solve theta=[b_u, p_u] in:
      y - mu - b_i = b_u + p_u^T q_i
    weighted ridge:
      ||sqrt(w)*(t - A theta)||^2 + lam||theta||^2
    """
    n, k = Q.shape
    A = np.concatenate([np.ones((n, 1), dtype=np.float32), Q], axis=1)
    t = (y - mu - b_i).astype(np.float32)

    if w is not None:
        w = np.asarray(w, dtype=np.float32)
        w = np.clip(w, 1e-6, 1e6)
        # normalize weights to mean 1 for stable lam meaning
        w = w / (float(w.mean()) + 1e-8)
        s = np.sqrt(w).astype(np.float32)
        Aw = A * s[:, None]
        tw = t * s
    else:
        Aw = A
        tw = t

    # solve in float64 for numerical stability
    Aw64 = Aw.astype(np.float64)
    tw64 = tw.astype(np.float64)
    XtX = Aw64.T @ Aw64 + float(lam) * np.eye(k + 1, dtype=np.float64)
    Xty = Aw64.T @ tw64
    theta = np.linalg.solve(XtX, Xty).astype(np.float32)

    b_u = float(theta[0])
    p_u = theta[1:].astype(np.float32)
    return p_u, b_u


# -----------------------------
# Predictor
# -----------------------------
class RatingPredictor:
    """
    Service-facing predictor:
      - place meta -> (q_hat, b_hat)
      - history(>=min_history) -> online fit (p_u, b_u) with (cap + recency weights + ridge)
      - output predicted rating in [1,5]
    """

    def __init__(self, item_encoder_pt: str, device: Optional[str] = None):
        # PyTorch 2.6+ safe load (your own file, trusted)
        ckpt = torch.load(item_encoder_pt, map_location="cpu", weights_only=False)

        self.mu: float = float(ckpt["mu"])
        self.k: int = int(ckpt["k"])
        self.hash_dim: int = int(ckpt["hash_dim"])
        self.max_tokens: int = int(ckpt["max_tokens"])
        self.num_mean: np.ndarray = ckpt["num_mean"].astype(np.float32)
        self.num_std: np.ndarray = ckpt["num_std"].astype(np.float32)
        self.num_dim: int = int(ckpt["num_dim"])
        self.hidden: int = int(ckpt["hidden"])
        self.dropout: float = float(ckpt["dropout"])

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        self.enc = ItemEncoder(self.hash_dim, self.k, self.num_dim, self.hidden, self.dropout).to(self.device)
        self.enc.load_state_dict(ckpt["state_dict"])
        self.enc.eval()

        self._cache: Dict[str, Tuple[np.ndarray, float]] = {}

    def encode_item(self, place: Dict[str, Any], enable_cache: bool = True) -> Tuple[np.ndarray, float]:
        # cache key: use business_id/place_id/id if exists
        key = place.get("business_id") or place.get("place_id") or place.get("id")
        key = str(key) if key is not None else None

        if enable_cache and key is not None and key in self._cache:
            return self._cache[key]

        toks = _build_item_tokens(place, self.max_tokens)
        idxs = [_stable_hash(t) % self.hash_dim for t in toks]
        xnum = _build_item_numeric(place)
        xnum = (xnum - self.num_mean) / self.num_std

        x_t = torch.tensor(xnum[None, :], dtype=torch.float32, device=self.device)

        flat = torch.tensor(idxs, dtype=torch.long, device=self.device) if idxs else torch.zeros((0,), dtype=torch.long, device=self.device)
        bidx = torch.zeros((len(idxs),), dtype=torch.long, device=self.device) if idxs else torch.zeros((0,), dtype=torch.long, device=self.device)
        lens = torch.tensor([len(idxs)], dtype=torch.float32, device=self.device)

        with torch.no_grad():
            q, b = self.enc(flat, bidx, lens, x_t)

        out = (q.detach().cpu().numpy()[0].astype(np.float32), float(b.detach().cpu().numpy()[0]))

        if enable_cache and key is not None:
            self._cache[key] = out
        return out

    def _prepare_history(self, history: List[Dict[str, Any]], cfg: PredictorConfig
                         ) -> Tuple[List[Dict[str, Any]], np.ndarray, Optional[np.ndarray], Dict[str, Any]]:
        """
        Returns:
          places_used(list), ratings(np), weights(np or None), debug
        """
        rows: List[Tuple[Optional[datetime], Dict[str, Any], float]] = []
        for h in history:
            place = h["place"]
            rating = float(h["rating"])
            dt = _parse_dt_any(h.get("date")) if cfg.use_time_if_available else None
            rows.append((dt, place, rating))

        # If all dates exist -> time-based sorting; else keep order (assumed recency order)
        all_have_dt = all(dt is not None for dt, _, _ in rows) if rows else False
        if cfg.use_time_if_available and all_have_dt:
            rows.sort(key=lambda x: x[0])  # ascending

        # apply recent_cap
        if cfg.recent_cap and len(rows) > cfg.recent_cap:
            rows = rows[-cfg.recent_cap:]

        # apply fit_N (service-tuned)
        if cfg.fit_N and len(rows) > cfg.fit_N:
            rows = rows[-cfg.fit_N:]

        places = [p for _, p, _ in rows]
        ratings = np.asarray([r for *_, r in rows], dtype=np.float32)

        # weights
        if len(rows) == 0:
            return [], ratings, None, {"n_used": 0}

        if cfg.use_time_if_available and all_have_dt:
            dts = [dt for dt, _, _ in rows]  # all not None
            w = _recency_weights_time(dts, tau_days=cfg.tau_days)
        else:
            # rank-based fallback
            w = _recency_weights_rank(len(rows), tau_rank=cfg.tau_days)

        dbg = {
            "n_used": int(len(rows)),
            "fit_N": int(cfg.fit_N),
            "recent_cap": int(cfg.recent_cap),
            "tau_days": float(cfg.tau_days),
            "weights_mode": "time" if (cfg.use_time_if_available and all_have_dt) else "rank",
            "w_min": float(w.min()),
            "w_med": float(np.median(w)),
            "w_max": float(w.max()),
        }
        return places, ratings, w, dbg

    def fit_user(self, history: List[Dict[str, Any]], cfg: PredictorConfig
                 ) -> Tuple[np.ndarray, float, Dict[str, Any]]:
        places, ratings, w, dbg = self._prepare_history(history, cfg)
        n = len(places)
        if n == 0:
            return np.zeros((self.k,), np.float32), 0.0, dbg

        Q = np.zeros((n, self.k), dtype=np.float32)
        b = np.zeros((n,), dtype=np.float32)
        for i, place in enumerate(places):
            qi, bi = self.encode_item(place, enable_cache=cfg.enable_cache)
            Q[i] = qi
            b[i] = float(bi)

        lam = _lam_schedule(n, base=cfg.lam_base)
        p_u, b_u = _weighted_ridge_fit(Q, ratings, self.mu, b, lam=lam, w=w)
        dbg["lam"] = float(lam)
        return p_u, b_u, dbg

    def predict_rating(self,
                       history: List[Dict[str, Any]],
                       query_place: Dict[str, Any],
                       cfg: PredictorConfig = PredictorConfig(),
                       return_debug: bool = False) -> Dict[str, Any]:
        """
        Main entry:
          history: list of {place, rating, date?}
          query_place: place meta dict
        Returns: {"pred_rating": float, "mu": float, ...optional debug...}
        """
        # fallback if insufficient history
        if len(history) < cfg.min_history:
            q_i, b_i = self.encode_item(query_place, enable_cache=cfg.enable_cache)
            if cfg.fallback == "mu_item":
                pred = _clip15(self.mu + float(b_i))
            elif cfg.fallback == "mu":
                pred = _clip15(self.mu)
            else:
                raise ValueError(f"Unknown fallback={cfg.fallback}")

            out = {"pred_rating": float(pred), "mu": float(self.mu), "fallback": True, "n_history": int(len(history))}
            if return_debug:
                out["debug"] = {"reason": "insufficient_history", "min_history": cfg.min_history}
            return out

        p_u, b_u, dbg = self.fit_user(history, cfg)
        q_i, b_i = self.encode_item(query_place, enable_cache=cfg.enable_cache)

        pred = self.mu + float(b_u) + float(b_i) + float(np.dot(p_u, q_i))
        pred = _clip15(float(pred))

        out = {"pred_rating": float(pred), "mu": float(self.mu), "fallback": False}
        if return_debug:
            out["debug"] = dbg
        return out