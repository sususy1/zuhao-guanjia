import os, logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .config import settings
from .database import init_db, SessionLocal
from .auth import ensure_admin_user
from .api import auth, accounts, orders, stats, platforms, browser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(orders.router)
app.include_router(stats.router)
app.include_router(platforms.router)
app.include_router(browser.router)


@app.on_event("startup")
def startup_event():
    init_db()
    db = SessionLocal()
    try:
        ensure_admin_user(db)
    finally:
        db.close()
    if settings.SCHEDULER_ENABLED:
        from .scheduler import start_scheduler
        start_scheduler()
    logger.info(f"{settings.APP_NAME} 启动成功")


@app.on_event("shutdown")
def shutdown_event():
    from .scheduler import stop_scheduler
    stop_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


# 挂载前端静态文件
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend", "dist")
frontend_dir = os.path.normpath(frontend_dir)

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def read_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/{full_path:path}")
    def read_root(full_path: str):
        file_path = os.path.join(frontend_dir, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dir, "index.html"))
