"""
MIDI 合成器
將 JianpuNote 列表用三角波合成為可播放的 float32 音頻。
"""
import numpy as np
from core.transcriber import JianpuNote, NOTE_PC, MAJOR_SCALE, MINOR_SCALE


def jianpu_to_midi_pitch(jn: JianpuNote, root_pc: int, scale: list) -> int:
    degree = int(jn.num) - 1
    ref_tonic = 60 + root_pc
    return ref_tonic + scale[degree] + jn.octave * 12


def synthesize(notes: list, tempo: float, key_name: str, sr: int = 44100) -> np.ndarray:
    """
    將 JianpuNote 列表合成為 float32 mono 音頻陣列。
    使用三角波（比正弦波豐富、比方波柔和）。
    """
    is_minor = key_name.endswith('m')
    root_pc = NOTE_PC.get(key_name.rstrip('m'), 0)
    scale = MINOR_SCALE if is_minor else MAJOR_SCALE
    beat_dur = 60.0 / tempo

    segments = []
    for jn in notes:
        dur_sec = max(0.05, jn.beats * beat_dur)
        n_samples = int(dur_sec * sr)

        if jn.num == '0':
            segments.append(np.zeros(n_samples, dtype=np.float32))
            continue

        midi = jianpu_to_midi_pitch(jn, root_pc, scale)
        freq = 440.0 * 2.0 ** ((midi - 69) / 12.0)

        t = np.linspace(0, dur_sec, n_samples, endpoint=False)
        # 三角波：2 * |2 * frac(f*t + 0.25) - 1| - 1  (對稱三角)
        phase = freq * t
        wave = 2.0 * np.abs(2.0 * (phase - np.floor(phase + 0.5))) - 1.0
        wave = wave.astype(np.float32) * 0.22

        # 包絡：attack 15ms、release 30% of note
        env = np.ones(n_samples, dtype=np.float32)
        attack = min(int(0.015 * sr), n_samples // 4)
        release = min(int(0.30 * dur_sec * sr), n_samples // 2)
        if attack > 0:
            env[:attack] = np.linspace(0.0, 1.0, attack, dtype=np.float32)
        if release > 0:
            env[-release:] = np.linspace(1.0, 0.0, release, dtype=np.float32)

        segments.append(wave * env)

    if not segments:
        return np.zeros(sr, dtype=np.float32)

    audio = np.concatenate(segments)
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.80
    return audio
