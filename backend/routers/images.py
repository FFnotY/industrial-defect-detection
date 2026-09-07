"""结果图读取路由：前端惰性加载展示时按需拉取。

安全：严格限制在本次任务的结果目录内，防止路径穿越读到系统其它文件。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import RESULTS_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["images"])


def _safe_path(job_id: str, name: str) -> Path:
    base = (RESULTS_DIR / job_id).resolve()
    target = (base / name).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="非法的结果文件路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="结果图不存在")
    return target


@router.get(
    "/{job_id}/images/{name:path}",
    summary="读取某张结果图（二进制）",
)
async def get_result_image(job_id: str, name: str) -> FileResponse:
    path = _safe_path(job_id, name)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )
