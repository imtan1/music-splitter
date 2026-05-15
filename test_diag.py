import sys, numpy as np
import librosa
from core.bpm import detect_bpm

AUDIO_PATH = r"C:\Users\Wistronits.1302131-NB\Desktop\jian_ai.mp3"
import os
if not os.path.exists(AUDIO_PATH):
    AUDIO_PATH = u"C:\\Users\\Wistronits.1302131-NB\\Desktop\\剪愛.mp3"

y, sr = librosa.load(AUDIO_PATH, sr=44100, mono=True)
bpm, beat_times = detect_bpm(y, sr)

src_lines = open("ui/result_view.py", encoding="utf-8").readlines()
start_idx = next(i for i, l in enumerate(src_lines) if l.startswith("def _generate_metronome("))
end_idx = len(src_lines)
for i, l in enumerate(src_lines[start_idx + 1:], start_idx + 1):
    s = l.rstrip()
    if s and s[0].isalpha() and (s.startswith("def ") or s.startswith("class ")):
        end_idx = i
        break
fn_src = "".join(src_lines[start_idx:end_idx])
ns = {"np": np}
exec(compile(fn_src, "<gm>", "exec"), ns)
_gm = ns["_generate_metronome"]

total_samples = len(y)
_gm(total_samples, sr, bpm, beat_times=beat_times)
