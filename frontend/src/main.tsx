import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "./components/Layout";
import { EmptyState } from "./components/ui";
import ModelPage from "./pages/ModelPage";
import Overview from "./pages/Overview";
import PhoneCheck from "./pages/PhoneCheck";
import SettingsPage from "./pages/SettingsPage";
import TrapDetail from "./pages/TrapDetail";
import WhatIfPage from "./pages/WhatIfPage";
import { SettingsProvider } from "./settings";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SettingsProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Overview />} />
            <Route path="/traps/:id" element={<TrapDetail />} />
            <Route path="/phone-check" element={<PhoneCheck />} />
            <Route path="/model" element={<ModelPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/what-if" element={<WhatIfPage />} />
            <Route path="*" element={<EmptyState title="Page not found" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SettingsProvider>
  </StrictMode>,
);
