"""
音源分離模組
使用 Demucs htdemucs_6s 模型將音頻拆分為六條音軌：人聲、鼓、貝斯、吉他、鋼琴、其他。
分源完成後依各軌 onset strength 自動選擇最佳音源做 BPM 偵測，並對原始混音做調性偵測。
"""
import os
import numpy as np
import torch
import soundfile as sf
from pathlib import Path
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
        audio_np, _ = result[stem_name]
        return audio_np.mean(axis=1).astype(np.float32)

    for stem in candidates:
        if best_score > 0 and scores[stem] >= best_score * THRESHOLD and scores[stem] > 1e-6:
            return get_mono(stem)
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
        audio_np, _ = result[stem_name]
        return audio_np.mean(axis=1).astype(np.float32)

    if strong('drums'):
        return get_mono('drums')
    if strong('bass'):
        return get_mono('bass')
    melodic = max(('piano', 'guitar'), key=lambda s: scores[s])
    if strong(melodic):
        return get_mono(melodic)
    return original_mono


def _detect_key_chromagram(mono: np.ndarray, sr: int) -> str:
    from core.key import detect_key
    return detect_key(mono, sr)


class SeparatorThread(QThread):
    progress = Signal(str, int)         # (message, percent)
    finished = Signal(dict, float, str) # {stem: (audio_np, sr)}, tempo, key
    error = Signal(str)

    def __init__(self, input_path: str, stems: list[str], parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.stems = stems

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
            wav = (wav - ref.mean()) / ref.std()
            wav = wav.unsqueeze(0).to(device)  # (1, C, T)

            self.progress.emit("分源中（可能需要幾分鐘）...", 20)

            with torch.no_grad():
                sources = apply_model(
                    model,
                    wav,
                    device=device,
                    progress=False,
                    num_workers=0,
                )
            # sources shape: (1, num_stems, channels, samples)
            sources = sources[0]  # (num_stems, channels, samples)

            # Re-scale back
            sources = sources * ref.std() + ref.mean()

            result = {}
            model_stems = model.sources  # e.g. ['drums','bass','other','vocals','guitar','piano']
            sr = model.samplerate

            for i, stem_name in enumerate(model_stems):
                if stem_name not in self.stems:
                    continue
                self.progress.emit(f"整理音軌：{STEM_LABELS.get(stem_name, stem_name)}...", 70 + i * 4)
                audio = sources[i].cpu().numpy()  # (channels, samples)
                audio = audio.T.astype(np.float32)  # (samples, channels)
                result[stem_name] = (audio, sr)

            # 分源後用各軌 onset strength 選最佳 BPM 音源
            self.progress.emit("偵測 BPM 與調性...", 95)
            from core.bpm import detect_bpm
            from core.key import detect_key
            original_mono = original_wav_np.mean(axis=0).astype(np.float32)
            tempo_src = _pick_tempo_source(result, original_mono)
            tempo = detect_bpm(tempo_src, sr)
            key_src = _pick_key_source(result, original_mono)
            key = detect_key(key_src, sr)

            self.progress.emit("完成！", 100)
            self.finished.emit(result, tempo, key)

        except Exception as e:
            self.error.emit(str(e))
