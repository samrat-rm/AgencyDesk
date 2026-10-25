import { Fragment, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, getSession } from "../api.js";
import { Comments, DashboardLine, Files } from "../shared.jsx";

// Screen 4: the client's view of the same project. Internal tasks, comments and
// files aren't hidden by this page: the backend never sends them. There is no
// create or status control because clients can only read, comment and review files.
export default function ClientPortal() {
  const { projectId } = useParams();
  const { membership } = getSession();
  const [project, setProject] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api(`/projects/${projectId}`), api(`/tasks?project_id=${projectId}`)])
      .then(([p, t]) => {
        setProject(p);
        setTasks(t);
      })
      .catch((err) => setError(err.message));
  }, [projectId]);

  if (error) return <p style={{ color: "red" }}>{error}</p>;
  if (!project) return <p>Loading...</p>;

  return (
    <div>
      <h2>{project.name} (client portal)</h2>
      <p>
        Shared with you by {membership.agency_name}.
      </p>
      <DashboardLine projectId={projectId} />

      <table border="1" cellPadding="4" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th>Title</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Due</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <Fragment key={t.id}>
              <tr>
                <td>{t.title}</td>
                <td>{t.status}</td>
                <td>{t.priority}</td>
                <td>{t.due_date || "-"}</td>
                <td><button onClick={() => setOpen(open === t.id ? null : t.id)}>{open === t.id ? "Close" : "Open"}</button></td>
              </tr>
              {open === t.id && (
                <tr>
                  <td colSpan={5}>
                    <Comments taskId={t.id} staff={false} />
                    <Files taskId={t.id} staff={false} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
