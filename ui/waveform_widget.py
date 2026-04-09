import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QPen


class WaveformWidget(QWidget):
    """
    繪製單一音軌的波形圖，並顯示播放進度（playhead）。
    audio: float32 numpy array, shape (samples, channels)
    """

    WAVEFORM_COLOR = QColor("#7B61FF")
    PLAYED_COLOR   = QColor("#00d4ff")
    PLAYHEAD_COLOR = QColor("#ffffff")
    BG_COLOR       = QColor("#0e0e20")
    MUTED_COLOR    = QColor("#2a2a4a")

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
        # 取單聲道平均
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        mid = h // 2

        # Background
        painter.fillRect(0, 0, w, h, self.BG_COLOR)

        if len(self._peaks) == 0:
            return

        waveform_color = self.MUTED_COLOR if self._muted else self.WAVEFORM_COLOR
        pen = QPen(waveform_color)
        pen.setWidth(1)
        painter.setPen(pen)

        n = len(self._peaks)
        playhead_x = int(self._position * w)

        for px in range(w):
            peak_idx = int(px / w * n)
            peak_idx = min(peak_idx, n - 1)
            amp = self._peaks[peak_idx]
            bar_h = int(amp * mid * 0.9)

            # 播放過的部分用 cyan，未播放用 purple
            if px < playhead_x:
                color = self.PLAYED_COLOR if not self._muted else self.MUTED_COLOR
                painter.setPen(QPen(color))
            else:
                painter.setPen(QPen(waveform_color))

            painter.drawLine(px, mid - bar_h, px, mid + bar_h)

        # Playhead
        if 0.0 < self._position <= 1.0:
            painter.setPen(QPen(self.PLAYHEAD_COLOR, 1))
            painter.drawLine(playhead_x, 0, playhead_x, h)

        painter.end()
