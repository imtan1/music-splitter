import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QStackedWidget,
    QMessageBox, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QRectF, QSize, QByteArray
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QFont,
    QPainter, QLinearGradient, QColor, QPainterPath,
    QFontMetricsF,
)
from PySide6.QtSvg import QSvgRenderer

from core.separator import SeparatorThread, STEMS, STEM_LABELS
from ui.progress_dialog import ProgressDialog
from ui.result_view import ResultView


_MUSIC_SVG = b"""<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M9 18V5l12-2v13" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="6" cy="18" r="3" stroke="white" stroke-width="1.8" fill="none"/>
  <circle cx="18" cy="16" r="3" stroke="white" stroke-width="1.8" fill="none"/>
</svg>"""


class GradientIconWidget(QWidget):
    """48×48 圓角漸層背景 + 白色音符 SVG icon"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self._renderer = QSvgRenderer(QByteArray(_MUSIC_SVG), self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 漸層圓角背景（左上 → 右下）
        grad = QLinearGradient(0, 0, 48, 48)
        grad.setColorAt(0.0, QColor("#534AB7"))
        grad.setColorAt(1.0, QColor("#44aaff"))

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 48, 48), 14, 14)
        painter.fillPath(path, grad)

        # SVG icon 居中（24×24 置於 12,12）
        self._renderer.render(painter, QRectF(12, 12, 24, 24))
        painter.end()


class GradientLabel(QWidget):
    """漸層文字 Widget：#534AB7 → #7F77DD → #44aaff，34px bold"""

    _FONT_SIZE = 44
    _COLORS    = [
        (0.0, QColor("#534AB7")),
        (0.5, QColor("#7F77DD")),
        (1.0, QColor("#44aaff")),
    ]

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._font = QFont()
        self._font.setFamilies(["Segoe UI", "Microsoft JhengHei"])
        self._font.setPixelSize(self._FONT_SIZE)
        self._font.setBold(True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self._font)
        w = int(fm.horizontalAdvance(self._text)) + 8
        h = int(fm.height()) + 4
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        grad = QLinearGradient(0, 0, w, 0)
        for stop, color in self._COLORS:
            grad.setColorAt(stop, color)

        fm = QFontMetricsF(self._font)
        path = QPainterPath()
        path.addText(0, fm.ascent(), self._font, self._text)

        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawPath(path)
        painter.end()


# ──────────────────────────────────────────────────────────────────────────────


class DropZoneLabel(QLabel):
    """支援拖曳的上傳區域"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAlignment(Qt.AlignCenter)
        self._set_idle_text()
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        self._is_selected = False

    def _set_idle_text(self):
        self.setTextFormat(Qt.PlainText)
        self.setText("🎵  拖曳音樂檔案至此\n\n或點擊選擇檔案\n\nMP3 · WAV · FLAC · M4A")

    def set_selected(self, name: str):
        self._is_selected = True
        self.setTextFormat(Qt.RichText)
        self.setText(
            '🎵<br><br>'
            f'<span style="color:#6366f1; font-size:13px; font-weight:600;">'
            f'♪&nbsp;&nbsp;{name}</span><br><br>'
            '<span style="font-size:12px;">點擊重新選擇</span>'
        )
        self.setStyleSheet("border-color: #6366f1; color: #1e293b;")

    def set_idle(self):
        self._is_selected = False
        self.setStyleSheet("")
        self._set_idle_text()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("border-color: #6366f1; color: #6366f1;")

    def dragLeaveEvent(self, event):
        if self._is_selected:
            self.setStyleSheet("border-color: #6366f1; color: #1e293b;")
        else:
            self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        if self._is_selected:
            self.setStyleSheet("border-color: #6366f1; color: #1e293b;")
        else:
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

        # ── 標題列：icon 與標題文字同行，副標題縮排對齊 ──
        header_col = QVBoxLayout()
        header_col.setSpacing(2)
        header_col.setContentsMargins(0, 0, 0, 0)

        # 第一行：icon + 漸層標題（垂直置中對齊）
        icon_title_row = QHBoxLayout()
        icon_title_row.setSpacing(14)
        icon_title_row.setAlignment(Qt.AlignVCenter)

        icon_widget = GradientIconWidget()
        icon_title_row.addWidget(icon_widget, 0, Qt.AlignVCenter)

        grad_title = GradientLabel("音樂分源程式")
        icon_title_row.addWidget(grad_title, 0, Qt.AlignVCenter)

        header_col.addLayout(icon_title_row)

        # 第二行：副標題置中於整個 icon+標題 區塊
        subtitle_row = QHBoxLayout()
        subtitle_row.addStretch()
        subtitle = QLabel("AI 自動分離各聲部音軌")
        subtitle.setStyleSheet(
            "color: #888888; font-size: 12px; background: transparent;"
        )
        subtitle_row.addWidget(subtitle)
        subtitle_row.addStretch()
        header_col.addLayout(subtitle_row)

        title_row = QHBoxLayout()
        title_row.addLayout(header_col)
        title_row.addStretch()

        # 整體置中
        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addLayout(title_row)
        center_row.addStretch()
        layout.addLayout(center_row)

        layout.addSpacing(10)

        # ── 音軌 chips ──
        chip_row = QHBoxLayout()
        chip_row.setAlignment(Qt.AlignCenter)
        chip_row.setSpacing(6)
        for text in ['人聲', '鼓', '貝斯', '吉他', '鋼琴', '其他']:
            chip = QLabel(text)
            chip.setObjectName("TrackChip")
            chip_row.addWidget(chip)
        layout.addLayout(chip_row)

        layout.addSpacing(22)

        # ── 拖曳區域 ──
        self._drop_zone = DropZoneLabel(self)
        self._drop_zone.mousePressEvent = lambda e: self._browse_file()
        layout.addWidget(self._drop_zone)

        layout.addSpacing(20)

        # ── 開始按鈕 ──
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
        self._drop_zone.set_selected(name)
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
        self._on_file_selected(self._file_path, STEMS)


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
        self._thread.cancelled.connect(self._on_cancelled)
        self._progress_dialog.cancel_requested.connect(self._thread.cancel)
        self._thread.start()

        self._source_name = os.path.basename(file_path)

    def _on_progress(self, message: str, percent: int):
        if self._progress_dialog:
            self._progress_dialog.update_progress(message, percent)

    def _on_finished(self, results: dict, tempo: float, key: str):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

        self._result_view.load_results(results, self._source_name,
                                       tempo=tempo, key=key)
        self._stack.setCurrentWidget(self._result_view)

    def _on_cancelled(self):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        self._thread = None

    def _on_error(self, message: str):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        QMessageBox.critical(self, "分源失敗", f"發生錯誤：\n{message}")
