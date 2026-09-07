"""文件夹扫描：递归找出所有受支持的图片并按自然顺序排序。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from shared.schemas import SUPPORTED_IMAGE_EXTS

logger = logging.getLogger(__name__)


def _natural_key(text: str):
    """让 img2 排在 img10 前面，而不是按字典序排成 img10, img2。"""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def validate_folder(folder: str) -> Path:
    """校验文件夹存在且确实是目录。"""
    path = Path(folder)
    if not path.exists():
        raise FileNotFoundError(f"文件夹不存在：{folder}")
    if not path.is_dir():
        raise NotADirectoryError(f"这不是一个文件夹：{folder}")
    return path


def scan_images(folder: str) -> list[Path]:
    """递归扫描文件夹下所有受支持的图片，返回排序后的路径列表。"""
    root = validate_folder(folder)

    files = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS
    ]
    files.sort(key=lambda p: _natural_key(str(p.relative_to(root))))
    logger.info("扫描 %s 得到 %d 张图片", folder, len(files))
    return files


def scan_image_names(folder: str) -> list[str]:
    return [str(p) for p in scan_images(folder)]


def unique_result_name(used: set[str], source: Path) -> str:
    """生成不重复的结果文件名（同名文件自动加序号）。"""
    stem = source.stem
    name = f"{stem}.jpg"
    index = 1
    while name in used:
        name = f"{stem}_{index}.jpg"
        index += 1
    used.add(name)
    return name
