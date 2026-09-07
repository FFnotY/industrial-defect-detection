"""参数设置弹窗：只调整性能与输出质量参数，不涉及模型本身。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    def __init__(self, config: dict | None = None) -> None:
        super().__init__()
        self.setWindowTitle("参数设置")
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(14)

        title = QLabel("性能与输出")
        title.setObjectName("title")
        root.addWidget(title)

        form_card = QFrame()
        form_card.setObjectName("card")
        form = QFormLayout(form_card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 64)
        self.batch_spin.setToolTip("每批送入模型的图片数量。显存不够时请调小")

        self.maxside_spin = QSpinBox()
        self.maxside_spin.setRange(0, 8192)
        self.maxside_spin.setSingleStep(256)
        self.maxside_spin.setToolTip("图片长边超过该值时先缩放再送入模型，0 表示不缩放")

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(50, 100)
        self.quality_spin.setToolTip("结果图的 JPEG 编码质量")

        form.addRow("每批图片数", self.batch_spin)
        form.addRow("超大图长边上限", self.maxside_spin)
        form.addRow("结果 JPEG 质量", self.quality_spin)
        root.addWidget(form_card)

        hint = QLabel("修改后立即对下一次检测生效")
        hint.setObjectName("hint")
        root.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        root.addLayout(buttons)

        self.set_config(config or {})

        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

    # ------------------------------------------------------------------ 数据
    def set_config(self, config: dict) -> None:
        self.batch_spin.setValue(int(config.get("batch_size", 8)))
        self.maxside_spin.setValue(int(config.get("max_side", 0)))
        self.quality_spin.setValue(int(config.get("jpeg_quality", 90)))

    def patch(self) -> dict:
        return {
            "batch_size": self.batch_spin.value(),
            "max_side": self.maxside_spin.value(),
            "jpeg_quality": self.quality_spin.value(),
        }
