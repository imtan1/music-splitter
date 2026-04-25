"""
即時移調模組
StreamingPitchShifter：相位聲碼器，維護跨 chunk 的分析/合成相位狀態，
確保任意 chunk 大小下的相位連續性，不依賴外部串流 API。
"""
import numpy as np


class StreamingPitchShifter:
    """
    無狀態重置的串流相位聲碼器。
    - N_FFT=2048 / HOP=512：46ms 視窗，瞬態模糊遠低於 4096 的 93ms
    - 線性插值：分析 bin 分散到相鄰兩個合成 bin，消除頻譜空洞
    - 加權平均頻率：避免多個 bin 疊加時合成相位累積錯誤
    - Identity phase locking：非峰值 bin 相位鎖定到最近峰值，減少金屬感
    """
    N_FFT = 2048
    HOP   = N_FFT // 4   # 512，75% overlap

    def __init__(self, n_steps: float):
        self.ratio = 2.0 ** (n_steps / 12.0)
        bins = self.N_FFT // 2 + 1

        self._win   = np.sqrt(np.hanning(self.N_FFT))
        self._omega = 2.0 * np.pi * np.arange(bins) * self.HOP / self.N_FFT

        # 每聲道狀態
        self._phi_a   = np.zeros((2, bins))
        self._phi_s   = np.zeros((2, bins))
        self._in_buf  = np.zeros((2, self.N_FFT))
        self._out_acc = np.zeros((2, self.N_FFT + self.HOP * 8))

    # ------------------------------------------------------------------

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        audio: (frames, 2) float32，frames 需為 HOP 的整數倍。
        傳回同形狀的移調音頻。
        """
        n = len(audio)
        n_hops = n // self.HOP
        result = np.zeros((n, 2), dtype=np.float32)

        for h in range(n_hops):
            sl = slice(h * self.HOP, (h + 1) * self.HOP)
            chunk = audio[sl].astype(np.float64)

            for c in range(2):
                self._in_buf[c, :-self.HOP] = self._in_buf[c, self.HOP:]
                self._in_buf[c, -self.HOP:] = chunk[:, c]

                out_frame = self._pv_frame(c)

                self._out_acc[c, :self.N_FFT] += out_frame
                result[sl, c] = self._out_acc[c, :self.HOP]
                self._out_acc[c, :-self.HOP] = self._out_acc[c, self.HOP:]
                self._out_acc[c, -self.HOP:] = 0.0

        return result.astype(np.float32)

    # ------------------------------------------------------------------

    def _pv_frame(self, c: int) -> np.ndarray:
        frame = self._in_buf[c] * self._win
        spec  = np.fft.rfft(frame)
        mag   = np.abs(spec)
        phi   = np.angle(spec)
        bins  = len(mag)

        # 真實瞬時頻率
        dphi = phi - self._phi_a[c] - self._omega
        dphi -= np.round(dphi / (2.0 * np.pi)) * 2.0 * np.pi
        self._phi_a[c] = phi
        true_freq = self._omega + dphi / self.HOP

        # 線性插值 bin 映射：消除頻譜空洞
        k       = np.arange(bins, dtype=float)
        k_shift = k * self.ratio
        k_lo    = np.clip(k_shift.astype(int), 0, bins - 1)
        k_hi    = np.clip(k_lo + 1,            0, bins - 1)
        frac    = k_shift - np.floor(k_shift)

        w_lo = mag * (1.0 - frac)
        w_hi = mag * frac

        new_mag = np.zeros(bins)
        new_tf  = np.zeros(bins)
        np.add.at(new_mag, k_lo, w_lo)
        np.add.at(new_mag, k_hi, w_hi)
        # 合成頻率以幅度加權，避免多 bin 疊加時相位偏移
        np.add.at(new_tf, k_lo, w_lo * true_freq * self.ratio)
        np.add.at(new_tf, k_hi, w_hi * true_freq * self.ratio)

        safe_mag = np.where(new_mag > 1e-12, new_mag, 1.0)
        new_tf  /= safe_mag   # 加權平均

        # 合成相位累積（所有 bin）
        self._phi_s[c] += new_tf * self.HOP

        # Identity phase locking：非峰值 bin 鎖定到最近峰值，保留和聲相位關係
        is_peak = np.zeros(bins, dtype=bool)
        if bins > 2:
            is_peak[1:-1] = (new_mag[1:-1] > new_mag[:-2]) & (new_mag[1:-1] > new_mag[2:])
        is_peak[0] = is_peak[-1] = True

        peak_idx = np.where(is_peak)[0]
        if len(peak_idx) > 1:
            all_k  = np.arange(bins)
            ins    = np.searchsorted(peak_idx, all_k)
            left   = np.clip(ins - 1, 0, len(peak_idx) - 1)
            right  = np.clip(ins,     0, len(peak_idx) - 1)
            dist_l = all_k - peak_idx[left]
            dist_r = peak_idx[right] - all_k
            nearest = np.where(dist_l <= dist_r, left, right)
            p_bin   = peak_idx[nearest]   # 各 bin 最近的峰值 bin

            # 反映射到 analysis 空間，取得對應的 analysis phase
            k_a = np.clip((all_k / self.ratio).astype(int), 0, bins - 1)
            p_a = np.clip((p_bin / self.ratio).astype(int), 0, bins - 1)

            non_peak = ~is_peak
            self._phi_s[c][non_peak] = (
                self._phi_s[c][p_bin[non_peak]]
                + phi[k_a[non_peak]]
                - phi[p_a[non_peak]]
            )

        out_spec  = new_mag * np.exp(1j * self._phi_s[c])
        out_frame = np.fft.irfft(out_spec).real * self._win
        # hanning 75% overlap COLA sum = 2.0，正規化係數 = 0.5
        return out_frame * (self.HOP / self.N_FFT * 2.0)
