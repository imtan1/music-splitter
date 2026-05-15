"""
BPM（節拍速度）偵測模組
主要：librosa beat_track（dynamic programming + autocorrelation，倍頻問題更穩健）
備用：自製低通 RMS flux + Fourier tempogram（librosa 失敗時自動 fallback）
"""
import numpy as np


def detect_bpm(mono: np.ndarray, sr: int, default: float = 120.0) -> tuple[float, np.ndarray]:
    """
    librosa beat_track 偵測 BPM，失敗時 fallback 到自製 Fourier tempogram。
    回傳 (bpm, beat_times)；fallback 路徑無法產生可靠 beat_times，回傳空陣列。
    """
    try:
        import librosa
        tempo, beats = librosa.beat.beat_track(y=mono, sr=sr)
        bv = float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo)
        if 40.0 <= bv <= 220.0:
            beat_times = librosa.frames_to_time(beats, sr=sr)
            beat_times = _smooth_beat_times(beat_times)
            return bv, beat_times
    except Exception as e:
        print(f"[bpm] librosa beat_track 失敗，改用 fallback：{e}")

    return _detect_bpm_fallback(mono, sr, default), np.array([], dtype=np.float64)


def _smooth_beat_times(beat_times: np.ndarray) -> np.ndarray:
    """
    對 beat_times 做後處理，消除 librosa beat_track 的局部誤差。
    找出偏離 median ±15% 的異常間距，擴展到鄰近正常錨點，用等間距線性插值修正。
    錨點（擴展後的邊界拍）本身不動，只重新分配中間各拍的位置。
    """
    if len(beat_times) < 4:
        return beat_times

    intervals = np.diff(beat_times)
    median_iv = float(np.median(intervals))
    lower = median_iv * 0.85
    upper = median_iv * 1.15

    anomalous = (intervals < lower) | (intervals > upper)
    if not anomalous.any():
        return beat_times

    result = beat_times.astype(np.float64).copy()
    n = len(result)

    i = 0
    while i < len(intervals):
        if not anomalous[i]:
            i += 1
            continue
        # 找出連續異常間距的結尾 index j
        j = i
        while j + 1 < len(intervals) and anomalous[j + 1]:
            j += 1
        # 向外各擴一拍，取得兩端錨點
        left_anchor  = max(0, i - 1)
        right_anchor = min(n - 1, j + 2)
        n_ivs = right_anchor - left_anchor
        if n_ivs >= 2:
            t_start = result[left_anchor]
            t_end   = result[right_anchor]
            eq_iv   = (t_end - t_start) / n_ivs
            for k in range(left_anchor + 1, right_anchor):
                result[k] = round(t_start + (k - left_anchor) * eq_iv, 4)
        i = j + 1

    return result


def _detect_bpm_fallback(mono: np.ndarray, sr: int, default: float = 120.0) -> float:
    """
    備用：低頻 RMS flux + Fourier tempogram 估 BPM。
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
