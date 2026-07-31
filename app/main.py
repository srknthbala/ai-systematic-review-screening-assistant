"""FastAPI application entrypoint. Serves the API and the static SPA."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import db

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="AI Systematic Review Screening Assistant", version="1.0.0")

# Initialize at import so the schema always exists, regardless of launch path.
db.init_db()


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# --- Routers (added incrementally as each module is built) ---
from .routers import projects as projects_router  # noqa: E402
app.include_router(projects_router.router)
from .routers import criteria as criteria_router  # noqa: E402
app.include_router(criteria_router.router)
from .routers import imports as imports_router  # noqa: E402
app.include_router(imports_router.router)
from .routers import settings as settings_router  # noqa: E402
app.include_router(settings_router.router)
from .routers import screen as screen_router  # noqa: E402
app.include_router(screen_router.router)
from .routers import results as results_router  # noqa: E402
app.include_router(results_router.router)


# --- Static SPA (mounted last so /api/* wins) ---
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _asset_version() -> str:
    """Fingerprint the CSS/JS so a `git pull` can't leave a stale copy cached.

    Browsers hold on to /static/* aggressively; without this, an updated
    stylesheet silently doesn't apply until a manual hard refresh.
    """
    stamp = 0.0
    for rel in ("css/styles.css", "js/app.js", "js/shortcuts.js"):
        f = STATIC_DIR / rel
        if f.exists():
            stamp = max(stamp, f.stat().st_mtime)
    return str(int(stamp))


@app.get("/")
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    v = _asset_version()
    for rel in ("css/styles.css", "js/app.js", "js/shortcuts.js"):
        html = html.replace(f"/static/{rel}", f"/static/{rel}?v={v}")
    # index.html itself must never be cached, or the new ?v= never arrives.
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
