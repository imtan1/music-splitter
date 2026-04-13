import io
import base64
import tempfile
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QComboBox, QSpinBox, QMessageBox,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from core.player import TrackState
from core.transcriber import TranscriberThread, convert_raw_to_jianpu


ALL_KEYS = [
    '自動偵測',
    'C', 'D', 'E', 'F', 'G', 'A', 'B',
    'C#', 'Db', 'Eb', 'F#', 'Gb', 'Ab', 'Bb',
    'Cm', 'Dm', 'Em', 'Fm', 'Gm', 'Am', 'Bm',
]


class JianpuView(QDialog):
    def __init__(self, track: TrackState, label: str,
                 precomputed=None, parent=None, file_title=''):
        """
        precomputed: (raw_notes, jianpu_notes, tempo, key, beat_dur) 或 None。
        傳入時跳過轉寫直接渲染，適合從 MidiView 呼叫以避免重複分析。
        """
        super().__init__(parent)
        self.track = track
        self.label = label
        self._file_title = file_title or label
        self.setWindowTitle(f"簡譜 — {self._file_title}")
        self.resize(420, 220)

        self._raw_notes = None
        self._beat_dur = None
        self._auto_key = 'C'
        self._auto_tempo = 120.0
        self._thread = None
        self._tmp_html = None

        self._build_ui()

        if precomputed is not None:
            raw_notes, jianpu_notes, tempo, key, beat_dur = precomputed
            self._on_done(raw_notes, jianpu_notes, tempo, key, beat_dur)
        else:
            self._start_transcription()

    # ──────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── 控制列 ──
        ctrl = QHBoxLayout()

        ctrl.addWidget(QLabel("調性："))
        self._key_combo = QComboBox()
        self._key_combo.addItems(ALL_KEYS)
        self._key_combo.setFixedWidth(110)
        ctrl.addWidget(self._key_combo)

        ctrl.addWidget(QLabel("速度："))
        self._tempo_spin = QSpinBox()
        self._tempo_spin.setRange(40, 240)
        self._tempo_spin.setValue(120)
        self._tempo_spin.setSuffix(" BPM")
        ctrl.addWidget(self._tempo_spin)

        self._render_btn = QPushButton("重新生成")
        self._render_btn.setEnabled(False)
        self._render_btn.clicked.connect(self._rerender)
        ctrl.addWidget(self._render_btn)

        ctrl.addStretch()

        self._open_btn = QPushButton("在瀏覽器開啟")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_browser)
        ctrl.addWidget(self._open_btn)

        root.addLayout(ctrl)

        # ── 進度 ──
        self._progress_lbl = QLabel("準備分析...")
        root.addWidget(self._progress_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        root.addWidget(self._progress_bar)

        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setVisible(False)
        root.addWidget(self._status_lbl)

    # ──────────────────────────────────────────────
    # 轉寫
    # ──────────────────────────────────────────────

    def _start_transcription(self):
        self._thread = TranscriberThread(self.track.audio, self.track.sample_rate, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_done)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, msg: str, pct: int):
        self._progress_lbl.setText(msg)
        self._progress_bar.setValue(pct)

    def _on_done(self, raw_notes, jianpu_notes, tempo, key, beat_dur):
        self._raw_notes = raw_notes
        self._beat_dur  = beat_dur
        self._auto_key  = key
        self._auto_tempo = tempo

        self._progress_bar.setVisible(False)
        self._progress_lbl.setVisible(False)

        self._tempo_spin.setValue(int(tempo))
        if key in ALL_KEYS:
            self._key_combo.setCurrentText(key)

        self._render_btn.setEnabled(True)
        self._open_btn.setEnabled(True)
        self._render_and_open()

    def _on_error(self, msg: str):
        self._progress_lbl.setText("分析失敗")
        self._progress_bar.setVisible(False)
        QMessageBox.critical(self, "轉寫失敗", msg)

    # ──────────────────────────────────────────────
    # 渲染 → HTML → 瀏覽器
    # ──────────────────────────────────────────────

    def _rerender(self):
        if self._raw_notes is None:
            return
        self._render_and_open()

    def _render_and_open(self):
        from core.jianpu_renderer import render_jianpu
        import matplotlib.pyplot as plt

        key = self._key_combo.currentText()
        if key == '自動偵測':
            key = self._auto_key

        tempo = float(self._tempo_spin.value())
        beat_dur = 60.0 / tempo

        notes = convert_raw_to_jianpu(self._raw_notes, key, beat_dur)

        self._render_btn.setEnabled(False)
        self._render_btn.setText("生成中...")
        try:
            fig = render_jianpu(notes, tempo=tempo, key_name=key,
                                title=self._file_title)

            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=130,
                        bbox_inches='tight', facecolor='white')
            buf.seek(0)
            plt.close(fig)

            png_b64 = base64.b64encode(buf.read()).decode('ascii')

            html = (
                '<!DOCTYPE html><html><head>'
                '<meta charset="utf-8">'
                f'<title>{self._file_title} 簡譜</title>'
                '<style>body{margin:0;background:#fff;display:flex;'
                'justify-content:center;} img{max-width:100%;height:auto;}</style>'
                '</head><body>'
                f'<img src="data:image/png;base64,{png_b64}">'
                '</body></html>'
            )

            # 清除上一個暫存檔
            if self._tmp_html and os.path.exists(self._tmp_html):
                try:
                    os.remove(self._tmp_html)
                except OSError:
                    pass

            with tempfile.NamedTemporaryFile(
                suffix='.html', delete=False, mode='w', encoding='utf-8'
            ) as f:
                self._tmp_html = f.name
                f.write(html)

            self._open_browser()

            self._status_lbl.setText("已在瀏覽器開啟")
            self._status_lbl.setVisible(True)

        except Exception as e:
            QMessageBox.critical(self, "渲染失敗", str(e))
        finally:
            self._render_btn.setEnabled(True)
            self._render_btn.setText("重新生成")

    def _open_browser(self):
        if self._tmp_html and os.path.exists(self._tmp_html):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._tmp_html))

    def closeEvent(self, event):
        if self._tmp_html and os.path.exists(self._tmp_html):
            try:
                os.remove(self._tmp_html)
            except OSError:
                pass
        super().closeEvent(event)
