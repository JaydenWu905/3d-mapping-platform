import { NavLink } from 'react-router-dom';

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">🗺️</div>
        <div>
          <div className="brand-title">三维建图平台</div>
          <div className="brand-sub">Phase 1 · Mock Runner</div>
        </div>
      </div>
      <nav className="sidebar-nav">
        <NavLink to="/" end>
          <span className="nav-icon">📋</span> 任务列表
        </NavLink>
        <NavLink to="/jobs/new">
          <span className="nav-icon">➕</span> 新建任务
        </NavLink>
      </nav>
      <div className="sidebar-foot">
        <div className="foot-line">Pose → Surface → ESDF</div>
        <div className="foot-line">React · FastAPI · SSE</div>
      </div>
    </aside>
  );
}