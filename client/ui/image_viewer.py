"""大图查看器：全屏查看模型输出的完整标注图。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
)


class ImageViewer(QDialog):
    prev_requested = Signal()
    next_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("查看检测结果")
        self.setModal(True)
        self.setStyleSheet("background:#F4F6F9;")
        self.resize(1200, 820)

        self._pixmap = QPixmap()
        self._zoom = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部信息
        header = QFrame()
        header.setStyleSheet("background:#FFFFFF; border-bottom:1px solid #E6EAF0;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)

        self.name_label = QLabel("")
        self.name_label.setObjectName("statusText")
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.count_label = QLabel("")
        self.count_label.setObjectName("statusText")

        header_layout.addWidget(self.name_label)
        header_layout.addWidget(self.count_label)
        root.addWidget(header)

        # 中央图像区
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # 左右切换按钮：用 Qt 标准图标，避免依赖字体是否支持某个 Unicode 字符
        style = self.style()
        self.prev_btn = QPushButton()
        self.prev_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.prev_btn.setIconSize(QSize(22, 22))
        self.prev_btn.setObjectName("ghost")
        self.prev_btn.setFixedWidth(56)
        self.prev_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.prev_btn.setStyleSheet("background:#FFFFFF; border:none;")
        self.prev_btn.clicked.connect(self.prev_requested.emit)

        self.next_btn = QPushButton()
        self.next_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.next_btn.setIconSize(QSize(22, 22))
        self.next_btn.setObjectName("ghost")
        self.next_btn.setFixedWidth(56)
        self.next_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.next_btn.setStyleSheet("background:#FFFFFF; border:none;")
        self.next_btn.clicked.connect(self.next_requested.emit)

        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        body.addWidget(self.prev_btn)
        body.addWidget(self.image_label, 1)
        body.addWidget(self.next_btn)
        root.addLayout(body, 1)

        # 底部工具条
        footer = QFrame()
        footer.setStyleSheet("background:#FFFFFF; border-top:1px solid #E6EAF0;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 12)
        footer_layout.setSpacing(10)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("statusText")

        zoom_out = QPushButton("缩小")
        zoom_out.setObjectName("ghost")
        zoom_out.clicked.connect(lambda: self._zoom_by(-0.2))

        zoom_in = QPushButton("放大")
        zoom_in.setObjectName("ghost")
        zoom_in.clicked.connect(lambda: self._zoom_by(0.2))

        fit = QPushButton("适应窗口")
        fit.setObjectName("ghost")
        fit.clicked.connect(self.fit_to_window)

        close_btn = QPushButton("关闭 (Esc)")
        close_btn.setObjectName("ghost")
        close_btn.clicked.connect(self.close)

        footer_layout.addWidget(self.zoom_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(zoom_out)
        footer_layout.addWidget(zoom_in)
        footer_layout.addWidget(fit)
        footer_layout.addWidget(close_btn)
        root.addWidget(footer)

    # ------------------------------------------------------------------ 外部调用
    def show_image(self, pixmap: QPixmap | None, name: str, position: str) -> None:
        self.name_label.setText(name)
        self.count_label.setText(position)
        if pixmap is None or pixmap.isNull():
            self.image_label.setText("图片加载失败")
            self.image_label.setStyleSheet("color:#9CA3AF;")
            self._pixmap = QPixmap()
            return
        self.image_label.setStyleSheet("")
        self._pixmap = pixmap
        self.fit_to_window()

    def fit_to_window(self) -> None:
        if self._pixmap.isNull():
            return
        available = self.image_label.size()
        if available.width() <= 0 or available.height() <= 0:
            self._zoom = 1.0
            return
        scale = min(
            available.width() / max(1, self._pixmap.width()),
            available.height() / max(1, self._pixmap.height()),
            1.0,
        )
        self._zoom = scale
        self._apply_zoom()

    def _zoom_by(self, delta: float) -> None:
        if self._pixmap.isNull():
            return
        self._zoom = min(4.0, max(0.1, self._zoom + delta))
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        width = max(1, int(self._pixmap.width() * self._zoom))
        height = max(1, int(self._pixmap.height() * self._zoom))
        self.image_label.setPixmap(
            self._pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.zoom_label.setText(f"{int(self._zoom * 100)}%")

    def set_navigation(self, has_prev: bool, has_next: bool) -> None:
        self.prev_btn.setEnabled(has_prev)
        self.next_btn.setEnabled(has_next)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fit_to_window()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Left:
            self.prev_requested.emit()
        elif event.key() == Qt.Key_Right:
            self.next_requested.emit()
        else:
            super().keyPressEvent(event)
