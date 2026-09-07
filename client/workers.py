"""后台线程：所有网络与 IO 都在这里执行，主线程只负责刷新界面。

Qt 规则提醒：任何 QWidget 都不能在子线程里操作，
因此这些线程一律通过 Signal 把数据交回主线程。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot

from client import api_client
from client.config import POLL_INTERVAL_MS

TERMINAL_STATES = {"done", "failed", "canceled"}


class HealthWorker(QThread):
    """一次性健康检查。"""

    finished_with = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:  # pragma: no cover - 线程体
        try:
            self.finished_with.emit(api_client.health())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class BackendWaiter(QThread):
    """等待后端启动完成（首次启动时后端需要几秒钟加载环境）。"""

    ready = Signal(dict)
    timeout = Signal(str)

    def __init__(self, max_seconds: int = 30) -> None:
        super().__init__()
        self.max_seconds = max_seconds

    def run(self) -> None:  # pragma: no cover - 线程体
        deadline = time.time() + self.max_seconds
        last_error = "未知错误"
        while time.time() < deadline:
            try:
                self.ready.emit(api_client.health())
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                time.sleep(0.5)
        self.timeout.emit(f"后端服务启动超时：{last_error}")


class JobPoller(QThread):
    """按固定间隔轮询任务进度，直到任务进入终态。"""

    progress = Signal(dict)
    failed = Signal(str)

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run(self) -> None:  # pragma: no cover - 线程体
        interval = max(0.3, POLL_INTERVAL_MS / 1000)
        while not self._stopped:
            try:
                info = api_client.get_job(self.job_id)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))
                return

            self.progress.emit(info)

            if info.get("status") in TERMINAL_STATES:
                return
            time.sleep(interval)


class JobStarter(QThread):
    """创建检测任务（后台执行，避免后端未就绪时卡住界面）。"""

    started = Signal(dict)
    failed = Signal(str)

    def __init__(self, folder: str, prompt: str) -> None:
        super().__init__()
        self.folder = folder
        self.prompt = prompt

    def run(self) -> None:  # pragma: no cover - 线程体
        try:
            self.started.emit(api_client.create_job(self.folder, self.prompt))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ScanWorker(QThread):
    """扫描文件夹里的图片数量。"""

    finished_with = Signal(dict)
    failed = Signal(str)

    def __init__(self, folder: str) -> None:
        super().__init__()
        self.folder = folder

    def run(self) -> None:  # pragma: no cover - 线程体
        try:
            self.finished_with.emit(api_client.scan_folder(self.folder))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ConfigWorker(QThread):
    """读取 / 保存参数。"""

    loaded = Signal(dict)
    saved = Signal(dict)
    failed = Signal(str)

    def __init__(self, patch: dict | None = None) -> None:
        super().__init__()
        self.patch = patch

    def run(self) -> None:  # pragma: no cover - 线程体
        try:
            if self.patch is None:
                self.loaded.emit(api_client.get_config())
            else:
                self.saved.emit(api_client.update_config(self.patch))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# 缩略图异步加载（线程池，避免大文件夹一次性开太多线程）
# ---------------------------------------------------------------------------


class ImageSignals(QObject):
    loaded = Signal(str, bytes)
    failed = Signal(str, str)


class ImageLoader(QRunnable):
    def __init__(self, job_id: str, name: str) -> None:
        super().__init__()
        self.job_id = job_id
        self.name = name
        self.signals = ImageSignals()

    @Slot()
    def run(self) -> None:  # pragma: no cover - 线程体
        try:
            data = api_client.fetch_image(self.job_id, self.name)
            self.signals.loaded.emit(self.name, data)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self.name, str(exc))
