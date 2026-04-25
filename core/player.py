"""
音頻播放引擎
AudioEngine：多軌同步播放，支援靜音、獨奏、音量、播放速度與移調倍率，低延遲 sounddevice callback 混音。
SingleTrackPlayer：單軌獨立播放，用於各音軌的單獨試聽。
"""
import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal, QTimer


class TrackState:
    def __init__(self, name: str, audio: np.ndarray, sample_rate: int):
        self.name = name
        self.audio = audio          # float32, (samples, 2)
        self.sample_rate = sample_rate
        self.volume = 1.0           # 0.0 ~ 1.5
        self.muted = False
        self.solo = False

    @property
    def length(self):
        return len(self.audio)


class AudioEngine(QObject):
    """
    多軌同步播放引擎。
    用 sounddevice callback 即時混音，透過 QTimer 定期發送 position 更新。
    """
    position_changed = Signal(float)   # 0.0 ~ 1.0
    playback_stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tracks: list[TrackState] = []
        self.sample_rate = 44100
        self._position = 0          # in samples
        self._length = 0            # total samples
        self._stream: sd.OutputStream | None = None
        self._master_volume = 1.0
        self._playing = False

        self._speed = 1.0           # 播放速度倍率，1.0 = 原速
        self._pitch_board = None    # pedalboard.Pedalboard | None，即時移調

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._emit_position)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_tracks(self, tracks: list[TrackState]):
        self.stop()
        self.tracks = tracks
        if tracks:
            self.sample_rate = tracks[0].sample_rate
            self._length = max(t.length for t in tracks)
        self._position = 0

    @property
    def master_volume(self):
        return self._master_volume

    @master_volume.setter
    def master_volume(self, v: float):
        self._master_volume = max(0.0, min(2.0, v))

    @property
    def speed(self):
        return self._speed

    def set_speed(self, speed: float):
        """設定播放速度倍率。若正在播放，重新啟動串流套用。"""
        self._speed = max(0.25, min(4.0, speed))
        if self._playing:
            pos = self._position
            self.pause()
            self._position = pos
            self.play()

    def set_pitch_semitones(self, n: int):
        """設定移調半音數。即時生效，不重啟串流，callback 內每個 chunk 即時套用。"""
        import pedalboard
        if n == 0:
            self._pitch_board = None
        else:
            self._pitch_board = pedalboard.Pedalboard([pedalboard.PitchShift(semitones=n)])

    def get_position_ratio(self) -> float:
        if self._length == 0:
            return 0.0
        return self._position / self._length

    def seek(self, ratio: float):
        self._position = int(max(0.0, min(1.0, ratio)) * self._length)

    def play(self):
        if self._playing:
            return
        if self._position >= self._length:
            self._position = 0

        self._playing = True
        output_sr = int(self.sample_rate * self._speed)
        self._stream = sd.OutputStream(
            samplerate=output_sr,
            channels=2,
            dtype="float32",
            callback=self._callback,
            finished_callback=self._on_stream_finished,
            latency='low',
        )
        self._stream.start()
        self._timer.start()

    def pause(self):
        self._playing = False
        self._timer.stop()
        stream, self._stream = self._stream, None   # 原子性取走，避免 race condition
        if stream:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def stop(self):
        self.pause()
        self._position = 0
        self.position_changed.emit(0.0)

    def is_playing(self) -> bool:
        return self._playing

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _callback(self, outdata: np.ndarray, frames: int, time, status):
        mixed = np.zeros((frames, 2), dtype=np.float32)
        any_solo = any(t.solo for t in self.tracks)
        pos = self._position

        for track in self.tracks:
            if track.muted:
                continue
            if any_solo and not track.solo:
                continue

            end = pos + frames
            chunk = track.audio[pos:end]
            actual = len(chunk)

            if actual == 0:
                continue

            buf = np.zeros((frames, 2), dtype=np.float32)
            buf[:actual] = chunk
            mixed += buf * track.volume

        mixed *= self._master_volume
        np.clip(mixed, -1.0, 1.0, out=mixed)

        board = self._pitch_board
        if board is not None:
            # (frames, 2) → (2, frames) → pedalboard → (2, frames) → (frames, 2)
            mixed = board(mixed.T, self.sample_rate).T[:frames]
            np.clip(mixed, -1.0, 1.0, out=mixed)

        outdata[:] = mixed
        self._position += frames

        if self._position >= self._length:
            self._playing = False
            raise sd.CallbackStop()

    def _on_stream_finished(self):
        # 由 sounddevice 執行緒呼叫——只能 emit signal，不可碰 QTimer
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self, '_cleanup_after_finish', Qt.QueuedConnection)

    def _cleanup_after_finish(self):
        """排回主執行緒執行：停 timer、關 stream、發出訊號。"""
        self._timer.stop()
        stream, self._stream = self._stream, None
        if stream:
            try:
                stream.close()
            except Exception:
                pass
        self.position_changed.emit(min(1.0, self.get_position_ratio()))
        self.playback_stopped.emit()

    def _emit_position(self):
        self.position_changed.emit(self.get_position_ratio())


class SingleTrackPlayer(QObject):
    """獨立播放單一音軌（不走 M/S 邏輯）。"""
    playback_stopped = Signal()
    position_changed = Signal(float)   # 0.0 ~ 1.0，每 50ms 發出

    def __init__(self, parent=None):
        super().__init__(parent)
        self._track: TrackState | None = None
        self._stream: sd.OutputStream | None = None
        self._position = 0
        self._playing = False

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._emit_position)

    def load(self, track: TrackState):
        self.stop()
        self._track = track
        self._position = 0

    def get_position_ratio(self) -> float:
        if self._track is None or self._track.length == 0:
            return 0.0
        return self._position / self._track.length

    def seek(self, ratio: float):
        if self._track is not None:
            self._position = int(max(0.0, min(1.0, ratio)) * self._track.length)

    def play(self):
        if self._playing or self._track is None:
            return
        if self._position >= self._track.length:
            self._position = 0

        self._playing = True
        self._stream = sd.OutputStream(
            samplerate=self._track.sample_rate,
            channels=2,
            dtype="float32",
            callback=self._callback,
            finished_callback=self._on_finished,
            latency='low',
        )
        self._stream.start()
        self._timer.start()

    def stop(self):
        self._playing = False
        self._timer.stop()
        stream, self._stream = self._stream, None
        if stream:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._position = 0

    def is_playing(self) -> bool:
        return self._playing

    def _emit_position(self):
        self.position_changed.emit(self.get_position_ratio())

    def _callback(self, outdata: np.ndarray, frames: int, time, status):
        if self._track is None:
            outdata[:] = 0
            raise sd.CallbackStop()

        pos = self._position
        chunk = self._track.audio[pos:pos + frames]
        actual = len(chunk)

        buf = np.zeros((frames, 2), dtype=np.float32)
        if actual > 0:
            buf[:actual] = chunk
        buf *= self._track.volume

        np.clip(buf, -1.0, 1.0, out=buf)
        outdata[:] = buf
        self._position += frames

        if self._position >= self._track.length:
            self._playing = False
            raise sd.CallbackStop()

    def _on_finished(self):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self, '_cleanup_after_finish', Qt.QueuedConnection)

    def _cleanup_after_finish(self):
        self._timer.stop()
        stream, self._stream = self._stream, None
        if stream:
            try:
                stream.close()
            except Exception:
                pass
        self.position_changed.emit(self.get_position_ratio())
        self.playback_stopped.emit()
