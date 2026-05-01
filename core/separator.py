"""
音源分離模組
使用 Demucs htdemucs_6s 模型將音頻拆分為六條音軌：人聲、鼓、貝斯、吉他、鋼琴、其他。
分源完成後依各軌 onset strength 自動選擇最佳音源做 BPM 偵測，並對原始混音做調性偵測。
"""
import gc
import os
import threading
import numpy as np
import torch
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QThread, Signal


STEMS = ["vocals", "drums", "bass", "guitar", "piano", "other"]
STEM_LABELS = {
    "vocals": "人聲",
    "drums": "鼓",
    "bass": "貝斯",
    "guitar": "吉他",
    "piano": "鋼琴",
    "other": "其他",
}


def _pick_key_source(result: dict, original_mono: np.ndarray) -> np.ndarray:
    """
    依各軌 RMS 能量選出最適合做調性分析的音源。
    優先順序：vocals → piano → guitar → original
    避免使用：drums、bass、other（節奏性音軌，調性資訊少）
    """
    THRESHOLD = 0.05  # 相對門檻：至少達最強候選軌的 5%

    def rms(stem_name):
        data = result.get(stem_name)
        if data is None:
            return 0.0
        audio_np, _ = data
        mono = audio_np.mean(axis=1).astype(np.float32)
        return float(np.sqrt(np.mean(mono ** 2)))

    candidates = ('vocals', 'piano', 'guitar')
    scores = {s: rms(s) for s in candidates}
    best_score = max(scores.values()) if scores else 0.0

    def get_mono(stem_name):
        data = result.get(stem_name)
        if data is None:
            return None
        audio_np, _ = data
        return audio_np.mean(axis=1).astype(np.float32)

    for stem in candidates:
        if best_score > 0 and scores[stem] >= best_score * THRESHOLD and scores[stem] > 1e-6:
            mono = get_mono(stem)
            if mono is not None:
                return mono
    return original_mono


def _pick_tempo_source(result: dict, original_mono: np.ndarray) -> np.ndarray:
    """
    依各軌 onset strength 選出最適合做 BPM 分析的音源。
    優先順序：drums → bass → piano/guitar（取較強者）→ original
    """
    THRESHOLD = 0.1  # 相對門檻：至少達最強軌的 10%

    def onset_strength(stem_name):
        data = result.get(stem_name)
        if data is None:
            return 0.0
        audio_np, _ = data
        mono = audio_np.mean(axis=1).astype(np.float32)  # (samples, ch) → mono
        HOP = 512
        n = len(mono) // HOP
        if n < 4:
            return 0.0
        frames = mono[:n * HOP].reshape(n, HOP)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        flux = np.maximum(np.diff(rms), 0)
        return float(flux.mean())

    scores = {s: onset_strength(s) for s in ('drums', 'bass', 'piano', 'guitar')}
    best_score = max(scores.values()) if scores else 0.0

    def strong(s):
        return best_score > 0 and scores[s] >= best_score * THRESHOLD and scores[s] > 1e-6

    def get_mono(stem_name):
        data = result.get(stem_name)
        if data is None:
            return None
        audio_np, _ = data
        return audio_np.mean(axis=1).astype(np.float32)

    for stem in ('drums', 'bass'):
        if strong(stem):
            mono = get_mono(stem)
            if mono is not None:
                return mono
    melodic = max(('piano', 'guitar'), key=lambda s: scores[s])
    if strong(melodic):
        mono = get_mono(melodic)
        if mono is not None:
            return mono
    return original_mono


def _detect_key_chromagram(mono: np.ndarray, sr: int) -> str:
    from core.key import detect_key
    return detect_key(mono, sr)


class SeparatorThread(QThread):
    progress  = Signal(str, int)         # (message, percent)
    finished  = Signal(dict, float, str) # {stem: (audio_np, sr)}, tempo, key
    error     = Signal(str)
    cancelled = Signal()

    def __init__(self, input_path: str, stems: list[str], parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.stems = stems
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.progress.emit("載入模型中...", 5)
            from demucs.pretrained import get_model
            from demucs.audio import AudioFile
            from demucs.apply import apply_model

            model = get_model("htdemucs_6s")
            model.eval()
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model.to(device)

            self.progress.emit("讀取音檔...", 15)
            wav = AudioFile(self.input_path).read(
                streams=0,
                samplerate=model.samplerate,
                channels=model.audio_channels,
            )
            # wav shape: (channels, samples) — torch tensor on CPU
            original_wav_np = wav.numpy()  # 正規化前保存，供 BPM/key 分析備用

            ref = wav.mean(0)
            wav_norm = (wav - ref.mean()) / ref.std()
            wav_norm = wav_norm.unsqueeze(0).to(device)  # (1, C, T)

            self.progress.emit("分源中（多核心平行處理）...", 20)

            try:
                import ctypes
                ctypes.windll.kernel32.SetPriorityClass(
                    ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
                )
            except Exception:
                pass

            # ── 切塊平行分源 ──────────────────────────────────────
            T = wav_norm.shape[-1]
            N = min(10, os.cpu_count() or 4)
            context = int(model.samplerate * 2)   # 2 秒 context，避免邊界斷點
            chunk_size = T // N

            chunks_meta = []
            for i in range(N):
                start     = i * chunk_size
                end       = start + chunk_size if i < N - 1 else T
                ctx_start = max(0, start - context)
                ctx_end   = min(T, end   + context)
                left_trim  = start - ctx_start
                right_trim = ctx_end - end
                chunks_meta.append((ctx_start, ctx_end, left_trim, right_trim))

            completed = [0]
            lock = threading.Lock()

            def _process_chunk(meta):
                if self._cancelled:
                    raise RuntimeError("cancelled")
                ctx_start, ctx_end, left_trim, right_trim = meta
                chunk = wav_norm[:, :, ctx_start:ctx_end]
                with torch.no_grad():
                    out = apply_model(model, chunk, device=device,
                                      progress=False, num_workers=0)
                out = out[0]  # (num_stems, C, chunk_len)
                r = out.shape[-1] - right_trim if right_trim > 0 else None
                out = out[:, :, left_trim:r]
                with lock:
                    completed[0] += 1
                    pct = 20 + completed[0] * 55 // N
                    self.progress.emit(f"分源中 ({completed[0]}/{N} 塊)...", pct)
                return out

            orig_threads = torch.get_num_threads()
            torch.set_num_threads(max(1, orig_threads // N))
            try:
                with ThreadPoolExecutor(max_workers=N) as pool:
                    chunk_results = list(pool.map(_process_chunk, chunks_meta))
            except Exception as e:
                if self._cancelled:
                    self.cancelled.emit()
                    return
                self.error.emit(f"分源塊處理失敗: {e}")
                return

            if self._cancelled:
                self.cancelled.emit()
                return
            finally:
                torch.set_num_threads(orig_threads)

            sources = torch.cat(chunk_results, dim=-1)  # (num_stems, C, T)
            sources = sources * ref.std() + ref.mean()
            model_stems = model.sources  # e.g. ['drums','bass','other','vocals','guitar','piano']
            sr = model.samplerate
            del wav_norm, chunk_results
            model.cpu()
            del model
            if device == "cuda":
                torch.cuda.empty_cache()
            gc.collect()
            try:
                import ctypes
                ctypes.windll.kernel32.SetPriorityClass(
                    ctypes.windll.kernel32.GetCurrentProcess(), 0x00000020  # NORMAL_PRIORITY_CLASS
                )
            except Exception:
                pass
            # ─────────────────────────────────────────────────────

            result = {}

            for i, stem_name in enumerate(model_stems):
                if stem_name not in self.stems:
                    continue
                self.progress.emit(f"整理音軌：{STEM_LABELS.get(stem_name, stem_name)}...", 70 + i * 4)
                audio = sources[i].cpu().numpy()  # (channels, samples)
                audio = audio.T.astype(np.float32)  # (samples, channels)
                result[stem_name] = (audio, sr)

            if self._cancelled:
                self.cancelled.emit()
                return

            # 分源後用各軌 onset strength 選最佳 BPM 音源
            self.progress.emit("偵測 BPM 與調性...", 95)
            from core.bpm import detect_bpm
            from core.key import detect_key
            original_mono = original_wav_np.mean(axis=0).astype(np.float32)
            tempo_src = _pick_tempo_source(result, original_mono)
            tempo = detect_bpm(tempo_src, sr)
            key_src = _pick_key_source(result, original_mono)
            key = detect_key(key_src, sr)

            if self._cancelled:
                self.cancelled.emit()
                return

            self.progress.emit("完成！", 100)
            self.finished.emit(result, tempo, key)

        except RuntimeError as e:
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.error.emit(f"運行時錯誤（可能是 GPU 不足或模型載入失敗）: {e}")
        except torch.cuda.OutOfMemoryError:
            self.error.emit("CUDA 記憶體不足，請關閉其他程式或改用 CPU")
        except Exception as e:
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.error.emit(f"未知錯誤: {e}")
