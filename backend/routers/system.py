"""系统级路由：健康检查、参数配置、文件夹预览扫描。"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import config
from backend.services.inference_runner import model_runner
from backend.services.scanner import scan_images
from shared.schemas import AppConfig, HealthInfo, ImageListResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthInfo, summary="健康检查与环境自检")
async def health() -> HealthInfo:
    torch_ok, version, cuda = model_runner.environment()
    status, message = model_runner.snapshot()
    return HealthInfo(
        backend=True,
        torch_available=torch_ok,
        torch_version=version,
        cuda_available=cuda,
        model_status=status,
        model_message=message,
    )


@router.get("/scan", response_model=ImageListResponse, summary="预览文件夹中的图片")
async def scan_folder(folder: str) -> ImageListResponse:
    try:
        files = scan_images(folder)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("扫描文件夹失败：%s", folder)
        raise HTTPException(status_code=500, detail=f"扫描失败：{exc}") from exc

    return ImageListResponse(
        folder=str(Path(folder)),
        total=len(files),
        files=[f.name for f in files],
    )


@router.get("/config", response_model=AppConfig, summary="读取当前参数")
async def get_config() -> AppConfig:
    return config.get()


@router.put("/config", response_model=AppConfig, summary="修改参数（对后续任务生效）")
async def update_config(patch: dict) -> AppConfig:
    allowed = {"batch_size", "max_side", "jpeg_quality"}
    cleaned = {k: v for k, v in (patch or {}).items() if k in allowed}
    if not cleaned:
        raise HTTPException(status_code=400, detail="没有可修改的参数")

    try:
        if "batch_size" in cleaned:
            value = int(cleaned["batch_size"])
            if not 1 <= value <= 64:
                raise ValueError
            cleaned["batch_size"] = value
        if "max_side" in cleaned:
            value = int(cleaned["max_side"])
            if value not in (0,) and not (256 <= value <= 8192):
                raise ValueError
            cleaned["max_side"] = value
        if "jpeg_quality" in cleaned:
            value = int(cleaned["jpeg_quality"])
            if not 50 <= value <= 100:
                raise ValueError
            cleaned["jpeg_quality"] = value
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="参数取值超出允许范围") from exc

    return config.update(cleaned)


@router.post("/models/reset", summary="重置模型加载状态（下次任务会重新加载）")
async def reset_model() -> dict:
    model_runner.reset()
    status, message = model_runner.snapshot()
    return {"model_status": status.value, "model_message": message}
