"""Final verification: beat_times offset fix"""
import sys, numpy as np, librosa
from core.bpm import detect_bpm

AUDIO_PATH = u"C:\\Users\\Wistronits.1302131-NB\\Desktop\\剪愛.mp3"
y, sr = librosa.load(AUDIO_PATH, sr=44100, mono=True)
bpm, beat_times = detect_bpm(y, sr)
total_samples = len(y)

# ── Load _generate_metronome from source ─────────────────────────
src_lines = open("ui/result_view.py", encoding="utf-8").readlines()
start = next(i for i, l in enumerate(src_lines) if l.startswith("def _generate_metronome("))
end = len(src_lines)
for i, l in enumerate(src_lines[start + 1:], start + 1):
    s = l.rstrip()
    if s and s[0].isalpha() and (s.startswith("def ") or s.startswith("class ")):
        end = i; break
ns = {"np": np}
exec(compile("".join(src_lines[start:end]), "<gm>", "exec"), ns)
gm = ns["_generate_metronome"]

# ─────────────────────────────────────────────────────────────────
print("=" * 60)
print("Test 1: Full-song beat_times quality (no speedup)")
print("=" * 60)

ivs = np.diff(beat_times)
median_iv = float(np.median(ivs))
# 判斷「突然加快」= 出現 interval < median * 0.7
speedup_mask = ivs < median_iv * 0.7
n_speedup = int(speedup_mask.sum())
print(f"  BPM           : {bpm:.2f}")
print(f"  beat_times len: {len(beat_times)}")
print(f"  median interval: {median_iv*1000:.1f}ms")
print(f"  min interval   : {ivs.min()*1000:.1f}ms")
print(f"  max interval   : {ivs.max()*1000:.1f}ms")
print(f"  std            : {ivs.std()*1000:.1f}ms")
print(f"  speedup count (<median*0.7): {n_speedup}")
t1 = n_speedup == 0
print(f"  Result: {'[OK] no speedup detected' if t1 else f'[FAIL] {n_speedup} anomalies found'}")

# ─────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Test 2: Mode-switch phase continuity")
print("=" * 60)

BASE_TEMPO = bpm
onset_from_bt0 = int(round(float(beat_times[0]) * sr))

# Helper: given audio, return positions where energy peaks (click positions)
def detect_clicks(audio, min_gap_ms=100):
    mono = audio[:, 0]
    hop = 128
    n = len(mono) // hop
    energy = np.array([mono[i*hop:(i+1)*hop].max() for i in range(n)])
    threshold = energy.max() * 0.3
    peaks = []
    last = -999999
    for i, e in enumerate(energy):
        pos = i * hop
        if e > threshold and pos - last > int(min_gap_ms * sr / 1000):
            peaks.append(pos)
            last = pos
    return np.array(peaks)

def click_intervals_ms(audio):
    peaks = detect_clicks(audio)
    if len(peaks) < 2:
        return np.array([])
    return np.diff(peaks) / sr * 1000

# 2a: beat_times mode (1x) — generate and check first click position
audio_1x = gm(total_samples, sr, BASE_TEMPO, onset_offset=0, beat_times=beat_times)
peaks_1x = detect_clicks(audio_1x)
first_click_1x = peaks_1x[0] if len(peaks_1x) > 0 else -1
expected_first = int(round(float(beat_times[0]) * sr))
phase_ok_1x = abs(first_click_1x - expected_first) < 300  # within ~7ms
print(f"  2a beat_times mode first click: pos={first_click_1x}  expected={expected_first}  diff={first_click_1x-expected_first}")
print(f"     {'[OK]' if phase_ok_1x else '[FAIL]'}")

# 2b: switch to 0.5x — equal-interval, onset from beat_times[0]
audio_05 = gm(total_samples, sr, BASE_TEMPO * 0.5, onset_offset=onset_from_bt0, beat_times=None)
peaks_05 = detect_clicks(audio_05)
first_click_05 = peaks_05[0] if len(peaks_05) > 0 else -1
phase_ok_05 = abs(first_click_05 - onset_from_bt0) < 300
ivs_05 = click_intervals_ms(audio_05)
expected_iv_05 = 60.0 / (BASE_TEMPO * 0.5) * 1000
iv_ok_05 = len(ivs_05) > 0 and abs(float(np.median(ivs_05)) - expected_iv_05) < 5
print(f"  2b 0.5x equal-interval: first_click={first_click_05}  onset_from_bt0={onset_from_bt0}  diff={first_click_05-onset_from_bt0}")
print(f"     interval median={float(np.median(ivs_05)) if len(ivs_05) else 0:.0f}ms  expected={expected_iv_05:.0f}ms")
print(f"     phase {'[OK]' if phase_ok_05 else '[FAIL]'}  interval {'[OK]' if iv_ok_05 else '[FAIL]'}")

# 2c: back to 1x beat_times — first click should match beat_times[0] again
audio_1x_back = gm(total_samples, sr, BASE_TEMPO, onset_offset=0, beat_times=beat_times)
peaks_1x_back = detect_clicks(audio_1x_back)
first_click_back = peaks_1x_back[0] if len(peaks_1x_back) > 0 else -1
phase_ok_back = abs(first_click_back - expected_first) < 300
print(f"  2c back to 1x: first_click={first_click_back}  expected={expected_first}  diff={first_click_back-expected_first}")
print(f"     {'[OK]' if phase_ok_back else '[FAIL]'}")

# 2d: manual BPM +3 -> equal-interval, onset from beat_times[0]
audio_bpm3 = gm(total_samples, sr, BASE_TEMPO + 3, onset_offset=onset_from_bt0, beat_times=None)
ivs_bpm3 = click_intervals_ms(audio_bpm3)
expected_iv_bpm3 = 60.0 / (BASE_TEMPO + 3) * 1000
iv_ok_bpm3 = len(ivs_bpm3) > 0 and abs(float(np.median(ivs_bpm3)) - expected_iv_bpm3) < 5
print(f"  2d BPM+3 equal-interval: median={float(np.median(ivs_bpm3)) if len(ivs_bpm3) else 0:.1f}ms  expected={expected_iv_bpm3:.1f}ms")
print(f"     {'[OK]' if iv_ok_bpm3 else '[FAIL]'}")

# ─────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Test 3: Boundary conditions")
print("=" * 60)

# 3a: last click does not exceed total_samples
audio_bt = gm(total_samples, sr, BASE_TEMPO, onset_offset=0, beat_times=beat_times)
shape_ok = audio_bt.shape == (total_samples, 2)
no_nan = not np.any(np.isnan(audio_bt))
no_overflow = not np.any(np.abs(audio_bt) > 1.0 + 1e-5)
print(f"  3a shape={audio_bt.shape}  nan={not no_nan}  overflow={not no_overflow}")
print(f"     {'[OK]' if (shape_ok and no_nan and no_overflow) else '[FAIL]'}")

# 3b: onset_offset value is 0 in beat_times mode (confirmed by examining function call)
# We verify indirectly: generate with onset_offset=99999 — in bt mode it must be ignored
audio_oo = gm(total_samples, sr, BASE_TEMPO, onset_offset=99999, beat_times=beat_times)
audio_oo2 = gm(total_samples, sr, BASE_TEMPO, onset_offset=0, beat_times=beat_times)
oo_ignored = np.allclose(audio_oo, audio_oo2)
print(f"  3b onset_offset ignored in beat_times mode: {'[OK]' if oo_ignored else '[FAIL]'}")

print()
all_ok = t1 and phase_ok_1x and phase_ok_05 and iv_ok_05 and phase_ok_back and iv_ok_bpm3 and shape_ok and no_nan and no_overflow and oo_ignored
print("All tests passed." if all_ok else "Some tests FAILED — see above.")
