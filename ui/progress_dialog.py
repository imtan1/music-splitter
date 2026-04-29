from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PySide6.QtCore import Qt


class ProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分源中...")
        self.setFixedSize(420, 150)
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

    def update_progress(self, message: str, percent: int):
        self.message_lbl.setText(message)
        self.progress_bar.setValue(percent)
