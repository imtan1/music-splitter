"""
MIDI 分析視窗
- 顯示音軌波形
- 播放合成 MIDI 音頻
- 開啟五線譜 / 簡譜視窗
"""
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QMessageBox, QWidget, QSlider,
)
from PySide6.QtCore import QTimer, Qt, Signal

from core.player import TrackState
from core.transcriber import TranscriberThread, convert_raw_to_jianpu
from ui.waveform_widget import WaveformWidget
from ui.main_window import GradientIconWidget


_CHIP_STYLE = (
    "background:#EEEDFE; color:#534AB7; font-size:11px; "
    "font-weight:600; padding:3px 8px; border-radius:5px;"
)


class MidiView(QDialog):
    # 分析完成後發出，讓 TrackChannel 快取 raw_notes/tempo/beat_dur
    analysis_ready = Signal(list, float, float)  # raw_notes, tempo, beat_dur

    def __init__(self, track: TrackState, label: str, parent=None,
                 file_title: str = '', initial_tempo: float = 0.0,
                 initial_key: str = '',
                 precomputed: tuple = None):
        """
        precomputed: (raw_notes, tempo, beat_dur) 快取資料。
        若提供，跳過音高分析，直接用新 key 重新轉換，幾乎即時。
        """
        super().__init__(parent)
        self.track = track
        self.label = label
        self._file_title = file_title or label
        self._initial_tempo = initial_tempo
        self._initial_key = initial_key
        self._precomputed = precomputed
        self.setWindowTitle(f"MIDI — {label}")
        self.resize(900, 380)
        self.setMinimumSize(700, 320)

        self._raw_notes = None
        self._jianpu_notes = None
        self._auto_key = 'C'
        self._auto_tempo = 120.0
        self._thread = None
        self._synth_audio = None
        self._is_playing = False
        self._seek_ratio = 0.0
        self._play_start_ratio = 0.0
        self._play_start_time = 0.0
        self._volume = 1.0

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._update_playback)

        self._build_ui()
        self._start_transcription()

    # ──────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── 標題列：icon + 文字 + chips ──
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        icon = GradientIconWidget()
        icon.setFixedSize(32, 32)
        header_row.addWidget(icon, 0)

        # 中：標題 + 狀態
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(f"MIDI — {self.label}")
        title_lbl.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #534AB7;"
        )
        text_col.addWidget(title_lbl)

        self._status_lbl = QLabel("音高分析中...")
        self._status_lbl.setStyleSheet(
            "font-size: 10px; color: #999999;"
        )
        text_col.addWidget(self._status_lbl)

        header_row.addLayout(text_col, 1)

        # 右：調性 / BPM chips（初始隱藏）
        self._key_chip = QLabel("—")
        self._key_chip.setStyleSheet(_CHIP_STYLE)
        self._key_chip.setVisible(False)
        header_row.addWidget(self._key_chip, 0)

        self._tempo_chip = QLabel("— BPM")
        self._tempo_chip.setStyleSheet(_CHIP_STYLE)
        self._tempo_chip.setVisible(False)
        header_row.addWidget(self._tempo_chip, 0)

        root.addLayout(header_row)

        # ── 分析進度條（分析期間顯示）──
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        root.addWidget(self._progress_bar)

        # ── 波形（含左右 padding 容器，分析完成後才載入）──
        waveform_container = QWidget()
        wc_layout = QVBoxLayout(waveform_container)
        wc_layout.setContentsMargins(12, 4, 12, 4)
        wc_layout.setSpacing(0)

        self._waveform = WaveformWidget(None)
        self._waveform.setMinimumHeight(150)
        self._waveform.setMaximumHeight(250)
        self._waveform.setVisible(False)
        self._waveform.seek_requested.connect(self._on_waveform_seek)
        wc_layout.addWidget(self._waveform)

        root.addWidget(waveform_container, stretch=1)

        # ── 控制列 ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        self._play_btn = QPushButton("▶ 播放 MIDI")
        self._play_btn.setObjectName("MasterPlayBtn")
        self._play_btn.setEnabled(False)
        self._play_btn.setFixedWidth(136)
        self._play_btn.clicked.connect(self._toggle_play)
        ctrl.addWidget(self._play_btn)

        self._staff_btn = QPushButton("📜 五線譜")
        self._staff_btn.setObjectName("JianpuBtn")
        self._staff_btn.setEnabled(False)
        self._staff_btn.setFixedWidth(90)
        self._staff_btn.setToolTip("顯示五線譜（需要 verovio）")
        self._staff_btn.clicked.connect(self._open_staff)
        ctrl.addWidget(self._staff_btn)

        self._jianpu_btn = QPushButton("♩ 簡譜")
        self._jianpu_btn.setObjectName("JianpuBtn")
        self._jianpu_btn.setEnabled(False)
        self._jianpu_btn.setFixedWidth(80)
        self._jianpu_btn.setToolTip("顯示簡譜")
        self._jianpu_btn.clicked.connect(self._open_jianpu)
        ctrl.addWidget(self._jianpu_btn)

        ctrl.addStretch()

        ctrl.addWidget(QLabel("音量："))

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 150)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(120)
        self._vol_slider.setToolTip("MIDI 播放音量 0–150%")
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        ctrl.addWidget(self._vol_slider)

        self._vol_lbl = QLabel("100%")
        self._vol_lbl.setFixedWidth(36)
        ctrl.addWidget(self._vol_lbl)

        root.addLayout(ctrl)

    # ──────────────────────────────────────────────
    # 轉寫
    # ──────────────────────────────────────────────

    def _start_transcription(self):
        if self._initial_tempo > 0 or self._initial_key:
            key_display = self._initial_key or '偵測中'
            tempo_display = int(self._initial_tempo) if self._initial_tempo > 0 else '—'
            self._key_chip.setText(key_display)
            self._tempo_chip.setText(f"{tempo_display} BPM")

        self._waveform.set_position(0.0)
        self._thread = TranscriberThread(
            self.track.audio, self.track.sample_rate, self,
            initial_tempo=self._initial_tempo,
            initial_key=self._initial_key,
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_done)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, msg: str, pct: int):
        self._status_lbl.setText(msg)
        self._progress_bar.setValue(pct)

    def _on_done(self, raw_notes, jianpu_notes, tempo, key, beat_dur):
        self._raw_notes = raw_notes
        self._jianpu_notes = jianpu_notes
        self._auto_key = key
        self._auto_tempo = tempo

        self._progress_bar.setVisible(False)

        self._key_chip.setText(key)
        self._tempo_chip.setText(f"{int(tempo)} BPM")
        self._key_chip.setVisible(True)
        self._tempo_chip.setVisible(True)

        self._status_lbl.setText("音高分析完成")

        self._waveform._load_audio(self.track.audio)
        self._waveform.setVisible(True)

        self._play_btn.setEnabled(True)
        self._staff_btn.setEnabled(True)
        self._jianpu_btn.setEnabled(True)

        # 分析完成後立即在背景預合成 MIDI 音頻，避免第一次按播放時卡住
        import threading
        threading.Thread(target=self._presynthesize, daemon=True).start()

    def _on_error(self, msg: str):
        self._status_lbl.setText("分析失敗")
        self._progress_bar.setVisible(False)
        QMessageBox.critical(self, "轉寫失敗", msg)

    # ──────────────────────────────────────────────
    # MIDI 播放
    # ──────────────────────────────────────────────

    def _on_volume_changed(self, value: int):
        self._volume = value / 100.0
        self._vol_lbl.setText(f"{value}%")

    def _on_waveform_seek(self, ratio: float):
        self._seek_ratio = ratio
        self._waveform.set_position(ratio)
        if self._is_playing:
            self._start_play_from(ratio)

    def _presynthesize(self):
        from core.midi_synth import synthesize
        audio = synthesize(self._jianpu_notes, self._auto_tempo, self._auto_key)
        self._synth_audio = audio  # GIL 保證賦值原子性

    def _toggle_play(self):
        if self._is_playing:
            self._stop_play()
            return
        if self._jianpu_notes is None:
            return
        if self._synth_audio is None:
            # 背景合成尚未完成，同步等待
            from core.midi_synth import synthesize
            self._synth_audio = synthesize(
                self._jianpu_notes, self._auto_tempo, self._auto_key
            )
        self._start_play_from(self._seek_ratio)

    def _start_play_from(self, ratio: float):
        import sounddevice as sd
        total = len(self._synth_audio)
        start_sample = int(max(0.0, min(1.0, ratio)) * total)
        try:
            sd.stop()
            audio_slice = self._synth_audio[start_sample:] * self._volume
            sd.play(audio_slice, samplerate=44100, latency='low')
        except Exception as e:
            QMessageBox.warning(self, "播放失敗", str(e))
            return
        self._is_playing = True
        self._play_start_ratio = ratio
        self._play_start_time = time.time()
        self._play_btn.setText("⏹ 停止")
        self._poll_timer.start()

    def _stop_play(self):
        self._poll_timer.stop()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self._is_playing = False
        self._play_btn.setText("▶ 播放 MIDI")

    def _update_playback(self):
        import sounddevice as sd
        # 更新波形播放頭位置
        if self._synth_audio is not None:
            total_dur = len(self._synth_audio) / 44100
            if total_dur > 0:
                elapsed = time.time() - self._play_start_time
                ratio = self._play_start_ratio + elapsed / total_dur
                ratio = min(ratio, 1.0)
                self._waveform.set_position(ratio)
        # 檢查是否播放結束
        try:
            if not sd.get_stream().active:
                self._seek_ratio = 0.0
                self._waveform.set_position(0.0)
                self._stop_play()
        except Exception:
            self._stop_play()

    # ──────────────────────────────────────────────
    # 開啟樂譜視窗
    # ──────────────────────────────────────────────

    def _current_key_tempo(self):
        return self._auto_key, self._auto_tempo

    def _open_staff(self):
        from ui.score_view import ScoreView
        key, tempo = self._current_key_tempo()
        beat_dur = 60.0 / tempo
        notes = convert_raw_to_jianpu(self._raw_notes, key, beat_dur)
        dlg = ScoreView(notes, tempo, key, self._file_title, parent=self)
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
