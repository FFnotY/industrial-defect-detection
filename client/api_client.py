"""对后端 HTTP 接口的薄封装。

约定：所有方法要么返回 dict / bytes，要么抛出带中文说明的 ApiError，
界面层不需要理解任何 HTTP 细节。
"""

from __future__ import annotations

from typing import Any

import requests

from client.config import BACKEND_URL, FETCH_IMAGE_TIMEOUT, HTTP_TIMEOUT


class ApiError(Exception):
    """可直接展示给用户的中文错误。"""


def _url(path: str) -> str:
    return f"{BACKEND_URL}{path}"


def _request(method: str, path: str, **kwargs) -> Any:
    try:
        response = requests.request(
            method, _url(path), timeout=kwargs.pop("timeout", HTTP_TIMEOUT), **kwargs
        )
    except requests.exceptions.ConnectionError as exc:
        raise ApiError(
            "无法连接本机后端服务",
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise ApiError("请求后端超时，请稍后重试") from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"请求失败：{exc}") from exc

    if response.status_code >= 400:
        raise ApiError(_read_error(response))

    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return response.json()
    return response.content


def _read_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail", payload)
        return str(detail)
    except Exception:  # noqa: BLE001
        return f"后端返回错误（HTTP {response.status_code}）"


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def health() -> dict:
    """健康检查：环境自检结果 + 模型加载状态。"""
    return _request("GET", "/api/health")


def scan_folder(folder: str) -> dict:
    """预览文件夹里的图片数量。"""
    return _request("GET", "/api/scan", params={"folder": folder})


def create_job(folder: str, prompt: str) -> dict:
    """创建一个检测任务。"""
    return _request("POST", "/api/jobs", json={"folder": folder, "prompt": prompt})


def get_job(job_id: str) -> dict:
    """查询任务进度。"""
    return _request("GET", f"/api/jobs/{job_id}")


def cancel_job(job_id: str) -> bool:
    """取消任务。"""
    payload = _request("POST", f"/api/jobs/{job_id}/cancel")
    return bool(payload.get("canceled"))


def get_config() -> dict:
    return _request("GET", "/api/config")


def update_config(patch: dict) -> dict:
    return _request("PUT", "/api/config", json=patch)


def fetch_image(job_id: str, name: str) -> bytes:
    """按需拉取某张结果图。"""
    return _request(
        "GET",
        f"/api/jobs/{job_id}/images/{name}",
        timeout=FETCH_IMAGE_TIMEOUT,
    )
