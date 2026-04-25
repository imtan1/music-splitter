"""
調性偵測模組
對音頻做低通 500Hz 濾波後取 bass 頻段（40–500Hz）的 FFT chromagram，
再以 Krumhansl-Schmuckler 演算法比對大調／小調輪廓，回傳最符合的調性名稱。
"""
import numpy as np


def detect_key(mono: np.ndarray, sr: int) -> str:
    """
    Bass-weighted FFT chromagram + Krumhansl-Schmuckler 演算法偵測調性，純 numpy。
    低頻 40–500Hz 分析，bass 根音更能代表調性。
    """
    from scipy.signal import butter, filtfilt

    major_p = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_p = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    audio = mono.astype(np.float32)
    nyq = sr / 2
    b, a = butter(4, min(500.0 / nyq, 0.99), btype='low')
    audio = filtfilt(b, a, audio).astype(np.float32)

    win = 8192
    hop = 4096
    window = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    valid = (freqs >= 40.0) & (freqs <= 500.0)
    midi_f = 12.0 * np.log2(np.maximum(freqs[valid], 1e-9) / 440.0) + 69.0
    pc = np.round(midi_f).astype(int) % 12

    chroma = np.zeros(12, dtype=np.float64)
    n_frames = max(1, (len(audio) - win) // hop)
    for i in range(n_frames):
        frame = audio[i * hop: i * hop + win]
        if len(frame) < win:
            break
        spectrum = np.abs(np.fft.rfft(frame * window))[valid]
        np.add.at(chroma, pc, spectrum)

    if chroma.sum() > 0:
        chroma /= chroma.sum()

    major_names = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    minor_roots = {0: 'Cm', 2: 'Dm', 4: 'Em', 5: 'Fm', 7: 'Gm', 9: 'Am', 11: 'Bm'}

    best_score, best_key = -np.inf, 'C'
    for root in range(12):
        maj = float(np.corrcoef(chroma, np.roll(major_p, root))[0, 1])
        if maj > best_score:
            best_score, best_key = maj, major_names[root]
        if root in minor_roots:
            mn = float(np.corrcoef(chroma, np.roll(minor_p, root))[0, 1])
            if mn > best_score:
                best_score, best_key = mn, minor_roots[root]

    return best_key
