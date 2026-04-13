import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QScrollArea, QFileDialog,
    QSizePolicy, QMessageBox, QSpinBox, QComboBox,
)
from PySide6.QtCore import Qt, Signal

from core.player import AudioEngine, TrackState
from core.mixer import mix_tracks
from core.exporter import export_mp3
from core.separator import STEM_LABELS
from ui.track_channel import TrackChannel

ALL_KEYS = [
    '自動偵測',
    'C', 'D', 'E', 'F', 'G', 'A', 'B',
    'C#', 'Db', 'Eb', 'F#', 'Gb', 'Ab', 'Bb',
    'Cm', 'Dm', 'Em', 'Fm', 'Gm', 'Am', 'Bm',
]


class ResultView(QWidget):
    back_requested = Signal()   # 回主頁

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = AudioEngine(self)
        self._engine.position_changed.connect(self._on_position_changed)
        self._engine.playback_stopped.connect(self._on_playback_stopped)

        self._channels: list[TrackChannel] = []
        self._tracks: list[TrackState] = []
        self._seek_dragging = False

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

        # 更新 BPM / 調性控制
        self._tempo_spin.setValue(max(40, min(240, int(tempo))))
        display_key = key if key in ALL_KEYS else '自動偵測'
        self._key_combo.setCurrentText(display_key)

        tracks = []
        file_title = os.path.splitext(source_name)[0] if source_name else ''

        for stem_name, (audio, sr) in results.items():
            label = STEM_LABELS.get(stem_name, stem_name)
            track = TrackState(stem_name, audio, sr)
            tracks.append(track)

            ch = TrackChannel(track, label, self, file_title=file_title,
                              get_tempo=self.get_tempo, get_key=self.get_key)
            ch.mute_changed.connect(self._on_mute_changed)
            ch.solo_changed.connect(self._on_solo_changed)
            # 插在 stretch 之前
            self._channels_layout.insertWidget(self._channels_layout.count() - 1, ch)
            self._channels.append(ch)

        self._tracks = tracks
        self._engine.load_tracks(tracks)

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
        self._tempo_spin.setToolTip("調整後開啟 MIDI 分析將套用此速度")
        info_row.addWidget(self._tempo_spin)

        info_row.addSpacing(20)

        info_row.addWidget(QLabel("調性："))
        self._key_combo = QComboBox()
        self._key_combo.addItems(ALL_KEYS)
        self._key_combo.setFixedWidth(110)
        self._key_combo.setToolTip("調整後開啟 MIDI 分析將套用此調性")
        info_row.addWidget(self._key_combo)

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

    def _toggle_master_play(self):
        if self._engine.is_playing():
            self._engine.pause()
            self._play_btn.setText("▶ 整體播放")
        else:
            self._engine.play()
            self._play_btn.setText("⏸ 暫停")

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

    def _on_master_volume_changed(self, value: int):
        self._engine.master_volume = value / 100.0
        self._master_vol_lbl.setText(f"{value}%")

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
            audio, sr = mix_tracks(self._tracks, master_volume=master_vol)
            export_mp3(audio, sr, path, bitrate="320k")
            QMessageBox.information(self, "完成", f"已儲存至：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "匯出失敗", str(e))
        finally:
            self._dl_master_btn.setText("⬇ 下載混音 MP3 320k")
            self._dl_master_btn.setEnabled(True)
