import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getSession } from "../api.js";

// Screen 2: the projects this person can see in this agency. The SAME request
// (GET /projects) returns different lists for admin, member and client: the
// backend's scoping decides, not this page.
export default function Projects() {
  const { membership } = getSession();
  const isClient = membership.role === "client_user";
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/projects").then(setProjects).catch((e) => setError(e.message));
  }, []);

  if (error) return <p style={{ color: "red" }}>{error}</p>;
  if (!projects) return <p>Loading...</p>;

  return (
    <div>
      <h2>{isClient ? "Your projects" : "Projects"}</h2>
      {projects.length === 0 && <p>No projects visible to you.</p>}
      <ul>
        {projects.map((p) => (
          <li key={p.id}>
            {/* Clients go to the portal view; staff go to the full task board. */}
            <Link to={isClient ? `/portal/${p.id}` : `/projects/${p.id}`}>{p.name}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
