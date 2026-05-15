"""Verify beat_times changes across all paths"""
import sys, types
import numpy as np

# ── Test 1: Normal path ───────────────────────────────────────────
print("=" * 60)
print("Test 1: Normal path (detect_bpm + _generate_metronome)")
print("=" * 60)

AUDIO_PATH = r"C:\Users\Wistronits.1302131-NB\Desktop\jian_ai.mp3"
import os
if not os.path.exists(AUDIO_PATH):
    AUDIO_PATH = r"C:\Users\Wistronits.1302131-NB\Desktop\剪愛.mp3"

import librosa
y, sr = librosa.load(AUDIO_PATH, sr=44100, mono=True)

from core.bpm import detect_bpm
bpm, beat_times = detect_bpm(y, sr)
print(f"  BPM           : {bpm:.2f}")
print(f"  beat_times len: {len(beat_times)}")
t1_ok = len(beat_times) > 0
print(f"  beat_times > 0: {'[OK]' if t1_ok else '[FAIL]'}")

total_samples = len(y)
click_dur = int(sr * 0.022)
t = np.arange(click_dur, dtype=np.float32) / sr
click_wave = (np.sin(2 * np.pi * 1000.0 * t) * np.exp(-180.0 * t)).astype(np.float32)

clicks_placed = 0
for bt in beat_times:
    pos = int(round(bt * sr))
    if 0 <= pos < total_samples:
        clicks_placed += 1

in_range = int((beat_times * sr < total_samples).sum())
print(f"  clicks placed : {clicks_placed}  in-range beats: {in_range}")
print(f"  beat_times mode used : {'[OK]' if clicks_placed > 0 else '[FAIL]'}")
print(f"  count matches        : {'[OK]' if clicks_placed == in_range else '[FAIL]'}")

# ── Load _generate_metronome via line-based extraction ───────────
print()
print("=" * 60)
print("Test 2: Fallback paths")
print("=" * 60)

src_lines = open('ui/result_view.py', encoding='utf-8').readlines()

# Find function start
start_idx = None
for i, line in enumerate(src_lines):
    if line.startswith('def _generate_metronome('):
        start_idx = i
        break

# Find function end (next top-level def/class)
end_idx = len(src_lines)
for i, line in enumerate(src_lines[start_idx + 1:], start_idx + 1):
    stripped = line.rstrip()
    if stripped and stripped[0].isalpha() and (stripped.startswith('def ') or stripped.startswith('class ')):
        end_idx = i
        break

fn_src = ''.join(src_lines[start_idx:end_idx])

ns = {'np': np}
try:
    exec(compile(fn_src, '<_generate_metronome>', 'exec'), ns)
    _gm = ns['_generate_metronome']
    print("  _generate_metronome loaded: [OK]")
except Exception as e:
    print(f"  load failed: {e}")
    print(fn_src[:500])
    sys.exit(1)

TOTAL = int(sr * 10)
BPM_BASE = 120.0
ONSET = int(sr * 0.5)

def check_energy(audio, expect_pos, window=200):
    lo = max(0, expect_pos - 50)
    hi = min(len(audio), expect_pos + window)
    return float(audio[lo:hi, 0].max()) > 0.01

# 2a: multiplier 0.5x -> beat_times=None -> equal-interval
try:
    a = _gm(TOTAL, sr, BPM_BASE * 0.5, onset_offset=ONSET, beat_times=None)
    iv = int(round(sr * 60.0 / (BPM_BASE * 0.5)))
    ok = check_energy(a, ONSET + iv)
    print(f"  2a 0.5x multiplier (equal-interval): {'[OK]' if ok else '[FAIL]'}  interval={iv/sr*1000:.0f}ms")
except Exception as e:
    print(f"  2a CRASH: {e}")

# 2b: multiplier 2x -> beat_times=None -> equal-interval
try:
    a = _gm(TOTAL, sr, BPM_BASE * 2.0, onset_offset=ONSET, beat_times=None)
    iv = int(round(sr * 60.0 / (BPM_BASE * 2.0)))
    ok = check_energy(a, ONSET + iv)
    print(f"  2b 2x multiplier (equal-interval)  : {'[OK]' if ok else '[FAIL]'}  interval={iv/sr*1000:.0f}ms")
except Exception as e:
    print(f"  2b CRASH: {e}")

# 2c: manual BPM change -> beat_times=None -> equal-interval
try:
    a = _gm(TOTAL, sr, 100.0, onset_offset=ONSET, beat_times=None)
    iv = int(round(sr * 60.0 / 100.0))
    ok = check_energy(a, ONSET + iv)
    print(f"  2c manual BPM=100 (equal-interval) : {'[OK]' if ok else '[FAIL]'}  interval={iv/sr*1000:.0f}ms")
except Exception as e:
    print(f"  2c CRASH: {e}")

# 2d: librosa fail -> empty beat_times -> equal-interval
try:
    a = _gm(TOTAL, sr, BPM_BASE, onset_offset=ONSET, beat_times=np.array([], dtype=np.float64))
    iv = int(round(sr * 60.0 / BPM_BASE))
    ok = check_energy(a, ONSET + iv)
    print(f"  2d empty beat_times (equal-interval): {'[OK]' if ok else '[FAIL]'}  interval={iv/sr*1000:.0f}ms")
except Exception as e:
    print(f"  2d CRASH: {e}")

# ── Test 3: Boundary conditions ──────────────────────────────────
print()
print("=" * 60)
print("Test 3: Boundary conditions")
print("=" * 60)

TOTAL_SHORT = int(sr * 5)

# 3a: last beat lands right at edge (total_samples - 10 samples)
last_beat = (TOTAL_SHORT - 10) / sr
bt_edge = np.array([0.5, 1.0, 1.5, last_beat])
try:
    a = _gm(TOTAL_SHORT, sr, BPM_BASE, beat_times=bt_edge)
    overflow = bool(np.any(np.abs(a) > 1.0 + 1e-5))
    shape_ok = a.shape == (TOTAL_SHORT, 2)
    ok = shape_ok and not overflow
    print(f"  3a edge beat no overflow: {'[OK]' if ok else '[FAIL]'}  shape={a.shape}  max={float(np.abs(a).max()):.3f}")
except Exception as e:
    print(f"  3a CRASH: {e}")

# 3b: beat_times contains positions past total_samples
bt_over = np.array([0.5, 1.0, 5.5, 6.0])  # 5.5s and 6.0s > 5s
try:
    a = _gm(TOTAL_SHORT, sr, BPM_BASE, beat_times=bt_over)
    ok = a.shape == (TOTAL_SHORT, 2) and not np.any(np.isnan(a))
    print(f"  3b out-of-range beats ignored: {'[OK]' if ok else '[FAIL]'}  shape={a.shape}")
except Exception as e:
    print(f"  3b CRASH: {e}")

print()
print("Done.")
