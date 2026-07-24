"""FastAPI 应用入口（DESIGN.md 第 8 节）。

启动时：建表 + 确保 admin 用户存在 + 启动模拟交易调度器。
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, backtests, data, sims, strategies
from app.api import ws as ws_api
from app.core.config import BACKEND_DIR, settings
from app.core.db import SessionLocal, init_db
from app.core.security import hash_password
from app.models import User
from app.scheduler.sim_scheduler import start_scheduler

# ---- 日志 ----
LOG_FILE = BACKEND_DIR / "server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="a"),
    ],
)
log = logging.getLogger("trading-quant")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    db = SessionLocal()
    if not db.query(User).filter(User.username == settings.admin_username).first():
        db.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
        db.commit()
        log.info("seed admin 用户完成")
    db.close()
    start_scheduler()
    log.info("服务启动，模拟调度器已就绪 | log: %s", LOG_FILE)
    yield
    log.info("服务关闭")


app = FastAPI(title="trading-quant", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 生产模式：托管前端静态文件 ----
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # 只处理前端路由，不拦截 API 请求
        if full_path.startswith("api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, 404)
        path = FRONTEND_DIST / full_path
        if path.is_file():
            return FileResponse(path)
        return FileResponse(FRONTEND_DIST / "index.html")
    log.info("前端托管已启用: %s", FRONTEND_DIST)


# ---- 请求日志中间件 ----
@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    dt = time.time() - t0
    log.info("%s %s → %d  %.0fms", request.method, request.url.path, response.status_code, dt * 1e3)
    return response
app.include_router(auth.router)
app.include_router(strategies.router)
app.include_router(backtests.router)
app.include_router(sims.router)
app.include_router(data.router)
app.include_router(ws_api.router)


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8100, reload=False)
