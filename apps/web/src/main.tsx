import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./styles.css";
import { Layout } from "./components/common";
import { Login, Onboarding } from "./app/auth";
import { Inbox, JobDetailPage } from "./app/inbox";
import { Studio } from "./app/studio";
import { Analytics, Messages, Pipeline, Runs, SettingsPage } from "./app/screens";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route element={<Layout />}>
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/studio/:id" element={<Studio />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/messages" element={<Messages />} />
          <Route path="/messages/:threadId" element={<Messages />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<Runs />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/inbox" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
