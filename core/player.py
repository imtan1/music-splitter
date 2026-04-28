"""
音頻播放引擎
AudioEngine：多軌同步播放，支援靜音、獨奏、音量、播放速度與移調倍率，低延遲 sounddevice callback 混音。
SingleTrackPlayer：單軌獨立播放，用於各音軌的單獨試聽。
"""
import math
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
        self.use_librosa_pitch: bool = False  # True = 使用 librosa HQ（較快）
        self._orig_audios: dict[int, np.ndarray] = {}   # track index → 原始音頻
        self._hq_process_start: int = 0  # position where HQ processing started
        self._hq_end: int = 0            # min of per-track hq_ends (callback boundary)
        self._hq_ends: list[int] = []    # per-track HQ progress

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
        self._hq_process_start = 0
        self._hq_end = 0
        self._hq_ends = []
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
        兩段式分批移調：
        1. 立刻建立 StreamingPitchShifter 提供即時（低品質）預覽
        2. 背景每 20 秒一塊順序處理（每塊內各軌平行），逐塊寫入 track.audio
        """
        self._pitch_n = n
        self._hq_process_start = 0
        self._hq_end = 0

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
            # 每次換調建立可寫入的副本，供背景逐塊 in-place 寫入 HQ 結果
            track.audio = self._orig_audios[i].copy()

        process_start = self._position
        self._hq_process_start = process_start
        self._hq_end = process_start
        self._hq_ends = [process_start] * len(self.tracks)

        # 即時預覽（在 HQ 尚未覆蓋的區段使用）
        self._pitch_shifter = StreamingPitchShifter(n)

        n_tracks = len(self.tracks)
        remaining_sec = (self._length - process_start) / self.sample_rate if self._length > 0 else 0
        print(f"[pitch] 開始移調 {n:+d} 半音，{n_tracks} 軌，"
              f"從 {process_start/self.sample_rate:.1f}s 起，剩餘 {remaining_sec:.1f}s 需處理")
        self.pitch_processing_changed.emit(True)
        t0 = time.perf_counter()
        bg_fn = self._bg_pitch_librosa if self.use_librosa_pitch else self._bg_pitch
        threading.Thread(target=bg_fn, args=(n, t0, process_start), daemon=True).start()

    def _bg_pitch(self, n: int, t0: float, process_start: int):
        """
        背景執行緒：每軌各自一條執行緒，各自依序處理所有區塊。
        _hq_end = min(per-track hq_ends)，callback 以此為 HQ/PV 切換邊界。
        """
        try:
            from pedalboard import Pedalboard, PitchShift
            sr = self.sample_rate
            SMALL_SEC  = 2
            SMALL_SECS = 18
            LARGE_SEC  = 20

            chunks: list[tuple[int, int]] = []
            pos = process_start
            small_boundary = process_start + SMALL_SECS * sr
            while pos < min(small_boundary, self._length):
                end = min(pos + SMALL_SEC * sr, small_boundary, self._length)
                chunks.append((pos, end))
                pos = end
            while pos < self._length:
                end = min(pos + LARGE_SEC * sr, self._length)
                chunks.append((pos, end))
                pos = end
            n_chunks = len(chunks)
            print(f"[pitch] 共 {n_chunks} 塊（前 {SMALL_SECS}s 每塊 {SMALL_SEC}s，"
                  f"之後每塊 {LARGE_SEC}s），各軌獨立執行緒")

            def _process_track(track_idx: int, track):
                orig = self._orig_audios.get(track_idx)
                for chunk_idx, (c_start, c_end) in enumerate(chunks):
                    if self._pitch_n != n:
                        return
                    try:
                        if orig is None:
                            self._hq_ends[track_idx] = c_end
                            self._hq_end = min(self._hq_ends)
                            continue

                        part = orig[c_start:c_end].astype(np.float32)
                        if float(np.sqrt(np.mean(part ** 2))) < 1e-4:
                            print(f"[pitch] 軌{track_idx} chunk {chunk_idx+1}/{n_chunks} 靜音，跳過")
                            track.audio[c_start:c_end] = part
                        else:
                            t_chunk = time.perf_counter()
                            b = Pedalboard([PitchShift(semitones=float(n))])
                            shifted = b(part.T, sr).T.astype(np.float32)
                            expected = c_end - c_start
                            if len(shifted) > expected:
                                shifted = shifted[:expected]
                            elif len(shifted) < expected:
                                pad = np.zeros((expected - len(shifted), 2), dtype=np.float32)
                                shifted = np.concatenate([shifted, pad])
                            track.audio[c_start:c_end] = shifted
                            elapsed = time.perf_counter() - t_chunk
                            print(f"[pitch] 軌{track_idx} chunk {chunk_idx+1}/{n_chunks}: "
                                  f"{c_start/sr:.1f}s–{c_end/sr:.1f}s 完成，耗時 {elapsed:.2f}s")
                    except Exception as e:
                        print(f"[pitch bg 軌{track_idx} chunk {chunk_idx+1}]: {e}")
                        if orig is not None:
                            track.audio[c_start:c_end] = orig[c_start:c_end]

                    self._hq_ends[track_idx] = c_end
                    self._hq_end = min(self._hq_ends)

            threads = [threading.Thread(target=_process_track, args=(i, t), daemon=True)
                       for i, t in enumerate(self.tracks)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if self._pitch_n != n:
                print(f"[pitch] 已中途取消")
                return

            total_elapsed = time.perf_counter() - t0
            print(f"[pitch] 全部完成，總耗時 {total_elapsed:.2f}s")
            QMetaObject.invokeMethod(self, '_on_bg_pitch_done', Qt.ConnectionType.QueuedConnection)
        except Exception as e:
            total_elapsed = time.perf_counter() - t0
            print(f"[pitch bg] error（耗時 {total_elapsed:.2f}s）: {e}")
            if self._pitch_n == n:
                QMetaObject.invokeMethod(self, '_on_bg_pitch_done', Qt.ConnectionType.QueuedConnection)

    def _bg_pitch_librosa(self, n: int, t0: float, process_start: int):
        """
        背景執行緒（librosa 版）：phase vocoder 移調，速度比 RubberBand 快 5-10 倍。
        結構與 _bg_pitch 完全一致，僅移調演算法不同。
        """
        try:
            import librosa
            sr = self.sample_rate
            SMALL_SEC  = 2
            SMALL_SECS = 18
            LARGE_SEC  = 20

            chunks: list[tuple[int, int]] = []
            pos = process_start
            small_boundary = process_start + SMALL_SECS * sr
            while pos < min(small_boundary, self._length):
                end = min(pos + SMALL_SEC * sr, small_boundary, self._length)
                chunks.append((pos, end))
                pos = end
            while pos < self._length:
                end = min(pos + LARGE_SEC * sr, self._length)
                chunks.append((pos, end))
                pos = end
            n_chunks = len(chunks)
            print(f"[pitch-librosa] 共 {n_chunks} 塊，各軌獨立執行緒")

            def _process_track(track_idx: int, track):
                orig = self._orig_audios.get(track_idx)
                for chunk_idx, (c_start, c_end) in enumerate(chunks):
                    if self._pitch_n != n:
                        return
                    try:
                        if orig is None:
                            self._hq_ends[track_idx] = c_end
                            self._hq_end = min(self._hq_ends)
                            continue

                        part = orig[c_start:c_end].astype(np.float32)
                        if float(np.sqrt(np.mean(part ** 2))) < 1e-4:
                            print(f"[pitch-librosa] 軌{track_idx} chunk {chunk_idx+1}/{n_chunks} 靜音，跳過")
                            track.audio[c_start:c_end] = part
                        else:
                            t_chunk = time.perf_counter()
                            ch0 = librosa.effects.pitch_shift(
                                part[:, 0], sr=sr, n_steps=float(n), res_type='kaiser_fast')
                            ch1 = librosa.effects.pitch_shift(
                                part[:, 1], sr=sr, n_steps=float(n), res_type='kaiser_fast')
                            shifted = np.column_stack([ch0, ch1]).astype(np.float32)
                            expected = c_end - c_start
                            if len(shifted) > expected:
                                shifted = shifted[:expected]
                            elif len(shifted) < expected:
                                pad = np.zeros((expected - len(shifted), 2), dtype=np.float32)
                                shifted = np.concatenate([shifted, pad])
                            track.audio[c_start:c_end] = shifted
                            elapsed = time.perf_counter() - t_chunk
                            print(f"[pitch-librosa] 軌{track_idx} chunk {chunk_idx+1}/{n_chunks}: "
                                  f"{c_start/sr:.1f}s–{c_end/sr:.1f}s 完成，耗時 {elapsed:.2f}s")
                    except Exception as e:
                        print(f"[pitch-librosa bg 軌{track_idx} chunk {chunk_idx+1}]: {e}")
                        if orig is not None:
                            track.audio[c_start:c_end] = orig[c_start:c_end]

                    self._hq_ends[track_idx] = c_end
                    self._hq_end = min(self._hq_ends)

            threads = [threading.Thread(target=_process_track, args=(i, t), daemon=True)
                       for i, t in enumerate(self.tracks)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if self._pitch_n != n:
                print(f"[pitch-librosa] 已中途取消")
                return

            total_elapsed = time.perf_counter() - t0
            print(f"[pitch-librosa] 全部完成，總耗時 {total_elapsed:.2f}s")
            QMetaObject.invokeMethod(self, '_on_bg_pitch_done', Qt.ConnectionType.QueuedConnection)
        except Exception as e:
            total_elapsed = time.perf_counter() - t0
            print(f"[pitch-librosa bg] error（耗時 {total_elapsed:.2f}s）: {e}")
            if self._pitch_n == n:
                QMetaObject.invokeMethod(self, '_on_bg_pitch_done', Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _on_bg_pitch_done(self):
        self._pitch_shifter = None   # 全部 HQ，不再需要即時預覽
        self.pitch_processing_changed.emit(False)

    def get_export_audio(self, track_idx: int) -> np.ndarray:
        """Return audio for export. Waits for background HQ processing to finish if needed."""
        while self._pitch_shifter is not None:
            time.sleep(0.05)
        return self.tracks[track_idx].audio

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
        mixed = np.zeros((frames, 2), dtype=np.float32)
        any_solo = any(t.solo for t in self.tracks)
        pos = self._position
        hq_end = self._hq_end   # snapshot：HQ 已覆蓋到此位置

        for i, track in enumerate(self.tracks):
            if track.muted:
                continue
            if any_solo and not track.solo:
                continue

            end = pos + frames
            if pos < hq_end:
                # 所有軌均已 HQ，直接讀 track.audio
                chunk = track.audio[pos:end]
            else:
                # 非 HQ 區段：讀原始音頻交給 PV，避免進度較快的軌被二次移調
                orig = self._orig_audios.get(i)
                chunk = orig[pos:end] if orig is not None else track.audio[pos:end]
            actual = len(chunk)

            if actual == 0:
                continue

            buf = np.zeros((frames, 2), dtype=np.float32)
            buf[:actual] = chunk
            mixed += buf * track.volume

        mixed *= self._master_volume
        np.clip(mixed, -1.0, 1.0, out=mixed)

        # 只在尚未 HQ 覆蓋的區段套用即時 PV 預覽
        shifter = self._pitch_shifter
        if shifter is not None and pos >= hq_end:
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

    @Slot()
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
