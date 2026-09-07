"""任务相关路由：创建 / 查询 / 取消。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.jobs.job_store import job_store
from backend.services.detection_service import detection_service
from shared.schemas import CreateJobRequest, CreateJobResponse, JobInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CancelResponse(BaseModel):
    canceled: bool


@router.post("", response_model=CreateJobResponse, summary="创建检测任务")
async def create_job(payload: CreateJobRequest) -> CreateJobResponse:
    if not payload.folder:
        raise HTTPException(status_code=400, detail="文件夹路径不能为空")

    job = await detection_service.create_job(payload.folder, payload.prompt.strip())
    return CreateJobResponse(job_id=job.job_id)


@router.get("/{job_id}", response_model=JobInfo, summary="查询任务进度与结果")
async def get_job(job_id: str) -> JobInfo:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    return job


@router.post("/{job_id}/cancel", response_model=CancelResponse, summary="取消任务")
async def cancel_job(job_id: str) -> CancelResponse:
    ok = await detection_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    return CancelResponse(canceled=True)
