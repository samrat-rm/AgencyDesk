from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import attachments, auth, comments, dashboard, invites, projects, tasks, time_entries

app = FastAPI(title="AgencyDesk")

# The React dev server runs on a different port, so the browser needs CORS permission.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(comments.router)
app.include_router(invites.router)
app.include_router(time_entries.router)
app.include_router(attachments.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"ok": True}
