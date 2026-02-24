import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./index.css";

// ✅ 임시 테스트: 직접 import 확인
import AppComponent from "./pages/App";
import LoginComponent from "./pages/Login";
import RegisterComponent from "./pages/Register";
import PrivateRouteComponent from "./components/PrivateRoute";

console.log("App:", AppComponent);
console.log("Login:", LoginComponent);
console.log("Register:", RegisterComponent);

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
    </Routes>
  </BrowserRouter>,
);
