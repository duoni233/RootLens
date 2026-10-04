import {
  Activity,
  History,
  LockKeyhole,
  PanelLeftClose,
  SearchCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useHistoryAccess } from "./historyAccess";
import { api } from "./lib/api";
import { DetailPage } from "./pages/DetailPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewDiagnosis } from "./pages/NewDiagnosis";

export function App() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const { token } = useHistoryAccess();
  useEffect(() => {
    let active = true;
    const check = () =>
      api
        .health()
        .then(() => {
          if (active) setOnline(true);
        })
        .catch(() => {
          if (active) setOnline(false);
        });
    check();
    const timer = window.setInterval(check, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  return (
    <div className="app-shell">
      <aside className={`sidebar ${navOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <Activity size={21} strokeWidth={2.3} />
          </div>
          <div>
            <strong>RootLens</strong>
            <span>DIAGNOSIS CONSOLE</span>
          </div>
        </div>
        <div className="nav-label">工作台</div>
        <nav aria-label="主导航">
          <NavLink
            to="/"
            end
            onClick={() => setNavOpen(false)}
            className={({ isActive }) =>
              `nav-item ${isActive ? "nav-active" : ""}`
            }
          >
            <SearchCheck size={18} /> 新建诊断
          </NavLink>
          <NavLink
            to="/history"
            onClick={() => setNavOpen(false)}
            className={({ isActive }) =>
              `nav-item ${isActive ? "nav-active" : ""}`
            }
          >
            <History size={18} /> 诊断历史
            {!token && <LockKeyhole size={13} className="nav-lock" />}
          </NavLink>
        </nav>
        <div className="sidebar-foot">
          <div
            className={`health-dot ${online === true ? "health-online" : online === false ? "health-offline" : ""}`}
          />
          <div>
            <strong>RootLens API</strong>
            <span>
              {online === true
                ? "运行正常"
                : online === false
                  ? "连接失败"
                  : "正在检查"}
            </span>
          </div>
        </div>
      </aside>
      {navOpen && (
        <button
          className="sidebar-scrim"
          aria-label="关闭导航"
          onClick={() => setNavOpen(false)}
        />
      )}
      <main className="main-area">
        <div className="mobile-top">
          <button
            className="icon-button"
            aria-label="打开导航"
            title="打开导航"
            onClick={() => setNavOpen(true)}
          >
            <PanelLeftClose size={20} />
          </button>
          <strong>RootLens</strong>
          <span
            className={`health-dot ${online ? "health-online" : "health-offline"}`}
          />
        </div>
        <Routes>
          <Route path="/" element={<NewDiagnosis />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/history/:runId" element={<DetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
