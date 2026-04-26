"""
音頻播放引擎
AudioEngine：多軌同步播放，支援靜音、獨奏、音量、播放速度與移調倍率，低延遲 sounddevice callback 混音。
SingleTrackPlayer：單軌獨立播放，用於各音軌的單獨試聽。
"""
import time
import threading
import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal, QTimer, Slot, Qt, QMetaObject
from core.pitch import StreamingPitchShifter


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
    pitch_processing_changed = Signal(bool)   # True=背景處理中, False=完成

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
        self._pitch_shifter: StreamingPitchShifter | None = None
        self._pitch_n: int = 0
        self._orig_audios: dict[int, np.ndarray] = {}   # track index → 原始音頻
        self._pending_switch: list[np.ndarray] | None = None  # 離線處理完成後的原子切換

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._emit_position)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_tracks(self, tracks: list[TrackState]):
        self.stop()
        self._pitch_n = 0
        self._pitch_shifter = None
        self._orig_audios.clear()
        self._pending_switch = None
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
        """
        兩段式移調：
        1. 立刻建立 StreamingPitchShifter 提供即時（低品質）預覽
        2. 同步在背景用 pedalboard RubberBand 做高品質離線處理，完成後自動切換
        """
        self._pitch_n = n
        self._pending_switch = None         # 取消未生效的上一次切換

        if n == 0:
            self._pitch_shifter = None
            for i, track in enumerate(self.tracks):
                if i in self._orig_audios:
                    track.audio = self._orig_audios[i]
            self.pitch_processing_changed.emit(False)
            return

        # 保存原始音頻（只在第一次換調時儲存）
        for i, track in enumerate(self.tracks):
            if i not in self._orig_audios:
                self._orig_audios[i] = track.audio
            # 確保 track.audio 指向原始版（避免前次處理結果被再次移調）
            track.audio = self._orig_audios[i]

        # 即時預覽
        self._pitch_shifter = StreamingPitchShifter(n)

        # 背景高品質處理：只從當前播放位置往後處理，縮短處理量
        t0 = time.perf_counter()
        process_start = self._position
        n_tracks = len(self.tracks)
        remaining_sec = (self._length - process_start) / self.sample_rate if self._length > 0 else 0
        print(f"[pitch] 開始移調 {n:+d} 半音，{n_tracks} 軌，"
              f"從 {process_start/self.sample_rate:.1f}s 起，剩餘 {remaining_sec:.1f}s 需處理")
        self.pitch_processing_changed.emit(True)
        threading.Thread(target=self._bg_pitch, args=(n, t0, process_start), daemon=True).start()

    def _bg_pitch(self, n: int, t0: float, process_start: int):
        """
        背景執行緒：每軌獨立 Pedalboard（RubberBand，高品質），平行處理。
        只處理 process_start 之後的音頻，縮短等待時間。
        """
        try:
            from pedalboard import Pedalboard, PitchShift
            sr = self.sample_rate
            n_tracks = len(self.tracks)
            new_audios: list[np.ndarray | None] = [None] * n_tracks

            def _process_one(i: int, track):
                if self._pitch_n != n:
                    return
                orig = self._orig_audios.get(i)
                if orig is None:
                    new_audios[i] = track.audio
                    return
                try:
                    t_track = time.perf_counter()
                    b = Pedalboard([PitchShift(semitones=float(n))])
                    part = orig[process_start:].T.astype(np.float32)
                    shifted_part = b(part, sr).T.astype(np.float32)

                    # 長度修正（pedalboard 可能多或少幾個 sample）
                    expected = len(orig) - process_start
                    if len(shifted_part) > expected:
                        shifted_part = shifted_part[:expected]
                    elif len(shifted_part) < expected:
                        pad = np.zeros((expected - len(shifted_part), 2), dtype=np.float32)
                        shifted_part = np.concatenate([shifted_part, pad])

                    elapsed = time.perf_counter() - t_track
                    print(f"[pitch]   軌{i} 完成，耗時 {elapsed:.2f}s")
                    if self._pitch_n == n:
                        # 前段保留原音（不影響已播過的部分），後段換 HQ
                        full = np.concatenate([orig[:process_start], shifted_part], axis=0)
                        new_audios[i] = full.astype(np.float32)
                except Exception as e:
                    print(f"[pitch bg track {i}]: {e}")
                    new_audios[i] = orig

            threads = [threading.Thread(target=_process_one, args=(i, t), daemon=True)
                       for i, t in enumerate(self.tracks)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if self._pitch_n != n:
                print(f"[pitch] 已中途取消（使用者換調）")
                return

            if all(a is not None for a in new_audios):
                self._pending_switch = new_audios  # type: ignore[assignment]
                total_elapsed = time.perf_counter() - t0
                print(f"[pitch] 全部完成，總耗時 {total_elapsed:.2f}s，切換至高品質版本")
                QMetaObject.invokeMethod(self, '_on_bg_pitch_done', Qt.ConnectionType.QueuedConnection)
        except Exception as e:
            total_elapsed = time.perf_counter() - t0
            print(f"[pitch bg] error（耗時 {total_elapsed:.2f}s）: {e}")
            if self._pitch_n == n:
                QMetaObject.invokeMethod(self, '_on_bg_pitch_done', Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _on_bg_pitch_done(self):
        self.pitch_processing_changed.emit(False)


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
            blocksize=4096,     # pedalboard PitchShift 需要夠大的 chunk 才能正確運作
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
        # 離線移調完成 → 原子切換 track.audio + 停用即時預覽
        switch = self._pending_switch
        if switch is not None:
            self._pending_switch = None
            self._pitch_shifter = None
            for track, new_audio in zip(self.tracks, switch):
                track.audio = new_audio

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

        shifter = self._pitch_shifter
        if shifter is not None:
            mixed = shifter.process(mixed)
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
