"""Compare beat_times before and after _smooth_beat_times"""
import numpy as np, librosa
from core.bpm import _smooth_beat_times

AUDIO_PATH = u"C:\\Users\\Wistronits.1302131-NB\\Desktop\\剪愛.mp3"
y, sr = librosa.load(AUDIO_PATH, sr=44100, mono=True)

_, raw_beats = librosa.beat.beat_track(y=y, sr=sr)
raw = librosa.frames_to_time(raw_beats, sr=sr)
smoothed = _smooth_beat_times(raw)

def stats(bt, label):
    ivs = np.diff(bt)
    med = float(np.median(ivs))
    short = int((ivs < med * 0.85).sum())
    long_ = int((ivs > med * 1.15).sum())
    norm  = len(ivs) - short - long_
    print(f"[{label}] len={len(bt)}  median={med*1000:.1f}ms  "
          f"SHORT={short}  NORMAL={norm}  LONG={long_}")
    return short, long_

print("=" * 60)
s0, l0 = stats(raw,      "BEFORE")
s1, l1 = stats(smoothed, "AFTER ")
print(f"\nSHORT: {s0} -> {s1}  LONG: {l0} -> {l1}")
print(f"len unchanged: {len(raw) == len(smoothed)}")
print(f"monotonic    : {bool(np.all(np.diff(smoothed) > 0))}")
