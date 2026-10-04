import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { HistoryAccessProvider } from "./historyAccess";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename="/console">
      <HistoryAccessProvider>
        <App />
      </HistoryAccessProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
