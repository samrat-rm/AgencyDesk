import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { clearSession, getSession } from "./api.js";
import ClientPortal from "./pages/ClientPortal.jsx";
import Login from "./pages/Login.jsx";
import Projects from "./pages/Projects.jsx";
import Tasks from "./pages/Tasks.jsx";

// The frontend is deliberately plain: its only job is to show the access rules on
// screen. Every rule is enforced by the backend; hiding a button here is cosmetic.

function Header() {
  const navigate = useNavigate();
  const { email, membership } = getSession();
  if (!membership) return null;
  return (
    <div>
      <p>
        Signed in as <b>{email}</b>, <b>{membership.role}</b> at <b>{membership.agency_name}</b>
        {membership.client_name && <> (client: {membership.client_name})</>}
        {" | "}
        <Link to="/projects">Projects</Link>
        {" | "}
        <Link to="/login?switch=1">Switch agency</Link>
        {" | "}
        <button
          onClick={() => {
            clearSession();
            navigate("/login");
          }}
        >
          Log out
        </button>
      </p>
      <hr />
    </div>
  );
}

function RequireAgency({ children }) {
  return getSession().accessToken ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <div style={{ padding: 16, fontFamily: "sans-serif" }}>
      <h1>AgencyDesk</h1>
      <Header />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/projects" element={<RequireAgency><Projects /></RequireAgency>} />
        <Route path="/projects/:projectId" element={<RequireAgency><Tasks /></RequireAgency>} />
        <Route path="/portal/:projectId" element={<RequireAgency><ClientPortal /></RequireAgency>} />
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
    </div>
  );
}
