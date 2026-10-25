// Every request to the backend goes through api(). It attaches the access token and
// turns error responses into thrown Errors carrying the server's message.
//
// The session lives in sessionStorage, which is per browser TAB. So you can be Priya
// in one tab and Maya in another, side by side, which is handy for the demo.

export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const KEY = "agencydesk.session";

export function getSession() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY)) || {};
  } catch {
    return {};
  }
}

export function setSession(patch) {
  sessionStorage.setItem(KEY, JSON.stringify({ ...getSession(), ...patch }));
}

export function clearSession() {
  sessionStorage.removeItem(KEY);
}

function messageFrom(data, fallback) {
  const detail = data && data.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors (422) come as a list.
  return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
}

export async function api(path, { method = "GET", body, token } = {}) {
  const headers = {};
  const bearer = token ?? getSession().accessToken;
  if (bearer) headers.Authorization = `Bearer ${bearer}`;

  let payload;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(API_URL + path, { method, headers, body: payload });
  const data = await res.json().catch(() => null);

  if (res.status === 401 && !path.startsWith("/auth/")) {
    // Token expired or membership removed: back to the login screen.
    clearSession();
    window.location.assign("/login");
  }
  if (!res.ok) {
    const err = new Error(messageFrom(data, res.statusText));
    err.status = res.status;
    throw err;
  }
  return data;
}

// Downloads need the Authorization header too, so they can't be plain links.
export async function downloadFile(attachment) {
  const res = await fetch(`${API_URL}/attachments/${attachment.id}/download`, {
    headers: { Authorization: `Bearer ${getSession().accessToken}` },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = attachment.filename;
  link.click();
  URL.revokeObjectURL(url);
}
