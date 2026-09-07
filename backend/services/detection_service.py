"""核心编排：把一个文件夹的检测任务拆解成分批推理，并持续维护进度。

设计要点：
    - 推理在**单工作线程**的线程池中串行执行，避免 GPU 并发导致显存溢出
    - 所有阻塞操作（扫描、拷文件、推理）都丢到线程里，不阻塞 asyncio 事件循环
    - 每批之间检查取消标志，用户点停止后能及时停下，已完成的结果仍然展示
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Sequence

from backend.config import RESULTS_DIR, TEMP_DIR, config
from backend.jobs.job_store import job_store
from backend.services.inference_runner import InferenceError, model_runner
from backend.services.scanner import scan_images, unique_result_name
from shared.schemas import JobInfo, JobStatus

logger = logging.getLogger(__name__)


def chunked(items: Sequence[Path], size: int) -> Iterable[list[Path]]:
    size = max(1, int(size))
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _prepare_batch(files: Sequence[Path], workdir: Path, max_side: int) -> list[str]:
    """把这一批图片拷到临时目录（按需缩放），返回临时文件绝对路径列表。

    为什么要拷贝：模型侧只需要读文件，给它一个干净、可控、短路径的输入更稳妥。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    prepared: list[str] = []

    for source in files:
        target = workdir / source.name
        if target.exists():  # 同名文件冲突时加前缀区分
            target = workdir / f"{source.parent.name}_{source.name}"

        if max_side and max_side > 0:
            resized = _resize_image(source, target, max_side)
            if resized:
                prepared.append(str(target))
                continue

        shutil.copy2(source, target)
        prepared.append(str(target))

    return prepared


def _resize_image(source: Path, target: Path, max_side: int) -> bool:
    """按长边缩放图片；环境里没有 PIL / cv2 时返回 False（调用方直接拷贝原图）。"""
    try:
        from PIL import Image  # type: ignore

        with Image.open(source) as img:
            img.load()
        with Image.open(source) as img:
            width, height = img.size
            scale = min(1.0, max_side / max(width, height))
            if scale < 1.0:
                img = img.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale)))
                )
            img.convert("RGB").save(target)
        return True
    except Exception:  # noqa: BLE001 - 没有 PIL 就尝试 cv2
        pass

    try:
        import cv2  # type: ignore

        img = cv2.imread(str(source))
        if img is None:
            return False
        height, width = img.shape[:2]
        scale = min(1.0, max_side / max(width, height))
        if scale < 1.0:
            img = cv2.resize(img, (int(width * scale), int(height * scale)))
        return bool(cv2.imwrite(str(target), img))
    except Exception:  # noqa: BLE001
        return False


class DetectionService:
    def __init__(self) -> None:
        # 单工作线程：GPU 显存有限，串行推理最稳
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="infer")

    # ------------------------------------------------------------------ 对外 API
    async def create_job(self, folder: str, prompt: str) -> JobInfo:
        job = job_store.create(folder, prompt)
        asyncio.get_event_loop().create_task(self._run(job.job_id, folder, prompt))
        return job

    async def cancel_job(self, job_id: str) -> bool:
        if not job_store.exists(job_id):
            return False
        job_store.request_cancel(job_id)
        logger.info("任务 %s 已请求取消", job_id)
        return True

    # ------------------------------------------------------------------ 主流程
    async def _run(self, job_id: str, folder: str, prompt: str) -> None:
        loop = asyncio.get_event_loop()
        started = time.time()
        results_dir = RESULTS_DIR / job_id
        temp_root = TEMP_DIR / job_id

        try:
            results_dir.mkdir(parents=True, exist_ok=True)

            files = await loop.run_in_executor(None, scan_images, folder)
            total = len(files)
            job_store.update(job_id, status=JobStatus.RUNNING, total=total)

            if total == 0:
                job_store.update(
                    job_id,
                    status=JobStatus.FAILED,
                    message="该文件夹中没有找到受支持的图片（jpg/jpeg/png/bmp/tif/webp）",
                )
                return

            app_config = config.get()
            batch_size = app_config.batch_size
            max_side = app_config.max_side
            quality = app_config.jpeg_quality

            used_names: set[str] = set()
            batches = list(chunked(files, batch_size))
            logger.info(
                "任务 %s 开始：共 %d 张，分 %d 批，批大小 %d",
                job_id, total, len(batches), batch_size,
            )

            for index, batch in enumerate(batches, start=1):
                if job_store.is_canceled(job_id):
                    logger.info("任务 %s 在处理第 %d 批前被取消", job_id, index)
                    break

                job_store.update(
                    job_id,
                    current_file=batch[0].name,
                    message=f"正在检测第 {index}/{len(batches)} 批",
                )

                workdir = temp_root / f"batch_{index}"
                paths = await loop.run_in_executor(
                    None, _prepare_batch, batch, workdir, max_side
                )

                try:
                    outputs = await loop.run_in_executor(
                        self._executor, model_runner.run_batch, paths, prompt, quality
                    )
                except InferenceError as exc:
                    # 模型级错误（未接入/权重缺失/显存不足等）：无法继续，整个任务直接失败
                    message = _error_message(exc)
                    logger.exception("任务 %s 模型级失败：%s", job_id, exc)
                    job_store.update(
                        job_id,
                        status=JobStatus.FAILED,
                        message=message,
                        elapsed_ms=int((time.time() - started) * 1000),
                    )
                    return
                except BaseException as exc:  # noqa: BLE001
                    # 单批内部错误（如某张图损坏）：记录该批所有文件，继续下一批
                    message = _error_message(exc)
                    logger.exception("任务 %s 第 %d 批推理失败：%s", job_id, index, exc)
                    for source in batch:
                        job_store.add_failure(job_id, source.name, message)
                    snapshot = job_store.get(job_id)
                    job_store.update(
                        job_id,
                        processed=snapshot.succeeded + snapshot.failed,
                        elapsed_ms=int((time.time() - started) * 1000),
                    )
                    continue

                for source, payload in zip(batch, outputs):
                    name = unique_result_name(used_names, source)
                    (results_dir / name).write_bytes(payload)
                    job_store.add_result(job_id, name)

                # 模型返回数量不足时，剩余图片登记为失败，保证进度准确
                if len(outputs) < len(batch):
                    for source in batch[len(outputs):]:
                        job_store.add_failure(
                            job_id, source.name, "模型没有返回该图片的结果"
                        )

                info = job_store.get(job_id)
                job_store.update(
                    job_id,
                    processed=info.succeeded + info.failed,
                    elapsed_ms=int((time.time() - started) * 1000),
                )

            self._finish(job_id, started)

        except asyncio.CancelledError:  # 应用关闭时的常规信号
            raise
        except BaseException as exc:  # noqa: BLE001 - 任务级失败
            logger.exception("任务 %s 执行失败", job_id)
            message = _error_message(exc)
            job_store.update(
                job_id,
                status=JobStatus.FAILED,
                message=message,
                elapsed_ms=int((time.time() - started) * 1000),
            )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
            job_store.clear_cancel(job_id)

    def _finish(self, job_id: str, started: float) -> None:
        info = job_store.get(job_id)
        if info is None:
            return

        elapsed_ms = int((time.time() - started) * 1000)

        if job_store.is_canceled(job_id):
            job_store.update(
                job_id,
                status=JobStatus.CANCELED,
                message=f"已取消，已完成 {info.succeeded} 张",
                processed=info.succeeded + info.failed,
                elapsed_ms=elapsed_ms,
                current_file=None,
            )
            return

        job_store.update(
            job_id,
            status=JobStatus.DONE,
            processed=info.succeeded + info.failed,
            elapsed_ms=elapsed_ms,
            current_file=None,
            message=f"完成：成功 {info.succeeded} 张，失败 {info.failed} 张",
        )
        logger.info(
            "任务 %s 结束：成功 %d 失败 %d 耗时 %.1fs",
            job_id, info.succeeded, info.failed, elapsed_ms / 1000,
        )


def _error_message(exc: BaseException) -> str:
    from backend.services.inference_runner import translate_exception

    message, hint = translate_exception(exc)
    return f"{message}；{hint}" if hint else message


detection_service = DetectionService()
