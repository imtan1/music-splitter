import numpy as np


def detect_bpm(mono: np.ndarray, sr: int, default: float = 120.0) -> float:
    """
    低頻 RMS flux + Fourier tempogram 估 BPM。
    低通 300Hz 後分析，避免人聲/旋律干擾節拍偵測。
    支援低速倍頻修正（b < 60 → ×2）與高速減半修正（b > 140 → ÷2）。
    """
    from scipy.signal import butter, filtfilt, find_peaks

    try:
        b, a = butter(4, min(300.0 / (sr / 2), 0.99), btype='low')
        low = filtfilt(b, a, mono).astype(np.float32)
    except Exception:
        low = mono.astype(np.float32)

    HOP = 512
    n = len(low) // HOP
    if n < 8:
        return default

    frames = low[:n * HOP].reshape(n, HOP)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    flux = np.maximum(np.diff(rms), 0).astype(np.float32)
    if flux.std() < 1e-8:
        return default

    onset_sr = sr / HOP
    F = np.abs(np.fft.rfft(flux, n=len(flux) * 8))
    bpm_arr = np.fft.rfftfreq(len(flux) * 8, d=1.0 / onset_sr) * 60.0
    mask = (bpm_arr >= 40) & (bpm_arr <= 180)
    F_m, b_m = F[mask], bpm_arr[mask]
    if len(F_m) == 0:
        return default

    peaks, _ = find_peaks(F_m, height=F_m.max() * 0.25)
    if len(peaks) == 0:
        peaks = [int(np.argmax(F_m))]

    candidates = sorted(zip(F_m[peaks], b_m[peaks]), reverse=True)
    for _, bv in candidates:
        if bv > 140:
            bv = bv / 2
        elif bv < 60:
            bv = bv * 2
        if 50 <= bv <= 160:
            return float(bv)
    return default


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
