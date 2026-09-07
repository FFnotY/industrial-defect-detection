"""模型推理适配层 —— 对接 OEGT-CP 缺陷定位模型。

OEGT-CP 官方仓库：https://github.com/lyylovemwj/OEGT-CP
本文件是软件与 OEGT-CP 之间的唯一桥接点。

软件只调用本文件暴露的两个函数（接口契约固定不变）：
    load_model()                                   —— 加载模型，只调用一次
    run_inference(image_paths, prompt) -> list[bytes]
                                                   —— 输入图片路径列表 + 缺陷文本，输出已画框的 JPEG

================================================================================
给模型负责同学的话
================================================================================
OEGT-CP 提供两种推理方式，本文件都已接好，改顶部配置即可切换：

方式 A（默认，开箱即用）—— IIDGPredictor，14 个检测头 + 启发式融合：
    - 不需要训练好的 .pt 权重，装上依赖就能跑
    - 如果下载了 CLIP / DINOv2 / ResNet 共享权重，会自动用深度学习特征；
      没下载则自动回退到传统图像处理算法（opencv），仍能输出缺陷框

方式 B（论文原始方法）—— Predictor（候选集合 Transformer ranker）：
    - 需要训练好的 .pt 权重文件，精度更高，是论文的正式模型
    - 把 USE_RANKER 改为 True，并填 RANKER_CHECKPOINT 路径即可
================================================================================
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# 配置区 —— 在这里填写模型信息
# ============================================================================

# 方式 A：开源自复现推理（默认）
ASSETS_DIR = r"assets/models"   # CLIP/DINOv2/ResNet 共享权重的目录（相对项目根或绝对路径均可）
HEAD = "all"                    # 可选 14 个头之一，或 "all" 融合所有头

# 方式 B：论文原始 ranker（需训练好的权重），需要时把下面两行改掉
USE_RANKER = False
RANKER_CHECKPOINT = r""         # 例如 r"D:/models/oegt_cp.pt"

# 推理设备："auto" 自动选择（有 GPU 用 GPU）/"cuda"/"cpu"
DEVICE = "auto"

# ============================================================================
# 以下为实现区（一般无需修改）
# ============================================================================

_predictor = None


def resolve_device() -> str:
    import torch  # 本文件允许 import torch

    if DEVICE == "cuda":
        return "cuda"
    if DEVICE == "cpu":
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model():
    """加载模型并返回推理器。幂等：重复调用复用已加载的实例。"""
    global _predictor
    if _predictor is not None:
        return _predictor

    try:
        import oegt_cp  # noqa: F401  # 确保依赖已安装
    except ImportError as exc:
        raise ModuleNotFoundError(
            "缺少 OEGT-CP 依赖。请先安装：pip install -e <OEGT-CP 仓库路径>"
        ) from exc

    device = resolve_device()

    if USE_RANKER:
        from oegt_cp.inference import Predictor

        checkpoint = Path(RANKER_CHECKPOINT)
        if not RANKER_CHECKPOINT or not checkpoint.exists():
            raise FileNotFoundError(
                f"找不到 ranker 权重：{RANKER_CHECKPOINT}，请检查 model/inference.py 的 RANKER_CHECKPOINT"
            )
        _predictor = Predictor(checkpoint=checkpoint, device=device)
        logger.info("OEGT-CP ranker 已加载（%s）", device)
    else:
        from oegt_cp.iidg import IIDGPredictor

        _predictor = IIDGPredictor(assets_dir=ASSETS_DIR, device=device)
        logger.info("OEGT-CP IIDG 推理器已就绪（head=%s, %s）", HEAD, device)

    return _predictor


def _load_rgb(path: str):
    """读取图片为 RGB numpy 数组，兼容中文/非 ASCII 路径。"""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"无法读取图片：{path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _predict(predictor, image_rgb, prompt: str) -> dict:
    """调用推理器，返回包含 box/confidence 的结果字典。"""
    if USE_RANKER:
        # 论文 ranker 接口：predict(target, references, category, defect_token)
        return predictor.predict(
            image_rgb, references_rgb=[], category="unknown", defect_token=prompt or "unknown"
        )
    # 开源自复现接口：predict(target, query, references, head)
    return predictor.predict(
        image_rgb, query=prompt or "", references_rgb=[], head=HEAD
    )


def _render(image_rgb, result: dict):
    """把缺陷框画到原图上，返回 RGB 标注图。"""
    import numpy as np

    if USE_RANKER:
        from oegt_cp.inference import draw_prediction

        return draw_prediction(image_rgb, result)

    from oegt_cp.iidg import render_box

    box = result.get("box")
    if box is None or not np.isfinite(box).all():
        return image_rgb.copy()
    return render_box(image_rgb, result)


def run_inference(image_paths: list[str], prompt: str, jpeg_quality: int = 90) -> list[bytes]:
    """对一批图片执行缺陷检测，返回已画好缺陷框的 JPEG 字节列表。

    参数：
        image_paths  —— 本机图片绝对路径列表（后端的临时副本）
        prompt       —— 缺陷类型文本（中英文均可），作为 query 参与定位
        jpeg_quality —— 结果图 JPEG 编码质量（来自软件参数设置）
    返回：
        与输入顺序一致的结果图（JPEG 字节）
    """
    import cv2

    if not image_paths:
        return []

    predictor = load_model()
    outputs: list[bytes] = []

    for path in image_paths:
        image_rgb = _load_rgb(path)
        result = _predict(predictor, image_rgb, prompt)
        annotated = _render(image_rgb, result)
        ok, buffer = cv2.imencode(
            ".jpg",
            cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR),
            [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
        )
        if not ok:
            raise ValueError(f"结果图编码失败：{path}")
        outputs.append(buffer.tobytes())

    return outputs
