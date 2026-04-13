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
    從原始音頻快速偵測 BPM。
    調性偵測交由 transcriber._detect_key 在音高分析後處理（更準確）。
    wav_np: shape (channels, samples)，float32
    回傳 (tempo_bpm, key_name)
    """
    from core.transcriber import _estimate_tempo_fast

    mono = wav_np.mean(axis=0).astype(np.float32)
    tempo = _estimate_tempo_fast(mono[:sr * 10], sr)
    return tempo, '自動偵測'


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
