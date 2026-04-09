import numpy as np
from core.player import TrackState


def mix_tracks(tracks: list[TrackState], master_volume: float = 1.0) -> tuple[np.ndarray, int]:
    """
    依照各音軌的 volume / muted 狀態混音，回傳 (audio_np, sample_rate)。
    Solo 邏輯：若有任何軌 solo，只混 solo 的軌。
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

    mixed *= master_volume
    np.clip(mixed, -1.0, 1.0, out=mixed)
    return mixed, sr


def mix_single_track(track: TrackState) -> tuple[np.ndarray, int]:
    """單一音軌套用音量後輸出。"""
    audio = track.audio * track.volume
    np.clip(audio, -1.0, 1.0, out=audio)
    return audio.astype(np.float32), track.sample_rate
