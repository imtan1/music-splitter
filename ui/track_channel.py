from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QSlider, QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from core.player import TrackState, SingleTrackPlayer
from core.mixer import mix_single_track
from core.exporter import export_mp3
from ui.waveform_widget import WaveformWidget


class TrackChannel(QWidget):
    """單一音軌的橫向 row：[名稱] [波形] [▶] [M] [S] [音量] [⬇]"""

    mute_changed = Signal(str, bool)
    solo_changed = Signal(str, bool)
    volume_changed = Signal(str, float)
    seek_requested = Signal(float)   # 0.0 ~ 1.0，波形點擊觸發

    def __init__(self, track: TrackState, label: str, parent=None,
                 file_title: str = '', get_tempo=None, get_key=None):
        super().__init__(parent)
        self.track = track
        self.label = label
        self._file_title = file_title
        self._get_tempo = get_tempo or (lambda: 120.0)
        self._get_key = get_key or (lambda: '自動偵測')
        self._solo_player = SingleTrackPlayer(self)
        self._solo_player.load(track)
        self._solo_player.playback_stopped.connect(self._on_solo_stopped)
        self._build_ui()

    def _build_ui(self):
        self.setFixedHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setObjectName("TrackChannel")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)

        # 音軌名稱
        name_lbl = QLabel(self.label)
        name_lbl.setFixedWidth(48)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setObjectName("TrackName")
        row.addWidget(name_lbl)

        # 波形圖（佔剩餘寬度）
        self.waveform = WaveformWidget(self.track.audio)
        self.waveform.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.waveform.seek_requested.connect(self.seek_requested)
        row.addWidget(self.waveform)

        # 獨立播放鈕
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("PlayBtn")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setToolTip("獨立播放此音軌")
        self.play_btn.clicked.connect(self._toggle_solo_play)
        row.addWidget(self.play_btn)

        # M / S 按鈕
        self.mute_btn = QPushButton("M")
        self.mute_btn.setObjectName("MuteBtn")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedSize(32, 32)
        self.mute_btn.setToolTip("靜音")
        self.mute_btn.toggled.connect(self._on_mute_toggled)
        row.addWidget(self.mute_btn)

        self.solo_btn = QPushButton("S")
        self.solo_btn.setObjectName("SoloBtn")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedSize(32, 32)
        self.solo_btn.setToolTip("獨奏")
        self.solo_btn.toggled.connect(self._on_solo_toggled)
        row.addWidget(self.solo_btn)

        # 音量區（label + slider + 百分比）
        vol_col = QVBoxLayout()
        vol_col.setSpacing(2)
        vol_col.setContentsMargins(0, 0, 0, 0)

        vol_top = QHBoxLayout()
        vol_top.setSpacing(4)
        vol_lbl = QLabel("音量")
        vol_lbl.setObjectName("SmallLabel")
        self.vol_value_lbl = QLabel("100%")
        self.vol_value_lbl.setObjectName("SmallLabel")
        self.vol_value_lbl.setFixedWidth(36)
        vol_top.addWidget(vol_lbl)
        vol_top.addStretch()
        vol_top.addWidget(self.vol_value_lbl)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(120)
        self.vol_slider.setToolTip("音量 0–150%")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)

        vol_col.addLayout(vol_top)
        vol_col.addWidget(self.vol_slider)
        row.addLayout(vol_col)

        # 下載按鈕
        self.dl_btn = QPushButton("⬇ MP3")
        self.dl_btn.setObjectName("DownloadBtn")
        self.dl_btn.setFixedWidth(80)
        self.dl_btn.setToolTip("下載此音軌 MP3 320k")
        self.dl_btn.clicked.connect(self._on_download)
        row.addWidget(self.dl_btn)

        # 人聲軌才顯示 MIDI 按鈕
        if self.track.name == 'vocals':
            self.midi_btn = QPushButton("♪ MIDI")
            self.midi_btn.setObjectName("JianpuBtn")
            self.midi_btn.setFixedWidth(76)
            self.midi_btn.setToolTip("分析人聲音高並顯示 MIDI / 樂譜")
            self.midi_btn.clicked.connect(self._on_midi)
            row.addWidget(self.midi_btn)

    # ------------------------------------------------------------------
    # 公開方法
    # ------------------------------------------------------------------

    def set_position(self, ratio: float):
        self.waveform.set_position(ratio)

    def set_solo_active(self, active: bool):
        self.waveform.set_muted(active and not self.solo_btn.isChecked())

    def force_unsolo(self):
        self.solo_btn.blockSignals(True)
        self.solo_btn.setChecked(False)
        self.solo_btn.blockSignals(False)
        self.track.solo = False
        self.waveform.set_muted(self.mute_btn.isChecked())

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _toggle_solo_play(self):
        if self._solo_player.is_playing():
            self._solo_player.stop()
            self.play_btn.setText("▶")
        else:
            self._solo_player.play()
            self.play_btn.setText("⏹")

    def _on_solo_stopped(self):
        self.play_btn.setText("▶")

    def _on_mute_toggled(self, checked: bool):
        self.track.muted = checked
        self.waveform.set_muted(checked)
        self.mute_changed.emit(self.track.name, checked)

    def _on_solo_toggled(self, checked: bool):
        self.track.solo = checked
        self.solo_changed.emit(self.track.name, checked)

    def _on_volume_changed(self, value: int):
        ratio = value / 100.0
        self.track.volume = ratio
        self.vol_value_lbl.setText(f"{value}%")
        self.volume_changed.emit(self.track.name, ratio)

    def _on_midi(self):
        from ui.midi_view import MidiView
        dlg = MidiView(self.track, self.label, parent=self,
                       file_title=self._file_title,
                       initial_tempo=self._get_tempo(),
                       initial_key=self._get_key())
        dlg.exec()

    def _on_download(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"儲存 {self.label} 音軌",
            f"{self.label}.mp3",
            "MP3 檔案 (*.mp3)",
        )
        if not path:
            return

        self.dl_btn.setText("...")
        self.dl_btn.setEnabled(False)
        try:
            audio, sr = mix_single_track(self.track)
            export_mp3(audio, sr, path, bitrate="320k")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "匯出失敗", str(e))
        finally:
            self.dl_btn.setText("⬇ MP3")
            self.dl_btn.setEnabled(True)
