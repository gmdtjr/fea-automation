import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./index.css";
import Jobs from "./pages/Jobs";
import JobDetail from "./pages/JobDetail";
import CutReview from "./pages/CutReview";
import Report from "./pages/Report";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/jobs" replace />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/jobs/:id/cut-review" element={<CutReview />} />
        <Route path="/jobs/:id/report" element={<Report />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
