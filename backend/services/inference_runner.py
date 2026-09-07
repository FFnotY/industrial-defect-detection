"""模型调用封装。

职责：
    1. 探测当前环境的 torch 是否可用（这是软件能否跑起来的前提）
    2. 懒加载 + 单例持有模型，并维护加载状态供界面显示
    3. 把模型侧抛出的各种异常翻译成中文提示
    4. 把模型返回的多样性结果（bytes / numpy / PIL）统一转成 JPEG 字节

本文件本身**不 import torch**，只在运行时动态探测；
torch 相关的真实调用全部通过 model 包完成。
"""

from __future__ import annotations

import logging
import threading
from importlib import import_module
from typing import Any, Optional

from shared.schemas import ModelStatus

logger = logging.getLogger(__name__)


class InferenceError(Exception):
    """已翻译成中文、可直接展示给用户的推理错误。"""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


def probe_torch() -> tuple[bool, Optional[str], bool]:
    """返回 (torch 是否可用, torch 版本, CUDA 是否可用)。"""
    try:
        torch = import_module("torch")
    except Exception as exc:
        logger.warning("import torch 失败：%s", exc)
        return False, None, False

    try:
        version = str(torch.__version__)
        cuda = bool(torch.cuda.is_available())
        return True, version, cuda
    except Exception as exc:
        logger.warning("读取 torch 信息失败：%s", exc)
        return True, None, False


def translate_exception(exc: BaseException) -> tuple[str, Optional[str]]:
    """把模型侧异常翻译成 (中文提示, 处理建议)。"""
    text = str(exc).strip()

    if isinstance(exc, NotImplementedError):
        return (
            "模型尚未接入",
            "请在 model/inference.py 的 load_model() 与 run_inference() 中填入你的模型代码",
        )

    if isinstance(exc, FileNotFoundError):
        detail = text or str(getattr(exc, "filename", ""))
        return (
            f"找不到模型文件：{detail}",
            "请核对 model/inference.py 中的 MODEL_WEIGHTS 路径是否正确",
        )

    if isinstance(exc, ModuleNotFoundError):
        return (
            f"缺少 Python 依赖：{getattr(exc, 'name', text)}",
            "请在当前环境中 pip install 对应依赖后重启软件",
        )

    low = text.lower()
    if "out of memory" in low or "cuda oom" in low:
        return (
            "显存不足（CUDA out of memory）",
            "请在设置中把「每批图片数」调小，或开启超大图缩放后再试",
        )
    if "no module named 'torch'" in low:
        return (
            "当前环境找不到 torch",
            "请在已安装 PyTorch 的环境中运行本软件（pip install -r requirements.txt 不会安装 torch）",
        )
    if "cannot identify image file" in low or "imread" in low:
        return (
            f"图片无法解码：{text}",
            "请确认该图片没有损坏，或先从待检测文件夹中移除",
        )

    return (f"模型推理失败：{text or exc.__class__.__name__}", None)


class ModelRunner:
    """模型加载状态机 + 批次调用入口。整个后端进程只有一个实例。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: ModelStatus = ModelStatus.NOT_LOADED
        self._message: str | None = None
        self._torch_checked = False
        self._torch_available = False
        self._torch_version: Optional[str] = None
        self._cuda_available = False

    # ------------------------------------------------------------ 环境探测
    def environment(self) -> tuple[bool, Optional[str], bool]:
        if not self._torch_checked:
            self._torch_available, self._torch_version, self._cuda_available = probe_torch()
            self._torch_checked = True
        return self._torch_available, self._torch_version, self._cuda_available

    # ------------------------------------------------------------ 状态查询
    @property
    def status(self) -> ModelStatus:
        return self._status

    @property
    def message(self) -> str | None:
        return self._message

    def snapshot(self) -> tuple[ModelStatus, str | None]:
        return self._status, self._message

    def reset(self) -> None:
        """丢弃当前状态，下一次任务会重新加载模型。"""
        with self._lock:
            self._status = ModelStatus.NOT_LOADED
            self._message = None

    # ------------------------------------------------------------ 加载模型
    def ensure_loaded(self) -> None:
        """确保模型已加载。线程安全，失败会抛出 InferenceError。"""
        torch_ok, _, _ = self.environment()
        if not torch_ok:
            raise InferenceError(
                "当前环境找不到 torch",
                "请在已安装 PyTorch 的环境中运行本软件，可运行 python -c \"import torch\" 验证",
            )

        with self._lock:
            if self._status is ModelStatus.READY:
                return
            if self._status is ModelStatus.LOADING:
                raise InferenceError("模型正在加载中，请稍候再试", None)

            if self._status is ModelStatus.ERROR and self._message:
                # 上一次失败过，本次任务再给一次机会（重新尝试加载）
                logger.info("上次模型加载失败，本次重新尝试：%s", self._message)

            self._status = ModelStatus.LOADING
            self._message = "正在加载模型权重"

        # 真正加载（不持有锁太久，但 LOADING 状态能挡住并发调用）
        try:
            from model import load_model  # 唯一接触 torch 的入口

            load_model()
        except BaseException as exc:  # noqa: BLE001 - 需要把一切异常转成中文提示
            message, hint = translate_exception(exc)
            full = f"{message}；{hint}" if hint else message
            logger.exception("模型加载失败：%s", exc)
            with self._lock:
                self._status = ModelStatus.ERROR
                self._message = full
            raise InferenceError(message, hint) from exc

        with self._lock:
            self._status = ModelStatus.READY
            self._message = None
        logger.info("模型加载完成")

    # ------------------------------------------------------------ 执行推理
    def run_batch(self, image_paths: list[str], prompt: str, jpeg_quality: int = 90) -> list[bytes]:
        """对一批图片执行推理，返回结果图字节列表（顺序与输入一致）。"""
        self.ensure_loaded()

        from model import run_inference

        try:
            raw = run_inference(image_paths, prompt, jpeg_quality)
        except InferenceError:
            raise
        except (NotImplementedError, ModuleNotFoundError, FileNotFoundError) as exc:
            # 这些属于"模型还没接好"，是模型级问题，不是单张图片的问题
            message, hint = translate_exception(exc)
            raise InferenceError(message, hint) from exc

        if raw is None:
            raise InferenceError("模型没有返回任何结果", "请检查 run_inference() 的返回值")

        if len(raw) != len(image_paths):
            logger.warning(
                "模型返回数量(%d)与输入数量(%d)不一致，按较短的一方对齐",
                len(raw), len(image_paths),
            )

        outputs: list[bytes] = []
        for item in raw:
            outputs.append(serialize_image(item, jpeg_quality))
        return outputs


def serialize_image(item: Any, jpeg_quality: int = 90) -> bytes:
    """把模型返回的单个结果统一转成 JPEG 字节。

    支持：bytes / numpy 数组 / PIL 图像对象。
    """
    if isinstance(item, (bytes, bytearray)):
        return bytes(item)

    # numpy 数组：优先 PIL，其次 cv2
    if hasattr(item, "shape") and hasattr(item, "dtype"):
        try:
            from PIL import Image  # type: ignore

            if str(getattr(item, "dtype", "")).startswith("float"):
                import numpy as np  # type: ignore

                item = (np.clip(item, 0, 1) * 255).astype("uint8")
            # cv2 读出来是 BGR，PIL 需要 RGB；这里判断通道末位是否可能是 BGR 时不做强转，
            # 由模型侧保证返回顺序与训练可视化一致。
            image = Image.fromarray(item)
            return _pil_to_jpeg(image, jpeg_quality)
        except Exception:  # noqa: BLE001 - 回退到 cv2
            pass

        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            array = np.asarray(item)
            if array.dtype != np.uint8:
                array = np.clip(array, 0, 255).astype("uint8")
            ok, buffer = cv2.imencode(
                ".jpg", array, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]
            )
            if not ok:
                raise ValueError("cv2 编码失败")
            return buffer.tobytes()
        except Exception as exc:  # noqa: BLE001
            raise InferenceError(f"无法把模型输出转成图片：{exc}") from exc

    # PIL 图像
    if hasattr(item, "save"):
        try:
            return _pil_to_jpeg(item, jpeg_quality)
        except Exception as exc:  # noqa: BLE001
            raise InferenceError(f"无法保存 PIL 图像：{exc}") from exc

    raise InferenceError(
        f"不支持的模型输出类型：{type(item).__name__}",
        "请让 run_inference() 返回 bytes、numpy 数组或 PIL 图像",
    )


def _pil_to_jpeg(image: Any, jpeg_quality: int) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.save(buffer, format="JPEG", quality=int(jpeg_quality))
    return buffer.getvalue()


model_runner = ModelRunner()
