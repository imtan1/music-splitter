import threading
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

    mute_changed      = Signal(str, bool)
    solo_changed      = Signal(str, bool)
    volume_changed    = Signal(str, float)
    seek_requested    = Signal(float)   # 0.0 ~ 1.0，波形點擊觸發
    solo_play_started = Signal()        # 單軌播放開始，通知 ResultView 停掉其它來源
    position_changed  = Signal(float)   # 單軌播放進度，0.0 ~ 1.0
    download_started  = Signal()        # 開始下載，通知外部鎖住其他按鈕
    download_finished = Signal()        # 下載結束（成功/失敗/取消），通知外部解鎖
    _dl_ready         = Signal()        # 音頻準備好，可跳出存檔視窗
    _dl_done          = Signal(str)     # 儲存完成（錯誤訊息，空字串=成功）

    def __init__(self, track: TrackState, label: str, parent=None,
                 file_title: str = '', get_speed=None, get_export_audio=None):
        super().__init__(parent)
        self.track = track
        self.label = label
        self._file_title = file_title
        self._get_speed = get_speed or (lambda: 1.0)
        self._get_export_audio = get_export_audio or (lambda: None)
        self._dl_ready.connect(self._on_download_ready)
        self._dl_done.connect(self._on_download_done)
        self._solo_player = SingleTrackPlayer(self)
        self._solo_player.load(track)
        self._solo_player.playback_stopped.connect(self._on_solo_stopped)
        self._solo_player.position_changed.connect(self.position_changed)
        self._build_ui()

    def _build_ui(self):
        self.setFixedHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setObjectName("TrackChannel")

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
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
        self.mute_btn.setFixedSize(30, 30)
        self.mute_btn.setToolTip("靜音")
        self.mute_btn.toggled.connect(self._on_mute_toggled)
        row.addWidget(self.mute_btn)

        self.solo_btn = QPushButton("S")
        self.solo_btn.setObjectName("SoloBtn")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedSize(30, 30)
        self.solo_btn.setToolTip("獨奏")
        self.solo_btn.toggled.connect(self._on_solo_toggled)
        row.addWidget(self.solo_btn)

        # 音量滑桿
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(120)
        self.vol_slider.setToolTip("音量 0–150%")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.vol_slider)

        self.vol_value_lbl = QLabel("100%")
        self.vol_value_lbl.setObjectName("SmallLabel")
        self.vol_value_lbl.setFixedWidth(36)
        row.addWidget(self.vol_value_lbl)

        # 下載按鈕
        self.dl_btn = QPushButton("⬇ MP3")
        self.dl_btn.setObjectName("DownloadBtn")
        self.dl_btn.setFixedWidth(80)
        self.dl_btn.setToolTip("下載此音軌 MP3 320k")
        self.dl_btn.clicked.connect(self._on_download)
        row.addWidget(self.dl_btn)

    # ------------------------------------------------------------------
    # 公開方法
    # ------------------------------------------------------------------

    def set_position(self, ratio: float):
        self.waveform.set_position(ratio)

    def update_waveform(self):
        """移調後重繪波形圖（從 track.audio 重新計算 peaks）。"""
        self.waveform._load_audio(self.track.audio)

    def set_solo_active(self, active: bool):
        self.waveform.set_muted(active and not self.solo_btn.isChecked())

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def stop_solo_play(self):
        """外部呼叫：強制停止單軌播放並還原按鈕狀態。"""
        if self._solo_player.is_playing():
            self._solo_player.stop()
            self.play_btn.setText("▶")

    def seek_solo_player(self, ratio: float):
        """外部呼叫：設定單軌播放起始位置（播放中或播放前皆可）。"""
        self._solo_player.seek(ratio)

    def is_solo_playing(self) -> bool:
        """外部呼叫：查詢此音軌是否正在單軌播放。"""
        return self._solo_player.is_playing()

    def _toggle_solo_play(self):
        if self._solo_player.is_playing():
            self._solo_player.stop()
            self.play_btn.setText("▶")
        else:
            self.solo_play_started.emit()   # 先通知 ResultView 停掉其它播放
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

    def _on_download(self):
        self.dl_btn.setText("處理中...")
        self.dl_btn.setEnabled(False)
        self._dl_export_audio = None
        self._dl_prepare_error = ''
        self.download_started.emit()

        def _prepare():
            try:
                self._dl_export_audio = self._get_export_audio()
            except Exception as e:
                self._dl_prepare_error = str(e)
            self._dl_ready.emit()

        threading.Thread(target=_prepare, daemon=True).start()

    def _on_download_ready(self):
        if self._dl_prepare_error:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "匯出失敗", self._dl_prepare_error)
            self.dl_btn.setText("⬇ MP3")
            self.dl_btn.setEnabled(True)
            self.download_finished.emit()
            return

        default_name = f"{self._file_title}_mixed_{self.label}.mp3" if self._file_title else f"{self.label}.mp3"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"儲存 {self.label} 音軌",
            default_name,
            "MP3 檔案 (*.mp3)",
        )
        if not path:
            self.dl_btn.setText("⬇ MP3")
            self.dl_btn.setEnabled(True)
            self.download_finished.emit()
            return

        export_audio = self._dl_export_audio

        def _save():
            error = ''
            try:
                audio, sr = mix_single_track(self.track, speed=self._get_speed(),
                                             export_audio=export_audio)
                export_mp3(audio, sr, path, bitrate="320k")
            except Exception as e:
                error = str(e)
            self._dl_done.emit(error)

        threading.Thread(target=_save, daemon=True).start()

    def _on_download_done(self, error: str):
        self.dl_btn.setText("⬇ MP3")
        self.dl_btn.setEnabled(True)
        self.download_finished.emit()
        if error:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "匯出失敗", error)
