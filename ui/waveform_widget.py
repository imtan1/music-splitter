import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPen


class WaveformWidget(QWidget):
    """
    繪製單一音軌的波形圖（bar chart 風格），並顯示播放進度（playhead）。
    audio: float32 numpy array, shape (samples, channels)
    """

    seek_requested = Signal(float)   # 0.0 ~ 1.0，點擊波形觸發跳轉

    WAVEFORM_COLOR = QColor("#6366f1")
    PLAYED_COLOR   = QColor("#0ea5e9")
    PLAYHEAD_COLOR = QColor("#1e293b")
    BG_COLOR       = QColor("#f8fafc")
    MUTED_COLOR    = QColor("#cbd5e1")

    BAR_W = 3   # 每根 bar 寬度（px）
    BAR_G = 1   # bar 之間間距（px）

    def __init__(self, audio: np.ndarray, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setMinimumWidth(120)
        self._peaks: np.ndarray = np.array([])
        self._position = 0.0   # 0.0 ~ 1.0
        self._muted = False
        self._load_audio(audio)

    def _load_audio(self, audio: np.ndarray):
        if audio is None or len(audio) == 0:
            self._peaks = np.zeros(1)
            return
        if audio.ndim == 2:
            mono = audio.mean(axis=1)
        else:
            mono = audio
        self._peaks = self._compute_peaks(mono, resolution=1000)
        self.update()

    def _compute_peaks(self, mono: np.ndarray, resolution: int) -> np.ndarray:
        n = len(mono)
        if n == 0:
            return np.zeros(resolution)
        chunk_size = max(1, n // resolution)
        peaks = []
        for i in range(resolution):
            start = i * chunk_size
            end = min(start + chunk_size, n)
            chunk = mono[start:end]
            if len(chunk) > 0:
                peaks.append(float(np.max(np.abs(chunk))))
            else:
                peaks.append(0.0)
        return np.array(peaks, dtype=np.float32)

    def set_position(self, ratio: float):
        self._position = max(0.0, min(1.0, ratio))
        self.update()

    def set_muted(self, muted: bool):
        self._muted = muted
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.width() > 0:
            ratio = max(0.0, min(1.0, event.x() / self.width()))
            self.seek_requested.emit(ratio)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.width() > 0:
            ratio = max(0.0, min(1.0, event.x() / self.width()))
            self.seek_requested.emit(ratio)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        mid = h // 2

        # Background
        painter.fillRect(0, 0, w, h, self.BG_COLOR)

        if len(self._peaks) == 0:
            painter.end()
            return

        n = len(self._peaks)
        playhead_x = int(self._position * w)
        step = self.BAR_W + self.BAR_G

        for bar_x in range(0, w - self.BAR_W + 1, step):
            center_x = bar_x + self.BAR_W // 2
            peak_idx = min(int(center_x / w * n), n - 1)
            amp = self._peaks[peak_idx]
            bar_h = max(2, int(amp * mid * 0.88))

            if self._muted:
                color = self.MUTED_COLOR
            elif center_x < playhead_x:
                color = self.PLAYED_COLOR
            else:
                color = self.WAVEFORM_COLOR

            painter.fillRect(bar_x, mid - bar_h, self.BAR_W, bar_h * 2, color)

        # Playhead
        if 0.0 < self._position <= 1.0:
            painter.setPen(QPen(self.PLAYHEAD_COLOR, 1))
            painter.drawLine(playhead_x, 0, playhead_x, h)

        painter.end()
