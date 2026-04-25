"""
即時移調模組
StreamingPitchShifter：相位聲碼器，維護跨 chunk 的分析/合成相位狀態，
確保任意 chunk 大小下的相位連續性，不依賴外部串流 API。
"""
import numpy as np


class StreamingPitchShifter:
    """
    無狀態重置的串流相位聲碼器。
    每次 process() 呼叫維護 phi_a（分析相位）與 phi_s（合成相位累積器），
    chunk 邊界相位連續，無點擊聲。
    """
    N_FFT = 2048
    HOP   = N_FFT // 4   # 512，75% overlap → 4x

    def __init__(self, n_steps: float):
        self.ratio = 2.0 ** (n_steps / 12.0)
        bins = self.N_FFT // 2 + 1

        self._win   = np.sqrt(np.hanning(self.N_FFT))
        # 每個頻率 bin 每 HOP 樣本的預期相位推進量
        self._omega = 2.0 * np.pi * np.arange(bins) * self.HOP / self.N_FFT

        # 每聲道狀態
        self._phi_a   = np.zeros((2, bins))              # 前一幀的分析相位
        self._phi_s   = np.zeros((2, bins))              # 合成相位累積器
        self._in_buf  = np.zeros((2, self.N_FFT))        # 滾動分析窗
        self._out_acc = np.zeros((2, self.N_FFT + self.HOP * 8))  # OLA 累積器

    # ------------------------------------------------------------------

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        audio: (frames, 2) float32
        傳回同形狀的移調音頻；輸入長度需為 HOP 的整數倍。
        """
        n = len(audio)
        n_hops = n // self.HOP
        result = np.zeros((n, 2), dtype=np.float32)

        for h in range(n_hops):
            sl = slice(h * self.HOP, (h + 1) * self.HOP)
            chunk = audio[sl].astype(np.float64)

            for c in range(2):
                # 滑動輸入窗
                self._in_buf[c, :-self.HOP] = self._in_buf[c, self.HOP:]
                self._in_buf[c, -self.HOP:] = chunk[:, c]

                # 分析 → 移調 → 合成
                out_frame = self._pv_frame(c)

                # OLA 累積
                self._out_acc[c, :self.N_FFT] += out_frame

                # 取出一個 HOP 的輸出
                result[sl, c] = self._out_acc[c, :self.HOP]

                # 推進 OLA 緩衝
                self._out_acc[c, :-self.HOP] = self._out_acc[c, self.HOP:]
                self._out_acc[c, -self.HOP:] = 0.0

        return result

    # ------------------------------------------------------------------

    def _pv_frame(self, c: int) -> np.ndarray:
        """對聲道 c 的當前輸入窗做一幀分析-合成。"""
        frame = self._in_buf[c] * self._win
        spec  = np.fft.rfft(frame)
        mag   = np.abs(spec)
        phi   = np.angle(spec)
        bins  = len(mag)

        # 真實瞬時頻率（解包相位差）
        dphi = phi - self._phi_a[c] - self._omega
        dphi -= np.round(dphi / (2.0 * np.pi)) * 2.0 * np.pi
        self._phi_a[c] = phi
        true_freq = self._omega + dphi / self.HOP

        # Bin 重映射（音高移調）
        k  = np.arange(bins)
        k2 = np.clip((k * self.ratio).astype(int), 0, bins - 1)
        new_mag = np.zeros(bins)
        new_tf  = np.zeros(bins)
        np.add.at(new_mag, k2, mag)
        np.add.at(new_tf,  k2, true_freq * self.ratio)

        # 合成相位累積
        self._phi_s[c] += new_tf * self.HOP

        # IFFT 合成幀，乘分析/合成窗
        out_spec  = new_mag * np.exp(1j * self._phi_s[c])
        out_frame = np.fft.irfft(out_spec).real * self._win

        # 正規化補償 sqrt(hann) 4x overlap 增益
        return out_frame * (self.HOP / self.N_FFT * 2.0)
