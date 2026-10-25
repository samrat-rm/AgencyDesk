import { Fragment, useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { api, getSession } from "../api.js";
import { Comments, DashboardLine, Files, VisibilityTag } from "../shared.jsx";

const STATUSES = ["todo", "in_progress", "in_review", "done"];

// Screen 3: the agency's view of a project. Shows every task the person may see,
// internal ones included, with the internal / client-visible flag shown plainly.
export default function Tasks() {
  const { projectId } = useParams();
  // A client who types a staff URL is sent to the portal. (Convenience only: the
  // backend would refuse the staff-only calls anyway.)
  if (getSession().membership?.role === "client_user") return <Navigate to={`/portal/${projectId}`} replace />;
  return <StaffBoard projectId={projectId} />;
}

function StaffBoard({ projectId }) {
  const [project, setProject] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [members, setMembers] = useState([]);
  const [open, setOpen] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ title: "", visibility: "internal", priority: "medium", assignee_id: "" });

  async function load() {
    try {
      const [p, t, m] = await Promise.all([
        api(`/projects/${projectId}`),
        api(`/tasks?project_id=${projectId}`),
        api(`/projects/${projectId}/members`),
      ]);
      setProject(p);
      setTasks(t);
      setMembers(m);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(err.message);
    }
  }
  useEffect(() => {
    load();
  }, [projectId]);

  const nameOf = (id) => (id ? members.find((m) => m.user_id === id)?.full_name || "(not on project)" : "unassigned");

  async function changeStatus(task, status) {
    setError("");
    try {
      await api(`/tasks/${task.id}`, { method: "PATCH", body: { status } });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function createTask(e) {
    e.preventDefault();
    setError("");
    try {
      await api("/tasks", {
        method: "POST",
        body: { ...form, project_id: projectId, assignee_id: form.assignee_id || null },
      });
      setForm({ ...form, title: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (error && !project) return <p style={{ color: "red" }}>{error}</p>;
  if (!project) return <p>Loading...</p>;

  return (
    <div>
      <h2>{project.name} (agency view)</h2>
      <DashboardLine projectId={projectId} refreshKey={refreshKey} />
      <p>Team: {members.map((m) => m.full_name).join(", ") || "nobody assigned"}</p>
      {error && <p style={{ color: "red" }}>{error}</p>}

      <table border="1" cellPadding="4" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th>Visibility</th>
            <th>Title</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Assignee</th>
            <th>Due</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <Fragment key={t.id}>
              <tr>
                <td><VisibilityTag value={t.visibility} /></td>
                <td>{t.title}</td>
                <td>
                  <select value={t.status} onChange={(e) => changeStatus(t, e.target.value)}>
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td>{t.priority}</td>
                <td>{nameOf(t.assignee_id)}</td>
                <td>{t.due_date || "-"}</td>
                <td><button onClick={() => setOpen(open === t.id ? null : t.id)}>{open === t.id ? "Close" : "Open"}</button></td>
              </tr>
              {open === t.id && (
                <tr>
                  <td colSpan={7}>
                    <Comments taskId={t.id} staff />
                    <Files taskId={t.id} staff />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>

      <h3>New task</h3>
      <form onSubmit={createTask}>
        <input
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Title"
          required
        />{" "}
        <select value={form.visibility} onChange={(e) => setForm({ ...form, visibility: e.target.value })}>
          <option value="internal">internal</option>
          <option value="client">client-visible</option>
        </select>{" "}
        <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
          {["low", "medium", "high", "urgent"].map((p) => <option key={p}>{p}</option>)}
        </select>{" "}
        <select value={form.assignee_id} onChange={(e) => setForm({ ...form, assignee_id: e.target.value })}>
          <option value="">unassigned</option>
          {members.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}
        </select>{" "}
        <button type="submit">Create</button>
      </form>
    </div>
  );
}
