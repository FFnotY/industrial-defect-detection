"""主窗口：把工具栏、控制面板、图片墙、状态栏组装起来并串联业务流程。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from client.ui.control_panel import ControlPanel
from client.ui.image_gallery import ImageGallery
from client.ui.image_viewer import ImageViewer
from client.ui.settings_dialog import SettingsDialog
from client.workers import (
    ConfigWorker,
    HealthWorker,
    JobPoller,
    JobStarter,
    ScanWorker,
)

# 语义色（与 theme.qss 保持一致）
ERROR_COLOR = "#EF4444"
MUTED_COLOR = "#6B7280"

STATE_STYLES = {
    "ready": ("ready", "#10B981"),
    "loading": ("loading", "#F59E0B"),
    "error": ("error", "#EF4444"),
    "off": ("off", "#C4CBD4"),
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("工业缺陷检测系统")
        self.resize(1280, 820)
        self.setMinimumSize(1024, 680)
        self.setAcceptDrops(True)

        # 重要：所有 QThread 必须保留引用。
        # 一旦 Python 把线程对象回收掉，而线程还在运行，程序会被 Qt 直接中止。
        self._health_worker: HealthWorker | None = None
        self._scan_worker: ScanWorker | None = None
        self._starter: JobStarter | None = None
        self._poller: JobPoller | None = None
        self._config_worker: ConfigWorker | None = None
        self._config: dict = {}
        self._current_job: str | None = None
        self._viewer_index = 0

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())
        root.addLayout(self._build_body(), 1)
        root.addWidget(self._build_status_bar())

        self._connect_signals()
        self._setup_shortcuts()

        # 健康检查：启动一次，之后每 10 秒刷新一次
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(10_000)
        self._health_timer.timeout.connect(self.refresh_health)
        self._health_timer.start()

        self.refresh_health()
        self.load_config()

    # ------------------------------------------------------------------ 界面构建
    def _build_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        toolbar.setFixedHeight(56)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(12)

        title = QLabel("工业缺陷检测系统")
        title.setObjectName("title")

        version = QLabel("v1.0")
        version.setObjectName("version")

        self.status_light = QLabel("")
        self.status_light.setObjectName("statusLight")
        self._set_light("off")

        self.status_label = QLabel("正在检查环境…")
        self.status_label.setObjectName("statusText")

        self.settings_btn = QPushButton("参数设置")
        self.settings_btn.setObjectName("ghost")
        self.settings_btn.clicked.connect(self.open_settings)

        layout.addWidget(title)
        layout.addWidget(version)
        layout.addStretch(1)
        layout.addWidget(self.status_light)
        layout.addWidget(self.status_label)
        layout.addSpacing(8)
        layout.addWidget(self.settings_btn)
        return toolbar

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.panel = ControlPanel()
        self.gallery = ImageGallery()

        body.addWidget(self.panel)
        body.addWidget(self.gallery, 1)
        return body

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(52)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(12)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.progress_label = QLabel("就绪")
        self.progress_label.setObjectName("statusText")

        self.elapsed_label = QLabel("")
        self.elapsed_label.setObjectName("hint")

        layout.addWidget(self.progress, 1)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.elapsed_label)
        return bar

    def _setup_shortcuts(self) -> None:
        self._start_shortcut = QShortcut("Ctrl+Enter", self)
        self._start_shortcut.activated.connect(self.panel.start_btn.click)

    # ------------------------------------------------------------------ 信号连接
    def _connect_signals(self) -> None:
        self.panel.folder_selected.connect(self.on_folder_selected)
        self.panel.start_requested.connect(self.on_start)
        self.panel.stop_requested.connect(self.on_stop)
        self.gallery.tile_clicked.connect(self.open_viewer)

    # ------------------------------------------------------------------ 线程工具
    def _cleanup_worker(self, worker) -> None:
        """安全停掉并清理一个后台 QThread，防止其在运行时被 GC 导致进程崩溃。

        所有 QThread 子线程都必须保留引用。一旦 Python 把它回收掉而线程还在跑，
        Qt 会直接中止整个进程（表现为"黑框一闪就闪退"）。
        """
        if worker is None:
            return
        # 1) 断开所有信号：避免 stop 后还有滞后信号进入主线程
        for sig_name in ("progress", "failed", "finished_with",
                         "saved", "loaded", "started"):
            sig = getattr(worker, sig_name, None)
            if sig is None:
                continue
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        # 2) 主动请求停止（poller 这类长循环线程有 stop()）
        if hasattr(worker, "stop"):
            try:
                worker.stop()
            except Exception:  # noqa: BLE001
                pass
        # 3) 等待线程真正退出再丢弃引用
        if worker.isRunning():
            worker.wait(2000)

    # ------------------------------------------------------------------ 健康检查
    def refresh_health(self) -> None:
        if self._health_worker and self._health_worker.isRunning():
            return

        worker = HealthWorker()
        worker.finished_with.connect(self.on_health)
        worker.failed.connect(lambda msg: self.on_health_failed(msg))
        self._health_worker = worker
        worker.start()

    def on_health(self, info: dict) -> None:
        torch_ok = bool(info.get("torch_available"))
        if not torch_ok:
            self._set_light("error")
            self.status_label.setText("环境异常：当前环境中找不到 torch")
            self.status_label.setStyleSheet(f"color:{ERROR_COLOR};")
            return

        model_status = info.get("model_status", "not_loaded")
        light_map = {
            "ready": "ready",
            "loading": "loading",
            "error": "error",
            "not_loaded": "off",
        }
        light = light_map.get(model_status, "off")
        self._set_light(light)

        device = "GPU" if info.get("cuda_available") else "CPU"
        texts = {
            "ready": f"模型就绪（{device}）",
            "loading": "正在加载模型…",
            "error": (info.get("model_message") or "模型加载失败")[:48],
            "not_loaded": f"torch {info.get('torch_version') or ''} · {device} · 模型未加载",
        }
        self.status_label.setText(texts.get(model_status, texts["not_loaded"]))
        self.status_label.setStyleSheet(
            f"color:{ERROR_COLOR};" if model_status == "error" else f"color:{MUTED_COLOR};"
        )

    def on_health_failed(self, message: str) -> None:
        self._set_light("error")
        self.status_label.setText(f"后端未连接：{message}")
        self.status_label.setStyleSheet(f"color:{ERROR_COLOR};")

    def _set_light(self, state: str) -> None:
        self.status_light.setProperty("state", STATE_STYLES[state][0])
        self.status_light.setStyleSheet(
            f"border-radius:5px; background:{STATE_STYLES[state][1]};"
            "min-width:10px;max-width:10px;min-height:10px;max-height:10px;"
        )

    # ------------------------------------------------------------------ 文件夹
    def on_folder_selected(self, folder: str) -> None:
        self.panel.set_image_count(0)
        self._cleanup_worker(self._scan_worker)
        worker = ScanWorker(folder)
        worker.finished_with.connect(self.on_scan_done)
        worker.failed.connect(lambda msg: self.panel.set_scan_error(msg))
        self._scan_worker = worker
        worker.start()

    def on_scan_done(self, payload: dict) -> None:
        self.panel.set_image_count(int(payload.get("total", 0)))

    # ------------------------------------------------------------------ 检测流程
    def on_start(self, folder: str, prompt: str) -> None:
        if not folder:
            self._set_status("请先选择图片文件夹", error=True)
            return

        self.gallery.clear()
        self.panel.reset_summary()
        self.panel.set_busy(True)
        self._set_status("正在创建任务…")
        self.setCursor(Qt.BusyCursor)

        # 启动新任务前先把旧的后台线程安全停掉，避免旧任务进度继续污染 UI
        self._cleanup_worker(self._poller)
        self._cleanup_worker(self._starter)
        self._current_job = None

        starter = JobStarter(folder, prompt)
        starter.started.connect(self.on_job_created)
        starter.failed.connect(self.on_job_failed)
        self._starter = starter
        starter.start()

    def on_job_created(self, payload: dict) -> None:
        job_id = payload.get("job_id")
        if not job_id:
            self.on_job_failed("后端未返回任务 ID")
            return

        self._cleanup_worker(self._starter)
        self._current_job = job_id
        self._set_status("任务已创建，等待模型响应…")

        poller = JobPoller(job_id)
        poller.progress.connect(self.on_progress)
        poller.failed.connect(self.on_job_failed)
        self._poller = poller
        poller.start()

    def on_progress(self, info: dict) -> None:
        # 防御性：忽略旧任务滞后到达的进度信号
        info_job_id = info.get("job_id")
        if info_job_id and self._current_job and info_job_id != self._current_job:
            return

        status = info.get("status")
        self.panel.update_summary(info)

        results = info.get("results") or []
        if results and self._current_job:
            self.gallery.set_results(self._current_job, results)

        total = int(info.get("total", 0))
        processed = int(info.get("processed", 0))
        percent = int(processed / total * 100) if total else 0
        self.progress.setValue(percent)

        elapsed_ms = int(info.get("elapsed_ms", 0))
        self.elapsed_label.setText(f"{elapsed_ms / 1000:.1f}s")

        if status == "running":
            current = info.get("current_file") or ""
            self._set_status(f"正在检测 {processed}/{total}　{current}")
            return

        # 终态
        self.panel.set_busy(False)
        self.unsetCursor()
        self.refresh_health()

        failures = info.get("failures") or []
        message = info.get("message") or ""
        is_error = status == "failed" or (failures and not results)

        if failures:
            first = failures[0]
            detail = f"{first.get('filename')}：{first.get('error')}"
            tail = f"（另有 {len(failures) - 1} 张同样失败）" if len(failures) > 1 else ""
            self._set_status(f"{message}　{detail}{tail}", error=is_error)
        else:
            self._set_status(message or "完成", error=is_error)

    def on_job_failed(self, message: str) -> None:
        self.panel.set_busy(False)
        self.unsetCursor()
        self._set_status(message, error=True)
        self.refresh_health()

    def on_stop(self) -> None:
        if not self._current_job:
            return
        try:
            from client import api_client

            api_client.cancel_job(self._current_job)
            self._set_status("正在停止…")
        except Exception as exc:  # noqa: BLE001
            self._set_status(str(exc), error=True)

    # ------------------------------------------------------------------ 状态显示
    def _set_status(self, text: str, error: bool = False) -> None:
        self.progress_label.setText(text)
        self.progress_label.setStyleSheet(
            f"color:{ERROR_COLOR};" if error else f"color:{MUTED_COLOR};"
        )

    # ------------------------------------------------------------------ 图片查看
    def open_viewer(self, index: int) -> None:
        names = self.gallery.names()
        if not (0 <= index < len(names)):
            return

        self._viewer_index = index
        viewer = ImageViewer()
        viewer.prev_requested.connect(lambda: self._step(-1, viewer))
        viewer.next_requested.connect(lambda: self._step(1, viewer))
        viewer.show_image(
            self.gallery.full_pixmap(index), names[index], f"{index + 1} / {len(names)}"
        )
        viewer.set_navigation(index > 0, index < len(names) - 1)
        viewer.exec()

    def _step(self, delta: int, viewer: ImageViewer) -> None:
        names = self.gallery.names()
        target = self._viewer_index + delta
        if not (0 <= target < len(names)):
            return
        self._viewer_index = target
        viewer.show_image(
            self.gallery.full_pixmap(target),
            names[target],
            f"{target + 1} / {len(names)}",
        )
        viewer.set_navigation(target > 0, target < len(names) - 1)

    # ------------------------------------------------------------------ 参数设置
    def load_config(self) -> None:
        self._cleanup_worker(self._config_worker)
        worker = ConfigWorker()
        worker.loaded.connect(self.on_config_loaded)
        worker.failed.connect(lambda msg: None)
        self._config_worker = worker
        worker.start()

    def on_config_loaded(self, config: dict) -> None:
        self._config = config

    def open_settings(self) -> None:
        dialog = SettingsDialog(self._config)
        if dialog.exec() != SettingsDialog.Accepted:
            return

        patch = dialog.patch()
        self._cleanup_worker(self._config_worker)
        worker = ConfigWorker(patch)
        worker.saved.connect(self.on_config_saved)
        worker.failed.connect(lambda msg: self._set_status(msg, error=True))
        self._config_worker = worker
        worker.start()

    def on_config_saved(self, config: dict) -> None:
        self._config = config
        self._set_status("参数已保存，下一次检测生效")

    # ------------------------------------------------------------------ 拖拽
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if not urls:
            return
        from pathlib import Path

        path = Path(urls[0].toLocalFile())
        if path.is_dir():
            self.panel.set_folder(str(path))
