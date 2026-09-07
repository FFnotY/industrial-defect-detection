"""左侧操作面板：选文件夹、填缺陷类型、开始 / 停止、本次摘要。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(8)

    label = QLabel(title)
    label.setObjectName("cardTitle")
    layout.addWidget(label)
    return card, layout


class ControlPanel(QFrame):
    folder_selected = Signal(str)
    start_requested = Signal(str, str)
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setFixedWidth(320)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        root.addLayout(self._build_folder_card())
        root.addLayout(self._build_prompt_card())
        root.addLayout(self._build_action_area())
        root.addLayout(self._build_summary())
        root.addStretch(1)

        self._set_busy(False)

    # ------------------------------------------------------------------ 文件夹
    def _build_folder_card(self) -> QVBoxLayout:
        card, layout = _card("选择图片文件夹")

        row = QHBoxLayout()
        row.setSpacing(8)

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("尚未选择文件夹")
        self.folder_edit.setMinimumWidth(140)
        self.folder_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        browse = QPushButton("浏览")
        browse.setObjectName("ghost")
        browse.setMinimumWidth(72)
        browse.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        browse.clicked.connect(self._on_browse)

        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse, 0)
        layout.addLayout(row)

        self.count_label = QLabel("共 0 张图片")
        self.count_label.setObjectName("hint")
        layout.addWidget(self.count_label)

        tip = QLabel("也可直接把文件夹拖拽到窗口空白处")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        return self._wrap_card(card)

    # ------------------------------------------------------------------ 缺陷类型
    def _build_prompt_card(self) -> QVBoxLayout:
        card, layout = _card("缺陷类型")

        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("如：裂纹 / crack / 划痕")
        self.prompt_edit.setToolTip("这段文本会作为 prompt 直接参与模型推理，支持中英文")
        layout.addWidget(self.prompt_edit)

        hint = QLabel("输入要检测的缺陷类型，中英文均可")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        return self._wrap_card(card)

    # ------------------------------------------------------------------ 操作区
    def _build_action_area(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(10)

        self.start_btn = QPushButton("开始检测")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        return layout

    # ------------------------------------------------------------------ 摘要
    def _build_summary(self) -> QVBoxLayout:
        card, layout = _card("本次运行")

        row = QHBoxLayout()
        self.total_value = QLabel("0")
        self.success_value = QLabel("0")
        self.fail_value = QLabel("0")

        self.total_value.setObjectName("value")
        self.success_value.setObjectName("valueSuccess")
        self.fail_value.setObjectName("valueFail")

        for label, value in (
            ("总数", self.total_value),
            ("成功", self.success_value),
            ("失败", self.fail_value),
        ):
            box = QVBoxLayout()
            caption = QLabel(label)
            caption.setObjectName("hint")
            caption.setAlignment(Qt.AlignCenter)
            value.setAlignment(Qt.AlignCenter)
            box.addWidget(value)
            box.addWidget(caption)
            row.addLayout(box)

        layout.addLayout(row)
        return self._wrap_card(card)

    # ------------------------------------------------------------------ 工具
    def _wrap_card(self, card: QFrame) -> QVBoxLayout:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(0)
        wrapper.addWidget(card)
        return wrapper

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择待检测图片文件夹")
        if folder:
            self.set_folder(folder)

    def set_folder(self, folder: str) -> None:
        self.folder_edit.setText(folder)
        self.folder_edit.setToolTip(folder)
        self.folder_selected.emit(folder)

    def current_folder(self) -> str:
        return self.folder_edit.text().strip()

    def current_prompt(self) -> str:
        return self.prompt_edit.text().strip()

    def _on_start(self) -> None:
        self.start_requested.emit(self.current_folder(), self.current_prompt())

    # ------------------------------------------------------------------ 状态更新
    def set_image_count(self, total: int) -> None:
        self.count_label.setText(f"共 {total} 张图片")

    def set_scan_error(self, message: str) -> None:
        self.count_label.setText(message)

    def reset_summary(self) -> None:
        self.total_value.setText("0")
        self.success_value.setText("0")
        self.fail_value.setText("0")

    def update_summary(self, info: dict) -> None:
        self.total_value.setText(str(info.get("total", 0)))
        self.success_value.setText(str(info.get("succeeded", 0)))
        self.fail_value.setText(str(info.get("failed", 0)))

    def _set_busy(self, busy: bool) -> None:
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.start_btn.setText("检测中…" if busy else "开始检测")

    def set_busy(self, busy: bool) -> None:
        self._set_busy(busy)
