"""右侧结果图片墙：自适应网格、惰性加载、悬停动效、点击放大。"""

from __future__ import annotations

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from client.config import THUMB_HEIGHT, THUMB_WIDTH
from client.workers import ImageLoader


class Tile(QFrame):
    """单张结果图卡片。"""

    clicked = Signal(int)

    def __init__(self, index: int, name: str) -> None:
        super().__init__()
        self.setObjectName("tile")
        self.index = index
        self.name = name
        self.loaded = False

        self.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT + 24)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)

        self.thumb = QLabel("加载中…")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedSize(THUMB_WIDTH - 16, THUMB_HEIGHT - 16)
        self.thumb.setStyleSheet("color:#9CA3AF; font-size:11px;")

        self.caption = QLabel(name)
        self.caption.setObjectName("tileName")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setFixedWidth(THUMB_WIDTH - 16)

        layout.addWidget(self.thumb)
        layout.addWidget(self.caption)

        # 入场淡入 + 轻微缩放
        self._animation = QPropertyAnimation(self, b"maximumHeight")
        self._animation.setDuration(220)
        self._animation.setStartValue(THUMB_HEIGHT)
        self._animation.setEndValue(THUMB_HEIGHT + 24)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def set_image(self, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(data))
        if pixmap.isNull():
            self.thumb.setText("无法显示")
            return
        scaled = pixmap.scaled(
            THUMB_WIDTH - 16,
            THUMB_HEIGHT - 16,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.thumb.setPixmap(scaled)
        self.thumb.setText("")
        self.loaded = True
        self.setToolTip(self.name)
        self._animation.start()

    def set_error(self, message: str) -> None:
        self.thumb.setText("加载失败")
        self.setToolTip(message)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.loaded:
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(event)


class ImageGallery(QFrame):
    """可滚动的图片墙，按可见区域惰性请求缩略图。"""

    tile_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 8, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().valueChanged.connect(self._schedule_lazy_load)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(16, 8, 16, 16)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll)

        self.empty_label = QLabel("选择文件夹并开始检测\n结果图会显示在这里")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("hint")
        self.empty_label.setStyleSheet("font-size:14px; padding:40px;")
        self.grid.addWidget(self.empty_label, 0, 0)

        self.job_id: str | None = None
        self.tiles: list[Tile] = []
        self._pending: set[str] = set()
        self._thread_pool = QThreadPool.globalInstance()
        self._lazy_timer = QTimer(self)
        self._lazy_timer.setSingleShot(True)
        self._lazy_timer.setInterval(120)
        self._lazy_timer.timeout.connect(self._load_visible)

        self._bump_scroll_policy()

    # ------------------------------------------------------------------ 公开接口
    def clear(self) -> None:
        self._remove_all_tiles()
        self.job_id = None
        self.empty_label.setVisible(True)

    def set_results(self, job_id: str, names: list[str]) -> None:
        """刷新结果列表：只增不减，保证界面上已有图片不闪。"""
        self.job_id = job_id

        existing = {tile.name for tile in self.tiles}
        new_names = [n for n in names if n not in existing]

        if self.tiles:
            self.empty_label.setVisible(False)
        if new_names:
            self.empty_label.setVisible(False)
            for name in new_names:
                self._add_tile(job_id, name)
        elif not self.tiles:
            self.empty_label.setVisible(True)

        if new_names:
            self._schedule_lazy_load()

    def full_pixmap(self, index: int) -> QPixmap | None:
        """给大图查看器用：直接再拉一次原图保证清晰度。"""
        if not self.job_id or not (0 <= index < len(self.tiles)):
            return None
        from client import api_client

        try:
            data = api_client.fetch_image(self.job_id, self.tiles[index].name)
        except Exception:  # noqa: BLE001
            return None
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(data))
        return pixmap if not pixmap.isNull() else None

    def names(self) -> list[str]:
        return [tile.name for tile in self.tiles]

    # ------------------------------------------------------------------ 内部实现
    def _remove_all_tiles(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is self.empty_label:
                continue
            if widget is not None:
                widget.deleteLater()
        self.empty_label.setParent(None)
        self.grid.addWidget(self.empty_label, 0, 0)
        self.tiles.clear()
        self._pending.clear()

    def _add_tile(self, job_id: str, name: str) -> None:
        tile = Tile(len(self.tiles), name)
        tile.clicked.connect(self.tile_clicked.emit)
        self.tiles.append(tile)
        self._relayout()

    def _relayout(self) -> None:
        self.empty_label.setParent(None)
        columns = self._column_count()
        for index, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, index // columns, index % columns)
        if not self.tiles:
            self.grid.addWidget(self.empty_label, 0, 0)

    def _column_count(self) -> int:
        width = self.scroll.viewport().width()
        columns = max(2, int((width - 32) // (THUMB_WIDTH + 14)))
        return columns

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.tiles and self._column_count() != getattr(self, "_last_columns", None):
            self._relayout()
            self._last_columns = self._column_count()
            self._schedule_lazy_load()

    def _bump_scroll_policy(self) -> None:
        self._last_columns = 2

    def _schedule_lazy_load(self, *_args) -> None:
        self._lazy_timer.start()

    def _load_visible(self) -> None:
        """只为进入可视区域的卡片请求图片，避免上百张图同时下载。"""
        if not self.job_id or not self._thread_pool:
            return

        container = self.scroll.widget()
        top_left = container.mapFrom(self.scroll.viewport(), QPoint(0, 0))
        visible = QRect(top_left, self.scroll.viewport().size())

        for tile in self.tiles:
            if tile.loaded or tile.name in self._pending:
                continue
            if not tile.geometry().intersects(visible):
                continue

            self._pending.add(tile.name)
            loader = ImageLoader(self.job_id, tile.name)
            loader.signals.loaded.connect(self._on_image_loaded)
            loader.signals.failed.connect(self._on_image_failed)
            self._thread_pool.start(loader)

    def _on_image_loaded(self, name: str, data: bytes) -> None:
        self._pending.discard(name)
        for tile in self.tiles:
            if tile.name == name:
                tile.set_image(data)
                break

    def _on_image_failed(self, name: str, message: str) -> None:
        self._pending.discard(name)
        for tile in self.tiles:
            if tile.name == name:
                tile.set_error(message)
                break
