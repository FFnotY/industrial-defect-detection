"""配置管理：读写项目根目录的 config.json。

配置项只涉及性能与输出质量，与具体模型无关，因此换模型不需要动配置。
首次运行时若不存在 config.json，会自动从 config.example.json 复制一份。
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path

from shared.schemas import AppConfig

logger = logging.getLogger(__name__)

# 项目根目录（backend 的上一级）
ROOT_DIR = Path(__file__).resolve().parents[1]

CONFIG_PATH = ROOT_DIR / "config.json"
CONFIG_EXAMPLE_PATH = ROOT_DIR / "config.example.json"

RESULTS_DIR = ROOT_DIR / "backend" / "storage" / "results"
TEMP_DIR = ROOT_DIR / "backend" / "storage" / "temp"
LOGS_DIR = ROOT_DIR / "logs"


class ConfigManager:
    """线程安全的配置读写器。保存后立即对后续任务生效。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config = self._load_from_disk()

    # ------------------------------------------------------------------ 读取
    def get(self) -> AppConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def as_dict(self) -> dict:
        return self.get().model_dump()

    # ------------------------------------------------------------------ 写入
    def update(self, patch: dict) -> AppConfig:
        with self._lock:
            data = self._config.model_dump()
            for key, value in patch.items():
                if key in data and value is not None:
                    data[key] = value
            self._config = AppConfig(**data)
            snapshot = self._config.model_copy(deep=True)

        self._save_to_disk(snapshot)
        logger.info("配置已更新：%s", patch)
        return snapshot

    # ------------------------------------------------------------------ 持久化
    def _load_from_disk(self) -> AppConfig:
        if not CONFIG_PATH.exists():
            if CONFIG_EXAMPLE_PATH.exists():
                shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
                logger.info("已根据 config.example.json 生成 config.json")
            else:
                return AppConfig()

        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return AppConfig(**raw)
        except Exception as exc:  # 配置文件损坏时退回默认值，不影响启动
            logger.warning("读取 config.json 失败，使用默认配置：%s", exc)
            return AppConfig()

    def _save_to_disk(self, config: AppConfig) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


config = ConfigManager()


def ensure_directories() -> None:
    """确保运行时目录存在。"""
    for directory in (RESULTS_DIR, TEMP_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
