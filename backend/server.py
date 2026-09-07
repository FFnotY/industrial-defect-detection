"""本机后端服务入口。

运行：python -m backend.server
也可以：uvicorn backend.server:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 保证从任意目录启动时都能 import 到项目根下的 shared / model 包
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend.config import LOGS_DIR, config, ensure_directories  # noqa: E402
from backend.routers import images, jobs, system  # noqa: E402
from shared.schemas import API_PREFIX, DEFAULT_HOST  # noqa: E402

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """日志同时输出到控制台与 logs/backend.log。

    注意：任何地方都不要把图片二进制写进日志。
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(LOGS_DIR / "backend.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """服务启动时做一次环境自检（是否能用 torch / CUDA）。"""
    from backend.services.inference_runner import model_runner

    torch_ok, version, cuda = model_runner.environment()
    if torch_ok:
        logger.info(
            "环境自检通过：torch %s，CUDA %s", version, "可用" if cuda else "不可用"
        )
    else:
        logger.warning(
            "当前环境中找不到 torch，软件无法执行推理。"
            "请在已安装 PyTorch 的环境中运行本软件。"
        )
    yield


def create_app() -> FastAPI:
    ensure_directories()

    app = FastAPI(
        title="工业缺陷检测 - 本机后端",
        description="负责文件夹扫描、分批调用本地 PyTorch 模型、进度维护与结果落盘",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 桌面客户端通过 localhost 访问，放开同源限制便于调试
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(images.router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    async def _root() -> dict:
        return {"name": "工业缺陷检测后端", "docs": "/docs"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    setup_logging()
    app_config = config.get()
    logger.info("启动后端服务：http://%s:%s", DEFAULT_HOST, app_config.port)
    uvicorn.run(app, host=DEFAULT_HOST, port=app_config.port, log_level="warning")
