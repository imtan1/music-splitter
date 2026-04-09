import io
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFileDialog,
    QProgressBar, QComboBox, QSpinBox, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

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
                 precomputed=None, parent=None):
        """
        precomputed: (raw_notes, jianpu_notes, tempo, key, beat_dur) 或 None。
        傳入時跳過轉寫直接渲染，適合從 MidiView 呼叫以避免重複分析。
        """
        super().__init__(parent)
        self.track = track
        self.label = label
        self.setWindowTitle(f"簡譜 — {label}")
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * 0.95), int(screen.height() * 0.95))

        self._raw_notes = None
        self._beat_dur = None
        self._auto_key = 'C'
        self._auto_tempo = 120.0
        self._thread = None

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
        root.setContentsMargins(10, 10, 10, 10)

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

        self._save_btn = QPushButton("⬇ 儲存 PNG")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_png)
        ctrl.addWidget(self._save_btn)

        root.addLayout(ctrl)

        # ── 進度 ──
        self._progress_lbl = QLabel("準備分析...")
        root.addWidget(self._progress_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        root.addWidget(self._progress_bar)

        # ── 簡譜圖像（可捲動） ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self._image_lbl = QLabel("等待分析完成...")
        self._image_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(self._image_lbl)
        root.addWidget(scroll)

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
        self._save_btn.setEnabled(True)
        self._render_image()

    def _on_error(self, msg: str):
        self._progress_lbl.setText("分析失敗")
        self._progress_bar.setVisible(False)
        QMessageBox.critical(self, "轉寫失敗", msg)

    # ──────────────────────────────────────────────
    # 渲染
    # ──────────────────────────────────────────────

    def _rerender(self):
        if self._raw_notes is None:
            return
        self._render_image()

    def _render_image(self):
        from core.jianpu_renderer import render_jianpu

        key = self._key_combo.currentText()
        if key == '自動偵測':
            key = self._auto_key

        tempo = float(self._tempo_spin.value())
        beat_dur = 60.0 / tempo

        # 重新轉換（換調或換速度都需要重算）
        notes = convert_raw_to_jianpu(self._raw_notes, key, beat_dur)

        self._render_btn.setEnabled(False)
        self._render_btn.setText("生成中...")
        try:
            fig = render_jianpu(notes, tempo=tempo, key_name=key, title=self.label)

            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=130,
                        bbox_inches='tight', facecolor='white')
            buf.seek(0)

            import matplotlib.pyplot as plt
            plt.close(fig)

            pixmap = QPixmap()
            pixmap.loadFromData(buf.read())

            self._image_lbl.setPixmap(pixmap)
            self._image_lbl.resize(pixmap.size())
        except Exception as e:
            QMessageBox.critical(self, "渲染失敗", str(e))
        finally:
            self._render_btn.setEnabled(True)
            self._render_btn.setText("重新生成")

    # ──────────────────────────────────────────────
    # 儲存
    # ──────────────────────────────────────────────

    def _save_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "儲存簡譜",
            f"{self.label}_簡譜.png",
            "PNG 圖片 (*.png)",
        )
        if not path:
            return
        pixmap = self._image_lbl.pixmap()
        if pixmap and not pixmap.isNull():
            pixmap.save(path, 'PNG')
            QMessageBox.information(self, "完成", f"已儲存：\n{path}")
