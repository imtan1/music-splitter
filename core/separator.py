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
    從原始音頻快速偵測 BPM 與調性（純 numpy，無 librosa）。
    wav_np: shape (channels, samples)，float32
    回傳 (tempo_bpm, key_name)
    """
    from core.transcriber import _estimate_tempo_fast

    mono = wav_np.mean(axis=0).astype(np.float32)
    tempo = _estimate_tempo_fast(mono[:sr * 10], sr)
    key = _detect_key_chromagram(mono, sr)
    return tempo, key


def _detect_key_chromagram(mono: np.ndarray, sr: int) -> str:
    """
    Bass-weighted FFT chromagram + Krumhansl-Schmuckler 演算法偵測調性，純 numpy。
    低頻 40–500Hz 分析，bass 根音更能代表調性。
    只回傳 ALL_KEYS 中存在的調性名稱。
    """
    from scipy.signal import butter, filtfilt

    # Krumhansl-Schmuckler 音調輪廓
    major_p = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    minor_p = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])

    audio = mono.astype(np.float32)

    # 低通 500Hz — bass 根音主導調性
    nyq = sr / 2
    b, a = butter(4, min(500.0 / nyq, 0.99), btype='low')
    audio = filtfilt(b, a, audio).astype(np.float32)

    win = 8192   # 更長視窗讓低頻解析度更高
    hop = 4096
    window = np.hanning(win).astype(np.float32)

    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    valid = (freqs >= 40.0) & (freqs <= 500.0)
    valid_freqs = freqs[valid]
    midi_f = 12.0 * np.log2(np.maximum(valid_freqs, 1e-9) / 440.0) + 69.0
    pc = np.round(midi_f).astype(int) % 12   # pitch class index per bin

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

    # 大調：12 個根音，對應 ALL_KEYS 的標記法
    major_names = ['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B']
    # 小調：只取 ALL_KEYS 中有的 7 個自然音小調（根音索引）
    minor_roots = {0:'Cm', 2:'Dm', 4:'Em', 5:'Fm', 7:'Gm', 9:'Am', 11:'Bm'}

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
