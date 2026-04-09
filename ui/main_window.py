import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QStackedWidget,
    QCheckBox, QGroupBox, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont

from core.separator import SeparatorThread, STEMS, STEM_LABELS
from ui.progress_dialog import ProgressDialog
from ui.result_view import ResultView


class DropZoneLabel(QLabel):
    """支援拖曳的上傳區域"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAlignment(Qt.AlignCenter)
        self.setText("🎵  拖曳音樂檔案至此\n\n或點擊選擇檔案\n\nMP3 · WAV · FLAC · M4A")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("border-color: #4CAF50; color: #4CAF50;")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.parent().parent().parent()._set_file(path)


class ImportPage(QWidget):
    def __init__(self, on_file_selected, parent=None):
        super().__init__(parent)
        self._on_file_selected = on_file_selected
        self._file_path = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(0)

        layout.addStretch(1)

        # 標題（HTML 雙色）
        title = QLabel()
        title.setTextFormat(Qt.RichText)
        title.setText(
            '<span style="font-size:38pt; font-weight:800; '
            'font-family:\'Segoe UI\',\'Microsoft JhengHei\';">'
            '<span style="color:#c4b5ff;">音樂</span>'
            '<span style="color:#00d4ff;">分源</span>'
            '<span style="color:#c4b5ff;">程式</span>'
            '</span>'
        )
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("margin-bottom: 6px;")
        layout.addWidget(title)

        # 副標題
        subtitle = QLabel("✦  AI 自動拆分人聲 · 鼓 · 貝斯 · 吉他 · 鋼琴 · 其他音軌  ✦")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "color: #454590; font-size: 13px; "
            "letter-spacing: 1px; margin-bottom: 24px;"
        )
        layout.addWidget(subtitle)

        # 拖曳區域
        self._drop_zone = DropZoneLabel(self)
        self._drop_zone.mousePressEvent = lambda e: self._browse_file()
        layout.addWidget(self._drop_zone)

        # 已選擇檔案
        self._file_lbl = QLabel("")
        self._file_lbl.setAlignment(Qt.AlignCenter)
        self._file_lbl.setStyleSheet(
            "color: #7B61FF; font-size: 12px; margin-top: 8px; font-weight: bold;"
        )
        layout.addWidget(self._file_lbl)

        layout.addSpacing(20)

        # 選擇音軌
        stems_group = QGroupBox("選擇要分離的音軌")
        stems_layout = QHBoxLayout(stems_group)
        stems_layout.setSpacing(16)
        self._stem_checks: dict[str, QCheckBox] = {}
        for stem in STEMS:
            cb = QCheckBox(STEM_LABELS[stem])
            cb.setChecked(True)
            stems_layout.addWidget(cb)
            self._stem_checks[stem] = cb
        layout.addWidget(stems_group)

        layout.addSpacing(20)

        # 開始按鈕
        self._start_btn = QPushButton("✦  開始分離")
        self._start_btn.setObjectName("MasterPlayBtn")
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumHeight(48)
        self._start_btn.setStyleSheet(
            self._start_btn.styleSheet() + "font-size: 15px; letter-spacing: 1px;"
        )
        self._start_btn.clicked.connect(self._on_start)
        layout.addWidget(self._start_btn)

        layout.addStretch(2)

    def set_file(self, path: str):
        self._file_path = path
        name = os.path.basename(path)
        self._file_lbl.setText(f"✔  {name}")
        self._drop_zone.setText(f"✔  {name}\n\n點擊重新選擇")
        self._drop_zone.setStyleSheet("border-color: #7B61FF; color: #a090ff;")
        self._start_btn.setEnabled(True)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇音樂檔案",
            "",
            "音樂檔案 (*.mp3 *.wav *.flac *.m4a *.ogg);;所有檔案 (*)",
        )
        if path:
            self.set_file(path)

    def _on_start(self):
        selected = [s for s, cb in self._stem_checks.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "提示", "請至少選擇一個音軌。")
            return
        self._on_file_selected(self._file_path, selected)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("音樂分源程式")
        self.setMinimumSize(960, 620)

        self._thread: SeparatorThread | None = None
        self._progress_dialog: ProgressDialog | None = None

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._import_page = ImportPage(self._start_separation, self)
        self._result_view = ResultView(self)
        self._result_view.back_requested.connect(self._go_import)

        self._stack.addWidget(self._import_page)
        self._stack.addWidget(self._result_view)
        self._stack.setCurrentWidget(self._import_page)

    def _set_file(self, path: str):
        self._import_page.set_file(path)

    def _go_import(self):
        self._stack.setCurrentWidget(self._import_page)

    def _start_separation(self, file_path: str, stems: list[str]):
        self._progress_dialog = ProgressDialog(self)
        self._progress_dialog.show()

        self._thread = SeparatorThread(file_path, stems, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

        self._source_name = os.path.basename(file_path)

    def _on_progress(self, message: str, percent: int):
        if self._progress_dialog:
            self._progress_dialog.update_progress(message, percent)

    def _on_finished(self, results: dict):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

        self._result_view.load_results(results, self._source_name)
        self._stack.setCurrentWidget(self._result_view)

    def _on_error(self, message: str):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        QMessageBox.critical(self, "分源失敗", f"發生錯誤：\n{message}")
