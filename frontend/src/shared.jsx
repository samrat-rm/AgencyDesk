import { useEffect, useState } from "react";
import { api, downloadFile } from "./api.js";

// Pieces used by both the staff task board and the client portal. They call the
// same endpoints either way; what comes back depends on who is asking.

export function VisibilityTag({ value }) {
  return value === "internal" ? <b style={{ color: "darkred" }}>[INTERNAL]</b> : <span>[client-visible]</span>;
}

// Plain-text dashboard: GET /dashboard?project_id=...
export function DashboardLine({ projectId, refreshKey }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    api(`/dashboard?project_id=${projectId}`).then(setD).catch(() => setD(null));
  }, [projectId, refreshKey]);
  if (!d) return null;
  const s = d.tasks_by_status;
  return (
    <p>
      <b>Dashboard:</b> {d.total_tasks} tasks (to do {s.todo}, in progress {s.in_progress}, in review{" "}
      {s.in_review}, done {s.done}) | overdue {d.overdue_tasks} | hours logged {d.hours_logged}
    </p>
  );
}

export function Comments({ taskId, staff }) {
  const [comments, setComments] = useState([]);
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("internal");
  const [error, setError] = useState("");

  const load = () => api(`/tasks/${taskId}/comments`).then(setComments).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [taskId]);

  async function add(e) {
    e.preventDefault();
    setError("");
    try {
      // Clients don't get a choice: the server stores their comments as client-visible.
      await api(`/tasks/${taskId}/comments`, { method: "POST", body: staff ? { body, visibility } : { body } });
      setBody("");
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <b>Comments</b>
      {comments.length === 0 && <p>No comments.</p>}
      <ul>
        {comments.map((c) => (
          <li key={c.id}>
            {staff && <VisibilityTag value={c.visibility} />} <b>{c.author_name}</b>: {c.body}
          </li>
        ))}
      </ul>
      <form onSubmit={add}>
        <input value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a comment" required size={40} />{" "}
        {staff && (
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="internal">internal</option>
            <option value="client">client-visible</option>
          </select>
        )}{" "}
        <button type="submit">Add comment</button>
      </form>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}

export function Files({ taskId, staff }) {
  const [files, setFiles] = useState([]);
  const [error, setError] = useState("");

  const load = () => api(`/tasks/${taskId}/attachments`).then(setFiles).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [taskId]);

  async function review(file, decision) {
    setError("");
    try {
      await api(`/attachments/${file.id}/review`, { method: "POST", body: { decision } });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <b>Files</b>
      {files.length === 0 && <p>No files.</p>}
      <ul>
        {files.map((f) => (
          <li key={f.id}>
            {staff && <VisibilityTag value={f.visibility} />} {f.filename} ({f.approval_status}){" "}
            <button onClick={() => downloadFile(f).catch((e) => setError(e.message))}>Download</button>{" "}
            {!staff && (
              <>
                <button onClick={() => review(f, "approved")}>Approve</button>{" "}
                <button onClick={() => review(f, "changes_requested")}>Needs changes</button>
              </>
            )}
          </li>
        ))}
      </ul>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
