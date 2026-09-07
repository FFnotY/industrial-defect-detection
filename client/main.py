"""桌面软件入口。

启动流程：
    1. 检查本机后端是否已在运行
    2. 没有则以子进程方式拉起后端（python -m backend.server）
    3. 等后端健康检查通过（显示启动提示窗口）
    4. 打开主界面；退出时把我们自己拉起的后端一起关掉
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client import api_client  # noqa: E402
from client.config import RESOURCES_DIR, THEME_PATH  # noqa: E402
from client.ui.main_window import MainWindow  # noqa: E402
from client.workers import BackendWaiter  # noqa: E402


def load_theme(app: QApplication) -> None:
    if THEME_PATH.exists():
        app.setStyleSheet(THEME_PATH.read_text(encoding="utf-8"))
    app.setStyle("Fusion")


def ping_backend() -> bool:
    """快速判断后端是否已在运行。"""
    try:
        api_client.health()
        return True
    except Exception:  # noqa: BLE001
        return False


class SplashWindow(QWidget):
    """启动等待窗口，避免用户以为软件没反应。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("正在启动")
        self.setFixedSize(360, 150)
        self.setWindowFlag(Qt.FramelessWindowHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        title = QLabel("工业缺陷检测系统")
        title.setObjectName("title")

        self.status = QLabel("正在启动本机后端服务…")
        self.status.setObjectName("statusText")

        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(6)
        bar.setTextVisible(False)

        layout.addWidget(title)
        layout.addWidget(self.status)
        layout.addWidget(bar)
        layout.addStretch(1)


def main() -> int:
    app = QApplication(sys.argv)
    load_theme(app)

    icon_path = RESOURCES_DIR / "app.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    backend_process: subprocess.Popen | None = None

    if not ping_backend():
        backend_process = subprocess.Popen(
            [sys.executable, "-m", "backend.server"],
            cwd=str(ROOT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        splash = SplashWindow()
        splash.show()
        app.processEvents()

        loop = QEventLoop()
        waiter = BackendWaiter(max_seconds=45)
        waiter.ready.connect(loop.quit)
        waiter.timeout.connect(loop.quit)
        waiter.start()
        loop.exec()
        waiter.wait(5000)  # 等线程真正退出后再释放引用，避免进程被 Qt 中止
        splash.close()

        if not ping_backend():
            QMessageBox.critical(
                None,
                "启动失败",
                "无法连接本机后端服务。\n\n"
                "请检查：\n"
                "1. 当前环境是否已安装依赖（pip install -r requirements.txt）\n"
                "2. 端口 8765 是否被其他程序占用\n"
                "3. 控制台是否有报错信息",
            )
            if backend_process:
                backend_process.terminate()
            return 1

    window = MainWindow()
    window.show()

    if backend_process is not None:
        app.aboutToQuit.connect(_make_cleanup(backend_process))

    return app.exec()


def _make_cleanup(process: subprocess.Popen):
    def _cleanup() -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:  # noqa: BLE001
                process.kill()

    return _cleanup


if __name__ == "__main__":
    raise SystemExit(main())
