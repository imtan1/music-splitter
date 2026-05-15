from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PySide6.QtCore import Qt, Signal


class ProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分源中...")
        self.setFixedSize(420, 190)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.message_lbl = QLabel("準備中...")
        self.message_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(32)
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn)

    def update_progress(self, message: str, percent: int):
        self.message_lbl.setText(message)
        self.progress_bar.setValue(percent)

    def _on_cancel(self):
        self.cancel_btn.setText("正在取消...")
        self.cancel_btn.setEnabled(False)
        self.cancel_requested.emit()
