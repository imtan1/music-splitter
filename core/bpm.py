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
