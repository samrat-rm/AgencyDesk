import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, getSession, setSession } from "../api.js";

const DEMO_ACCOUNTS = [
  "priya@pixel.co",
  "arjun@pixel.co",
  "rahul@devmail.com",
  "maya@bloombakery.com",
  "nora@northwind.studio",
];

// Screen 1: log in, then pick which agency to work in.
// Step 1 (POST /auth/login) proves who you are and lists your memberships.
// Step 2 (POST /auth/select-agency) gets an access token for ONE agency.
export default function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const switching = params.get("switch") === "1";
  const existing = getSession();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("password123");
  const [memberships, setMemberships] = useState(switching ? existing.memberships || [] : []);
  const [error, setError] = useState("");

  async function logIn(e) {
    e.preventDefault();
    setError("");
    try {
      const data = await api("/auth/login", { method: "POST", body: { email, password }, token: "" });
      setSession({ email: email.trim().toLowerCase(), loginToken: data.login_token, memberships: data.memberships });
      setMemberships(data.memberships);
    } catch (err) {
      setError(err.message);
    }
  }

  async function choose(m) {
    setError("");
    const s = getSession();
    try {
      // When switching, the current access token works too; the login token only lasts 10 minutes.
      const data = await api("/auth/select-agency", {
        method: "POST",
        body: { agency_id: m.agency_id },
        token: s.accessToken || s.loginToken,
      });
      setSession({ accessToken: data.access_token, membership: data.membership });
      navigate("/projects");
    } catch (err) {
      setError(err.message);
    }
  }

  if (memberships.length > 0) {
    return (
      <div>
        <h2>Choose an agency</h2>
        <p>{getSession().email} belongs to {memberships.length} agenc{memberships.length === 1 ? "y" : "ies"}:</p>
        <ul>
          {memberships.map((m) => (
            <li key={m.agency_id}>
              <button onClick={() => choose(m)}>
                {m.agency_name} as {m.role}
                {m.client_name ? ` (client: ${m.client_name})` : ""}
              </button>
            </li>
          ))}
        </ul>
        <button onClick={() => setMemberships([])}>Log in as someone else</button>
        {error && <p style={{ color: "red" }}>{error}</p>}
      </div>
    );
  }

  return (
    <div>
      <h2>Log in</h2>
      <form onSubmit={logIn}>
        <p>
          <label>
            Email <input value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
        </p>
        <p>
          <label>
            Password <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
        </p>
        <button type="submit">Log in</button>
      </form>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <p>Demo accounts (password: password123):</p>
      <ul>
        {DEMO_ACCOUNTS.map((a) => (
          <li key={a}>
            <button type="button" onClick={() => setEmail(a)}>{a}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
