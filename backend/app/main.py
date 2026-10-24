from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, comments, projects, tasks

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


@app.get("/health")
def health():
    return {"ok": True}
