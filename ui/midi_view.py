"""
MIDI 分析視窗
- 顯示音軌波形
- 播放合成 MIDI 音頻
- 開啟五線譜 / 簡譜視窗
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar,
    QComboBox, QSpinBox, QMessageBox,
)
from PySide6.QtCore import QTimer

from core.player import TrackState
from core.transcriber import TranscriberThread, convert_raw_to_jianpu
from ui.waveform_widget import WaveformWidget


ALL_KEYS = [
    '自動偵測',
    'C', 'D', 'E', 'F', 'G', 'A', 'B',
    'C#', 'Db', 'Eb', 'F#', 'Gb', 'Ab', 'Bb',
    'Cm', 'Dm', 'Em', 'Fm', 'Gm', 'Am', 'Bm',
]


class MidiView(QDialog):
    def __init__(self, track: TrackState, label: str, parent=None, file_title: str = ''):
        super().__init__(parent)
        self.track = track
        self.label = label
        self._file_title = file_title or label
        self.setWindowTitle(f"MIDI — {label}")
        self.resize(900, 480)

        self._raw_notes = None
        self._jianpu_notes = None
        self._auto_key = 'C'
        self._auto_tempo = 120.0
        self._thread = None
        self._synth_audio = None
        self._is_playing = False
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_playback)

        self._build_ui()
        self._start_transcription()

    # ──────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 標題
        title_lbl = QLabel(f"MIDI — {self.label}")
        title_lbl.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #c4b5ff; margin-bottom: 2px;"
        )
        root.addWidget(title_lbl)

        # 進度（分析期間顯示）
        self._progress_lbl = QLabel("音高分析中...")
        root.addWidget(self._progress_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        root.addWidget(self._progress_bar)

        # 波形顯示（分析完成後才載入）
        self._waveform = WaveformWidget(None)
        self._waveform.setMinimumHeight(120)
        self._waveform.setVisible(False)
        root.addWidget(self._waveform, stretch=1)

        # ── 控制列 ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        # 播放 / 停止
        self._play_btn = QPushButton("▶ 播放 MIDI")
        self._play_btn.setObjectName("MasterPlayBtn")
        self._play_btn.setEnabled(False)
        self._play_btn.setFixedWidth(136)
        self._play_btn.clicked.connect(self._toggle_play)
        ctrl.addWidget(self._play_btn)

        # 五線譜
        self._staff_btn = QPushButton("📜 五線譜")
        self._staff_btn.setObjectName("JianpuBtn")
        self._staff_btn.setEnabled(False)
        self._staff_btn.setFixedWidth(90)
        self._staff_btn.setToolTip("顯示五線譜（需要 verovio）")
        self._staff_btn.clicked.connect(self._open_staff)
        ctrl.addWidget(self._staff_btn)

        # 簡譜
        self._jianpu_btn = QPushButton("♩ 簡譜")
        self._jianpu_btn.setObjectName("JianpuBtn")
        self._jianpu_btn.setEnabled(False)
        self._jianpu_btn.setFixedWidth(80)
        self._jianpu_btn.setToolTip("顯示簡譜")
        self._jianpu_btn.clicked.connect(self._open_jianpu)
        ctrl.addWidget(self._jianpu_btn)

        ctrl.addStretch()

        # 調性 / 速度
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

        root.addLayout(ctrl)

    # ──────────────────────────────────────────────
    # 轉寫
    # ──────────────────────────────────────────────

    def _start_transcription(self):
        self._waveform.set_position(0.0)
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
        self._jianpu_notes = jianpu_notes
        self._auto_key = key
        self._auto_tempo = tempo

        self._progress_lbl.setVisible(False)
        self._progress_bar.setVisible(False)

        self._tempo_spin.setValue(int(tempo))
        if key in ALL_KEYS:
            self._key_combo.setCurrentText(key)

        # 分析完成後才顯示波形
        self._waveform._load_audio(self.track.audio)
        self._waveform.setVisible(True)

        self._play_btn.setEnabled(True)
        self._staff_btn.setEnabled(True)
        self._jianpu_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self._progress_lbl.setText("分析失敗")
        self._progress_bar.setVisible(False)
        QMessageBox.critical(self, "轉寫失敗", msg)

    # ──────────────────────────────────────────────
    # MIDI 播放
    # ──────────────────────────────────────────────

    def _toggle_play(self):
        if self._is_playing:
            self._stop_play()
            return

        if self._jianpu_notes is None:
            return

        # 合成音頻（快取）
        if self._synth_audio is None:
            key = self._key_combo.currentText()
            if key == '自動偵測':
                key = self._auto_key
            tempo = float(self._tempo_spin.value())
            from core.midi_synth import synthesize
            self._synth_audio = synthesize(self._jianpu_notes, tempo, key)

        try:
            import sounddevice as sd
            sd.play(self._synth_audio, samplerate=44100)
        except Exception as e:
            QMessageBox.warning(self, "播放失敗", str(e))
            return

        self._is_playing = True
        self._play_btn.setText("⏹ 停止")
        self._poll_timer.start(300)

    def _stop_play(self):
        self._poll_timer.stop()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self._is_playing = False
        self._play_btn.setText("▶ 播放 MIDI")

    def _check_playback(self):
        try:
            import sounddevice as sd
            if not sd.get_stream().active:
                self._stop_play()
        except Exception:
            self._stop_play()

    # ──────────────────────────────────────────────
    # 開啟樂譜視窗
    # ──────────────────────────────────────────────

    def _current_key_tempo(self):
        key = self._key_combo.currentText()
        if key == '自動偵測':
            key = self._auto_key
        tempo = float(self._tempo_spin.value())
        return key, tempo

    def _open_staff(self):
        from ui.score_view import ScoreView
        key, tempo = self._current_key_tempo()
        dlg = ScoreView(self._jianpu_notes, tempo, key, self._file_title, parent=self)
        dlg.exec()

    def _open_jianpu(self):
        from ui.jianpu_view import JianpuView
        key, tempo = self._current_key_tempo()
        beat_dur = 60.0 / tempo
        notes = convert_raw_to_jianpu(self._raw_notes, key, beat_dur)
        dlg = JianpuView(
            track=self.track,
            label=self._file_title,
            precomputed=(self._raw_notes, notes, tempo, key, beat_dur),
            parent=self,
            file_title=self._file_title,
        )
        dlg.exec()

    # ──────────────────────────────────────────────
    # 關閉清理
    # ──────────────────────────────────────────────

    def closeEvent(self, event):
        self._stop_play()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
