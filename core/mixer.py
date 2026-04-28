"""
混音模組
依各軌的靜音、獨奏、音量狀態將多條 TrackState 混合為單一立體聲音頻，用於匯出混音 MP3。
"""
import numpy as np
from core.player import TrackState


def _resample(audio: np.ndarray, speed: float) -> np.ndarray:
    """以速度倍率對音頻做時間軸重採樣（兩聲道）。"""
    target_len = max(1, int(len(audio) / speed))
    x_old = np.linspace(0.0, 1.0, len(audio))
    x_new = np.linspace(0.0, 1.0, target_len)
    ch0 = np.interp(x_new, x_old, audio[:, 0]).astype(np.float32)
    ch1 = np.interp(x_new, x_old, audio[:, 1]).astype(np.float32)
    return np.column_stack([ch0, ch1])


def mix_tracks(
    tracks: list[TrackState],
    master_volume: float = 1.0,
    speed: float = 1.0,
    metronome_track: TrackState | None = None,
) -> tuple[np.ndarray, int]:
    """
    依照各音軌的 volume / muted / solo 狀態混音。
    - speed：播放速度倍率，!=1.0 時重採樣輸出
    - metronome_track：節拍器音軌，未靜音時混入
    回傳 (audio_np, sample_rate)。
    """
    if not tracks:
        return np.zeros((0, 2), dtype=np.float32), 44100

    sr = tracks[0].sample_rate
    length = max(t.length for t in tracks)
    mixed = np.zeros((length, 2), dtype=np.float32)

    any_solo = any(t.solo for t in tracks)

    for track in tracks:
        if track.muted:
            continue
        if any_solo and not track.solo:
            continue
        buf = np.zeros((length, 2), dtype=np.float32)
        buf[:track.length] = track.audio
        mixed += buf * track.volume

    # 節拍器（未靜音則混入）
    if metronome_track is not None and not metronome_track.muted:
        buf = np.zeros((length, 2), dtype=np.float32)
        buf[:metronome_track.length] = metronome_track.audio
        mixed += buf * metronome_track.volume

    mixed *= master_volume
    np.clip(mixed, -1.0, 1.0, out=mixed)

    # 速度重採樣
    if abs(speed - 1.0) > 0.005:
        mixed = _resample(mixed, speed)

    return mixed.astype(np.float32), sr


def mix_single_track(track: TrackState, speed: float = 1.0) -> tuple[np.ndarray, int]:
    """單一音軌套用音量與速度後輸出。"""
    audio = (track.audio * track.volume).astype(np.float32)
    np.clip(audio, -1.0, 1.0, out=audio)
    if abs(speed - 1.0) > 0.005:
        audio = _resample(audio, speed)
    return audio, track.sample_rate
