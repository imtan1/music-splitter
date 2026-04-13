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


def _detect_tempo_key(wav_np: np.ndarray, sr: int) -> tuple:
    """
    從原始音頻快速偵測 BPM 與調性。
    wav_np: shape (channels, samples)，float32
    回傳 (tempo_bpm, key_name)
    """
    from core.transcriber import _estimate_tempo_fast, NOTE_NAMES

    mono = wav_np.mean(axis=0).astype(np.float32)

    # BPM — 快速自相關法（取前 10 秒）
    tempo = _estimate_tempo_fast(mono[:sr * 10], sr)

    # 調性 — chroma + Krumhansl-Schmuckler
    try:
        import librosa
        segment = mono[:sr * 30]
        chroma = librosa.feature.chroma_stft(
            y=segment, sr=sr, hop_length=2048, n_fft=4096
        )
        chroma_mean = chroma.mean(axis=1)
        total = chroma_mean.sum()
        if total > 1e-8:
            chroma_mean /= total

        major_p = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                             2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_p = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                             2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        major_p /= major_p.sum()
        minor_p /= minor_p.sum()

        best_score, key = -1.0, 'C'
        for root in range(12):
            shifted = np.roll(chroma_mean, -root)
            for profile, suffix in [(major_p, ''), (minor_p, 'm')]:
                score = float(np.dot(shifted, profile))
                if score > best_score:
                    best_score = score
                    key = NOTE_NAMES[root] + suffix
    except Exception:
        key = 'C'

    return tempo, key


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

            # 在分源前偵測 BPM 與調性
            self.progress.emit("偵測 BPM 與調性...", 18)
            tempo, key = _detect_tempo_key(wav.numpy(), model.samplerate)

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

            self.progress.emit("完成！", 100)
            self.finished.emit(result, tempo, key)

        except Exception as e:
            self.error.emit(str(e))
