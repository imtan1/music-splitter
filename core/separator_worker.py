"""
分源 Worker：在獨立子進程中執行，與主進程透過 Queue 溝通。
不依賴 Qt，不依賴 QThread，可被 process.kill() 真正停止。

Queue 訊息格式：
  ('progress', message: str, percent: int)
  ('done',     result_path: str)          # pickle 暫存檔路徑
  ('error',    message: str)
"""
import gc
import os
import pickle
import tempfile
import threading
import numpy as np
import torch
from concurrent.futures import ThreadPoolExecutor, wait

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
    for stem in ('vocals', 'piano', 'guitar'):
        if stem in result:
            audio_np, _ = result[stem]
            mono = audio_np.mean(axis=1).astype(np.float32)
            if mono.std() > 1e-4:
                return mono
    return original_mono


def _pick_tempo_source(result: dict, original_mono: np.ndarray) -> tuple[np.ndarray, str]:
    HOP = 512

    def score(stem_name):
        data = result.get(stem_name)
        if data is None:
            return 0.0
        audio_np, _ = data
        mono = audio_np.mean(axis=1).astype(np.float32)
        n = len(mono) // HOP
        if n < 4:
            return 0.0
        frames = mono[:n * HOP].reshape(n, HOP)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        flux = float(np.maximum(np.diff(rms), 0).mean())
        presence = float(np.sum(rms > rms.max() * 0.05) / n) if rms.max() > 1e-6 else 0.0
        return flux * presence

    candidates = ('drums', 'bass', 'piano', 'guitar')
    scores = {s: score(s) for s in candidates}
    best = max(scores, key=lambda s: scores[s])

    if scores[best] > 1e-8:
        audio_np, _ = result[best]
        return audio_np.mean(axis=1).astype(np.float32), best
    return original_mono, 'original'


def run_separation(input_path: str, stems: list, queue) -> None:
    """
    子進程的主函數。結果透過 pickle 暫存檔傳回，路徑放入 queue。
    這樣避免大型 numpy array 透過 Queue 傳輸導致的記憶體問題。
    """
    tmp_path = None
    try:
        queue.put(('progress', '載入模型中...', 5))
        from demucs.pretrained import get_model
        from demucs.audio import AudioFile
        from demucs.apply import apply_model

        model = get_model("htdemucs_6s")
        model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)

        # 降低子進程優先級，不影響系統其他運作
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
            )
        except Exception:
            pass

        queue.put(('progress', '讀取音檔...', 15))
        wav = AudioFile(input_path).read(
            streams=0,
            samplerate=model.samplerate,
            channels=model.audio_channels,
        )
        original_wav_np = wav.numpy()

        ref = wav.mean(0)
        wav_norm = (wav - ref.mean()) / ref.std()
        wav_norm = wav_norm.unsqueeze(0).to(device)

        queue.put(('progress', '分源中（多核心平行處理）...', 20))

        # ── 切塊平行分源 ──────────────────────────────────────
        T = wav_norm.shape[-1]
        N = min(10, os.cpu_count() or 4)
        context = int(model.samplerate * 2)
        chunk_size = T // N

        chunks_meta = []
        for i in range(N):
            start      = i * chunk_size
            end        = start + chunk_size if i < N - 1 else T
            ctx_start  = max(0, start - context)
            ctx_end    = min(T, end + context)
            left_trim  = start - ctx_start
            right_trim = ctx_end - end
            chunks_meta.append((ctx_start, ctx_end, left_trim, right_trim))

        completed = [0]
        lock = threading.Lock()

        def _process_chunk(meta):
            ctx_start, ctx_end, left_trim, right_trim = meta
            chunk = wav_norm[:, :, ctx_start:ctx_end]
            with torch.no_grad():
                out = apply_model(model, chunk, device=device,
                                  progress=False, num_workers=0)
            out = out[0]
            r = out.shape[-1] - right_trim if right_trim > 0 else None
            out = out[:, :, left_trim:r]
            with lock:
                completed[0] += 1
                pct = 20 + completed[0] * 55 // N
                queue.put(('progress', f'分源中 ({completed[0]}/{N} 塊)...', pct))
            return out

        torch.set_num_threads(max(1, torch.get_num_threads() // N))
        pool = ThreadPoolExecutor(max_workers=N)
        future_to_idx = {pool.submit(_process_chunk, meta): i for i, meta in enumerate(chunks_meta)}
        chunk_results = [None] * len(chunks_meta)
        pool_error = None

        try:
            pending = set(future_to_idx.keys())
            while pending:
                done, pending = wait(pending, timeout=0.2)
                for f in done:
                    try:
                        chunk_results[future_to_idx[f]] = f.result()
                    except Exception as e:
                        pool_error = e
                        raise
        except Exception as e:
            if pool_error is None:
                pool_error = e
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if pool_error is not None:
            queue.put(('error', f'分源塊處理失敗: {pool_error}'))
            return

        sources = torch.cat(chunk_results, dim=-1)
        sources = sources * ref.std() + ref.mean()
        model_stems = model.sources
        sr = model.samplerate

        del wav_norm, chunk_results
        model.cpu()
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

        # 優先級恢復正常
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00000020  # NORMAL_PRIORITY_CLASS
            )
        except Exception:
            pass

        result = {}
        for i, stem_name in enumerate(model_stems):
            if stem_name not in stems:
                continue
            queue.put(('progress', f'整理音軌：{STEM_LABELS.get(stem_name, stem_name)}...', 70 + i * 4))
            audio = sources[i].cpu().numpy()
            audio = audio.T.astype(np.float32)
            result[stem_name] = (audio, sr)

        queue.put(('progress', '偵測 BPM 與調性...', 95))
        from core.bpm import detect_bpm
        from core.key import detect_key
        original_mono = original_wav_np.mean(axis=0).astype(np.float32)
        tempo_src, bpm_source = _pick_tempo_source(result, original_mono)
        tempo, beat_times = detect_bpm(tempo_src, sr)
        key_src = _pick_key_source(result, original_mono)
        key = detect_key(key_src, sr)

        queue.put(('progress', '完成！', 100))

        # 結果寫入暫存檔（避免大型 array 透過 Queue 傳輸）
        fd, tmp_path = tempfile.mkstemp(suffix='.pkl', prefix='music_splitter_')
        os.close(fd)
        with open(tmp_path, 'wb') as f:
            pickle.dump({
                'result': result,
                'tempo': tempo,
                'key': key,
                'bpm_source': bpm_source,
                'beat_times': beat_times,
            }, f)

        queue.put(('done', tmp_path))

    except torch.cuda.OutOfMemoryError:
        queue.put(('error', 'CUDA 記憶體不足，請關閉其他程式或改用 CPU'))
    except Exception as e:
        queue.put(('error', f'分源失敗: {e}'))
