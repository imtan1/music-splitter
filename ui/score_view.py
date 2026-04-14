"""
五線譜顯示視窗
verovio SVG 透過暫存 HTML 在系統預設瀏覽器開啟。
（Qt SVG Tiny 1.2 不支援 verovio 輸出；QWebEngineView 在部分 Windows 環境 crash）
"""
import os
import sys
import tempfile

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices


class ScoreView(QDialog):
    def __init__(self, notes: list, tempo: float, key_name: str,
                 label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"五線譜 — {label}")
        self.resize(480, 220)

        self._notes    = notes
        self._tempo    = tempo
        self._key_name = key_name
        self._label    = label
        self._svg_bytes: bytes | None = None
        self._tmp_html: str | None = None

        self._build_ui()
        QTimer.singleShot(100, self._render)

    # ──────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        self._status_lbl = QLabel("五線譜生成中，請稍候...")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(
            "color: #6366f1; font-size: 13px; padding: 4px;"
        )
        root.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._open_btn = QPushButton("🌐 在瀏覽器開啟")
        self._open_btn.setEnabled(False)
        self._open_btn.setFixedWidth(150)
        self._open_btn.clicked.connect(self._open_browser)
        btn_row.addWidget(self._open_btn)

        self._save_btn = QPushButton("⬇ 儲存 SVG")
        self._save_btn.setEnabled(False)
        self._save_btn.setFixedWidth(110)
        self._save_btn.clicked.connect(self._save_svg)
        btn_row.addWidget(self._save_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

    # ──────────────────────────────────────────────
    # 渲染
    # ──────────────────────────────────────────────

    def _show_error(self, msg: str):
        self._status_lbl.setText(f"⚠  {msg}")
        self._status_lbl.setStyleSheet(
            "color: #ef4444; font-size: 13px; padding: 4px;"
        )
        print(f"[ScoreView] 錯誤: {msg}", file=sys.stderr, flush=True)

    def _render(self):
        import traceback
        try:
            from core.staff_renderer import render_staff_svg
            svg_str, error_msg = render_staff_svg(
                self._notes, self._tempo, self._key_name, self._label
            )
        except Exception as e:
            self._show_error(f"render_staff_svg 例外：{e}\n{traceback.format_exc()}")
            return

        if error_msg is not None:
            self._show_error(error_msg)
            return

        if not svg_str:
            self._show_error("render_staff_svg 回傳空字串")
            return

        self._svg_bytes = svg_str.encode('utf-8')

        # 寫入暫存 HTML
        try:
            html = (
                '<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<style>body{margin:0;padding:16px;background:#fff;}'
                'svg{max-width:100%;height:auto;}</style>'
                f'</head><body>{svg_str}</body></html>'
            )
            with tempfile.NamedTemporaryFile(
                suffix='.html', delete=False,
                mode='w', encoding='utf-8'
            ) as f:
                self._tmp_html = f.name
                f.write(html)
        except Exception as e:
            self._show_error(f"寫入暫存檔失敗：{e}")
            return

        self._status_lbl.setText("✅  五線譜生成完成，點擊下方按鈕在瀏覽器中檢視。")
        self._status_lbl.setStyleSheet(
            "color: #059669; font-size: 13px; padding: 4px;"
        )
        self._open_btn.setEnabled(True)
        self._save_btn.setEnabled(True)

        # 自動開啟一次
        self._open_browser()

    def _open_browser(self):
        if self._tmp_html:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._tmp_html))

    # ──────────────────────────────────────────────
    # 儲存
    # ──────────────────────────────────────────────

    def _save_svg(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "儲存五線譜",
            f"{self._label}_五線譜.svg",
            "SVG 檔案 (*.svg)",
        )
        if path and self._svg_bytes:
            with open(path, 'wb') as f:
                f.write(self._svg_bytes)
            QMessageBox.information(self, "完成", f"已儲存：\n{path}")

    # ──────────────────────────────────────────────
    # 關閉清理
    # ──────────────────────────────────────────────

    def closeEvent(self, event):
        if self._tmp_html and os.path.exists(self._tmp_html):
            try:
                os.unlink(self._tmp_html)
            except OSError:
                pass
        super().closeEvent(event)
