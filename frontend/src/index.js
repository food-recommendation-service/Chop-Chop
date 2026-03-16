import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./index.css";

import AppComponent from "./pages/App";
import LoginComponent from "./pages/Login";
import RegisterComponent from "./pages/Register";
import MyPageComponent from "./pages/MyPage";
import PrivateRouteComponent from "./components/PrivateRoute";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginComponent />} />
      <Route path="/register" element={<RegisterComponent />} />
      <Route
        path="/app"
        element={
          <PrivateRouteComponent>
            <AppComponent />
          </PrivateRouteComponent>
        }
      />
      <Route
        path="/mypage"
        element={
          <PrivateRouteComponent>
            <MyPageComponent />
          </PrivateRouteComponent>
        }
      />
    </Routes>
  </BrowserRouter>,
);
