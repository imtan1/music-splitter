import os
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QScrollArea, QFileDialog,
    QSizePolicy, QMessageBox, QSpinBox, QComboBox,
)
from PySide6.QtCore import Qt, Signal, QTimer

from core.player import AudioEngine, TrackState, SingleTrackPlayer
from core.mixer import mix_tracks
from core.exporter import export_mp3
from core.separator import STEM_LABELS
from ui.track_channel import TrackChannel

def _generate_metronome(total_samples: int, sample_rate: int, bpm: float) -> np.ndarray:
    """產生節拍器音頻陣列，單一點擊音。"""
    audio = np.zeros((total_samples, 2), dtype=np.float32)
    beat_samples = max(1, int(round(sample_rate * 60.0 / bpm)))
    click_dur = int(sample_rate * 0.022)   # 22ms 短促點擊

    t = np.arange(click_dur, dtype=np.float32) / sample_rate
    click = (np.sin(2 * np.pi * 1000.0 * t) * np.exp(-180.0 * t)).astype(np.float32)

    pos = 0
    while pos < total_samples:
        end = min(pos + click_dur, total_samples)
        chunk = click[:end - pos]
        audio[pos:end, 0] += chunk
        audio[pos:end, 1] += chunk
        pos += beat_samples

    np.clip(audio, -1.0, 1.0, out=audio)
    return audio


class MetronomeChannel(QWidget):
    """節拍器控制列：開關 + 速度倍率 + 音量。"""

    speed_changed = Signal()

    def __init__(self, track: TrackState, parent=None):
        super().__init__(parent)
        self.track = track
        self.track.muted = True          # 預設關閉
        self.multiplier = 1.0            # 速度倍率，預設 1x
        self.setObjectName("TrackChannel")
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build_ui()

    def _build_ui(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(12)

        name_lbl = QLabel("節拍器")
        name_lbl.setFixedWidth(48)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setObjectName("TrackName")
        row.addWidget(name_lbl)

        self._toggle_btn = QPushButton("開啟")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setFixedWidth(56)
        self._toggle_btn.setObjectName("MuteBtn")
        self._toggle_btn.toggled.connect(self._on_toggle)
        row.addWidget(self._toggle_btn)

        # 速度倍率按鈕 0.5x / 1x / 2x
        self._speed_btns: dict[float, QPushButton] = {}
        for label, mult in [("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0)]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(mult == 1.0)
            btn.setObjectName("SpeedBtn")
            btn.setFixedWidth(40)
            btn.clicked.connect(lambda _, m=mult: self._on_speed(m))
            self._speed_btns[mult] = btn
            row.addWidget(btn)

        row.addSpacing(8)
        row.addWidget(QLabel("音量："))

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 150)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(140)
        self._vol_slider.valueChanged.connect(self._on_volume)
        row.addWidget(self._vol_slider)

        self._vol_lbl = QLabel("80%")
        self._vol_lbl.setObjectName("SmallLabel")
        self._vol_lbl.setFixedWidth(38)
        row.addWidget(self._vol_lbl)

        row.addStretch()

        # 套用初始音量
        self.track.volume = 0.80

    def _on_toggle(self, checked: bool):
        self.track.muted = not checked
        self._toggle_btn.setText("關閉" if checked else "開啟")

    def _on_speed(self, mult: float):
        self.multiplier = mult
        for m, btn in self._speed_btns.items():
            btn.setChecked(m == mult)
        self.speed_changed.emit()

    def _on_volume(self, value: int):
        self.track.volume = value / 100.0
        self._vol_lbl.setText(f"{value}%")


# 調性選擇範圍：偵測調性居中，往上/往下各 8 半音
_PITCH_RANGE = 8
# 半音 → 音名：往上用升記號，往下用降記號
_PC_SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_PC_FLAT  = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

# 調性字串 → pitch class（僅供偵測結果轉換用）
KEY_PC: dict[str, int] = {
    'C':0,'C#':1,'Db':1,'D':2,'D#':3,'Eb':3,'E':4,
    'F':5,'F#':6,'Gb':6,'G':7,'G#':8,'Ab':8,'A':9,'A#':10,'Bb':10,'B':11,
}



class ResultView(QWidget):
    back_requested = Signal()   # 回主頁

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = AudioEngine(self)
        self._engine.position_changed.connect(self._on_position_changed)
        self._engine.playback_stopped.connect(self._on_playback_stopped)
        self._engine.pitch_processing_changed.connect(self._on_pitch_processing_changed)

        self._channels: list[TrackChannel] = []
        self._tracks: list[TrackState] = []
        self._metronome_track: TrackState | None = None
        self._metronome_channel: MetronomeChannel | None = None
        self._seek_dragging = False
        self._base_tempo = 120.0   # 分源時偵測到的原始 BPM，作為速度計算基準
        self._base_key_pc: int | None = None       # 分源偵測調性的根音半音值
        self._source_title: str = ''

        # 防抖計時器：BPM 停止變動後 600ms 才重建節拍器
        self._metro_rebuild_timer = QTimer(self)
        self._metro_rebuild_timer.setSingleShot(True)
        self._metro_rebuild_timer.setInterval(600)
        self._metro_rebuild_timer.timeout.connect(self._rebuild_metronome)

        self._build_ui()

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def get_tempo(self) -> float:
        return float(self._tempo_spin.value())

    def get_key(self) -> str:
        return self._key_combo.currentText()

    def load_results(self, results: dict, source_name: str = "",
                     tempo: float = 120.0, key: str = 'C'):
        """
        results: {stem_name: (audio_np, sample_rate)}
        tempo/key: 分源前偵測到的 BPM 與調性
        """
        self._engine.stop()
        self._channels.clear()
        self._tracks.clear()

        # 清除舊 channel strips
        for i in reversed(range(self._channels_layout.count())):
            w = self._channels_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

        # 更新 BPM / 調性控制（先斷開訊號避免觸發重建）
        self._base_tempo = max(40.0, min(240.0, float(tempo)))
        self._tempo_spin.valueChanged.disconnect()
        self._tempo_spin.setValue(max(40, min(240, int(tempo))))
        self._tempo_spin.valueChanged.connect(self._on_tempo_changed)
        base_pc = KEY_PC.get(key, 0)
        self._build_key_combo(base_pc, key or 'C')

        self._source_title = source_name or ''

        tracks = []
        file_title = os.path.splitext(source_name)[0] if source_name else ''

        for stem_name, (audio, sr) in results.items():
            label = STEM_LABELS.get(stem_name, stem_name)
            track = TrackState(stem_name, audio, sr)
            tracks.append(track)

            ch = TrackChannel(track, label, self, file_title=file_title,
                              get_tempo=self.get_tempo, get_key=self.get_key,
                              get_speed=lambda: self._engine.speed)
            ch.mute_changed.connect(self._on_mute_changed)
            ch.solo_changed.connect(self._on_solo_changed)
            ch.seek_requested.connect(self._on_waveform_seek)
            ch.solo_play_started.connect(self._on_solo_play_started)
            ch.position_changed.connect(self._on_position_changed)
            # 插在 stretch 之前
            self._channels_layout.insertWidget(self._channels_layout.count() - 1, ch)
            self._channels.append(ch)

        self._tracks = tracks

        # 建立節拍器音軌
        if tracks:
            total_samples = max(t.length for t in tracks)
            sr = tracks[0].sample_rate
            metro_audio = _generate_metronome(total_samples, sr, tempo)
            self._metronome_track = TrackState('metronome', metro_audio, sr)
            self._metronome_track.muted = True

            # 移除舊節拍器 widget
            if self._metronome_channel is not None:
                self._metronome_channel.deleteLater()
            self._metronome_channel = MetronomeChannel(self._metronome_track, self)
            self._metronome_channel.speed_changed.connect(self._rebuild_metronome)
            self._channels_layout.insertWidget(
                self._channels_layout.count() - 1, self._metronome_channel
            )

            engine_tracks = tracks + [self._metronome_track]
        else:
            engine_tracks = tracks

        self._engine.load_tracks(engine_tracks)
        self._engine.set_speed(1.0)
        self._engine.set_pitch_semitones(0)

        title = f"分離完成：{source_name}" if source_name else "分離完成"
        self._title_lbl.setText(title)

        # 重設 seek bar
        self._seek_bar.setValue(0)
        self._time_lbl.setText("00:00 / 00:00")

        # 更新總時長顯示
        if tracks:
            total_sec = tracks[0].length / tracks[0].sample_rate
            self._update_time_label(0.0, total_sec)

    # ------------------------------------------------------------------
    # UI 建立
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # 標題
        self._title_lbl = QLabel("分離完成")
        self._title_lbl.setAlignment(Qt.AlignCenter)
        font = self._title_lbl.font()
        font.setPointSize(16)
        font.setBold(True)
        self._title_lbl.setFont(font)
        root.addWidget(self._title_lbl)

        # ---- 整體控制列 ----
        master_box = QWidget()
        master_box.setObjectName("MasterBox")
        master_layout = QVBoxLayout(master_box)
        master_layout.setContentsMargins(12, 10, 12, 10)
        master_layout.setSpacing(8)

        # 播放控制列
        ctrl_row = QHBoxLayout()
        self._play_btn = QPushButton("▶ 整體播放")
        self._play_btn.setObjectName("MasterPlayBtn")
        self._play_btn.setFixedWidth(140)
        self._play_btn.clicked.connect(self._toggle_master_play)
        ctrl_row.addWidget(self._play_btn)

        self._time_lbl = QLabel("00:00 / 00:00")
        self._time_lbl.setObjectName("SmallLabel")
        ctrl_row.addWidget(self._time_lbl)
        ctrl_row.addStretch()
        master_layout.addLayout(ctrl_row)

        # Seek bar
        self._seek_bar = QSlider(Qt.Horizontal)
        self._seek_bar.setObjectName("SeekBar")
        self._seek_bar.setRange(0, 1000)
        self._seek_bar.setValue(0)
        self._seek_bar.sliderPressed.connect(self._on_seek_pressed)
        self._seek_bar.sliderReleased.connect(self._on_seek_released)
        master_layout.addWidget(self._seek_bar)

        # BPM / 調性列
        info_row = QHBoxLayout()

        info_row.addWidget(QLabel("速度："))
        self._tempo_spin = QSpinBox()
        self._tempo_spin.setRange(40, 240)
        self._tempo_spin.setValue(120)
        self._tempo_spin.setSuffix(" BPM")
        self._tempo_spin.setFixedWidth(100)
        self._tempo_spin.setToolTip("調整速度：同步改變播放速度與節拍器")
        self._tempo_spin.valueChanged.connect(self._on_tempo_changed)
        info_row.addWidget(self._tempo_spin)

        info_row.addSpacing(20)

        info_row.addWidget(QLabel("調性："))
        self._key_combo = QComboBox()
        self._key_combo.setFixedWidth(90)
        self._key_combo.setEnabled(False)
        self._key_combo.setToolTip("選擇調性後所有音軌將自動移調")
        self._key_combo.currentTextChanged.connect(self._on_key_changed)
        info_row.addWidget(self._key_combo)

        self._pitch_status_lbl = QLabel("⏳ 高品質移調處理中…")
        self._pitch_status_lbl.setObjectName("SmallLabel")
        self._pitch_status_lbl.setVisible(False)
        info_row.addWidget(self._pitch_status_lbl)

        info_row.addStretch()
        master_layout.addLayout(info_row)

        # 整體音量 + 下載
        vol_dl_row = QHBoxLayout()

        vol_lbl = QLabel("整體音量：")
        vol_lbl.setObjectName("SmallLabel")
        vol_dl_row.addWidget(vol_lbl)

        self._master_vol_slider = QSlider(Qt.Horizontal)
        self._master_vol_slider.setRange(0, 150)
        self._master_vol_slider.setValue(100)
        self._master_vol_slider.setFixedWidth(160)
        self._master_vol_slider.valueChanged.connect(self._on_master_volume_changed)
        vol_dl_row.addWidget(self._master_vol_slider)

        self._master_vol_lbl = QLabel("100%")
        self._master_vol_lbl.setObjectName("SmallLabel")
        self._master_vol_lbl.setFixedWidth(40)
        vol_dl_row.addWidget(self._master_vol_lbl)

        vol_dl_row.addStretch()

        self._dl_master_btn = QPushButton("⬇ 下載混音 MP3 320k")
        self._dl_master_btn.setObjectName("MasterDownloadBtn")
        self._dl_master_btn.clicked.connect(self._on_download_master)
        vol_dl_row.addWidget(self._dl_master_btn)

        master_layout.addLayout(vol_dl_row)
        root.addWidget(master_box)

        # ---- Channel Strips（直向可捲動） ----
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        channels_container = QWidget()
        self._channels_layout = QVBoxLayout(channels_container)
        self._channels_layout.setContentsMargins(8, 8, 8, 8)
        self._channels_layout.setSpacing(8)
        self._channels_layout.addStretch()

        scroll_area.setWidget(channels_container)
        root.addWidget(scroll_area)

        # ---- 底部按鈕 ----
        bottom_row = QHBoxLayout()
        back_btn = QPushButton("← 新增歌曲")
        back_btn.clicked.connect(self.back_requested)
        bottom_row.addWidget(back_btn)
        bottom_row.addStretch()
        root.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _stop_all_solo_players(self):
        """停止所有音軌的獨立播放。"""
        for ch in self._channels:
            ch.stop_solo_play()

    def _on_solo_play_started(self):
        """單軌開始播放 → 停掉 master 及其它所有單軌，並讓新軌從目前進度開始。"""
        current_ratio = self._seek_bar.value() / 1000.0

        if self._engine.is_playing():
            self._engine.pause()
            self._play_btn.setText("▶ 整體播放")

        # 停掉所有單軌（發出 signal 的那個尚未開始播，stop 對它無影響）
        self._stop_all_solo_players()

        # 讓即將播放的那軌從目前進度位置開始（signal 是同步的，play() 尚未執行）
        sender_ch = self.sender()
        if isinstance(sender_ch, TrackChannel):
            sender_ch.seek_solo_player(current_ratio)

    def _toggle_master_play(self):
        if self._engine.is_playing():
            self._engine.pause()
            self._play_btn.setText("▶ 整體播放")
        else:
            self._stop_all_solo_players()
            # 從 seek bar 目前位置繼續（單軌播放過程中 engine 位置不會更新）
            self._engine.seek(self._seek_bar.value() / 1000.0)
            self._engine.play()
            self._play_btn.setText("⏸ 暫停")

    def _on_pitch_processing_changed(self, processing: bool):
        self._pitch_status_lbl.setVisible(processing)

    def _on_playback_stopped(self):
        self._play_btn.setText("▶ 整體播放")

    def _on_position_changed(self, ratio: float):
        if not self._seek_dragging:
            self._seek_bar.blockSignals(True)
            self._seek_bar.setValue(int(ratio * 1000))
            self._seek_bar.blockSignals(False)

        # 更新所有波形 playhead
        for ch in self._channels:
            ch.set_position(ratio)

        # 更新時間標籤
        if self._tracks:
            total_sec = self._tracks[0].length / self._tracks[0].sample_rate
            self._update_time_label(ratio, total_sec)

    def _update_time_label(self, ratio: float, total_sec: float):
        current_sec = ratio * total_sec
        cur_m, cur_s = divmod(int(current_sec), 60)
        tot_m, tot_s = divmod(int(total_sec), 60)
        self._time_lbl.setText(f"{cur_m:02d}:{cur_s:02d} / {tot_m:02d}:{tot_s:02d}")

    def _on_seek_pressed(self):
        self._seek_dragging = True

    def _on_seek_released(self):
        ratio = self._seek_bar.value() / 1000.0
        self._engine.seek(ratio)
        for ch in self._channels:
            ch.set_position(ratio)
        self._seek_dragging = False

    def _on_waveform_seek(self, ratio: float):
        """波形圖點擊/拖曳 seek。"""
        self._engine.seek(ratio)
        for ch in self._channels:
            ch.set_position(ratio)
        self._seek_bar.blockSignals(True)
        self._seek_bar.setValue(int(ratio * 1000))
        self._seek_bar.blockSignals(False)
        if self._tracks:
            total_sec = self._tracks[0].length / self._tracks[0].sample_rate
            self._update_time_label(ratio, total_sec)

    def _on_master_volume_changed(self, value: int):
        self._engine.master_volume = value / 100.0
        self._master_vol_lbl.setText(f"{value}%")

    def _on_key_changed(self, key_text: str):
        """調性 combo 改動 → 即時套用移調（pedalboard 在 callback 裡處理，無需等待）。"""
        if not self._tracks:
            return
        self._apply_pitch_shift()

    def _build_key_combo(self, base_pc: int, base_name: str = 'C'):
        """以偵測調性為中心，動態產生 ±_PITCH_RANGE 半音的選項。"""
        self._key_combo.blockSignals(True)
        self._key_combo.clear()
        for offset in range(_PITCH_RANGE, -_PITCH_RANGE - 1, -1):
            pc = (base_pc + offset) % 12
            if offset == 0:
                name = base_name
            elif offset > 0:
                name = _PC_SHARP[pc]
            else:
                name = _PC_FLAT[pc]
            self._key_combo.addItem(name)
        self._key_combo.setCurrentIndex(_PITCH_RANGE)   # 中心 = 偵測調性 = 0 移調
        self._key_combo.setEnabled(True)
        self._key_combo.blockSignals(False)

    def _apply_pitch_shift(self):
        """偵測調性為基準，index 距中心的距離即為半音數（正=升，負=降）。"""
        if not self._tracks:
            return
        n_steps = _PITCH_RANGE - self._key_combo.currentIndex()
        self._engine.set_pitch_semitones(n_steps)

    def _on_tempo_changed(self, value: int):
        """BPM 改動：即時更新播放速度，並用防抖計時器重建節拍器。"""
        if self._base_tempo > 0:
            speed = value / self._base_tempo
            self._engine.set_speed(speed)
        self._metro_rebuild_timer.start()

    def _rebuild_metronome(self):
        """重建節拍器音軌（BPM 或速度倍率變動後觸發）。
        直接替換 TrackState.audio reference，engine callback 下一幀自動生效，不中斷播放。
        """
        if not self._tracks or self._metronome_track is None:
            return
        tempo = float(self._tempo_spin.value())
        if self._metronome_channel is not None:
            tempo *= self._metronome_channel.multiplier
        total_samples = max(t.length for t in self._tracks)
        sr = self._tracks[0].sample_rate
        self._metronome_track.audio = _generate_metronome(total_samples, sr, tempo)

    def _on_mute_changed(self, stem_name: str, muted: bool):
        pass  # TrackState 已在 channel 內更新，引擎 callback 自動讀取

    def _on_solo_changed(self, stem_name: str, soloed: bool):
        any_solo = any(t.solo for t in self._tracks)
        for ch in self._channels:
            if any_solo and ch.track.name != stem_name and not ch.track.solo:
                ch.set_solo_active(True)
            else:
                ch.set_solo_active(False)

    def _on_download_master(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "儲存混音結果",
            "mixed_output.mp3",
            "MP3 檔案 (*.mp3)",
        )
        if not path:
            return

        self._dl_master_btn.setText("處理中...")
        self._dl_master_btn.setEnabled(False)
        try:
            master_vol = self._master_vol_slider.value() / 100.0
            audio, sr = mix_tracks(
                self._tracks,
                master_volume=master_vol,
                speed=self._engine.speed,
                metronome_track=self._metronome_track,
            )
            export_mp3(audio, sr, path, bitrate="320k")
            QMessageBox.information(self, "完成", f"已儲存至：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "匯出失敗", str(e))
        finally:
            self._dl_master_btn.setText("⬇ 下載混音 MP3 320k")
            self._dl_master_btn.setEnabled(True)
