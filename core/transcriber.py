"""
音頻 → 簡譜音符轉換
使用 Spotify Basic Pitch 偵測音高，music21 做節奏量化。
"""
import numpy as np
from PySide6.QtCore import QThread, Signal
from dataclasses import dataclass, field


# ──────────────────────────────────────────────
# 資料結構
# ──────────────────────────────────────────────

@dataclass
class JianpuNote:
    num: str        # '0'(休止) 或 '1'–'7'
    octave: int     # -2 ~ 2，負數=低音點，正數=高音點
    beats: float    # 量化後的拍數（quarterLength）
    dotted: bool = False   # 附點音符
    triplet: bool = False  # 三連音（顯示 "3" 括號）


# ──────────────────────────────────────────────
# 音樂常數
# ──────────────────────────────────────────────

NOTE_PC = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
    'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11,
}

MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]

# 有效拍值（duple，以拍為單位）
VALID_BEATS_DUPLE = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.125]
DOTTED_BEATS = {3.0, 1.5, 0.75, 0.375}

# 三連音拍值
TRIPLET_BEATS = {
    2/3: True,   # 三連音四分音符（一拍三連音的每一音）
    4/3: True,   # 三連音二分音符
    1/3: True,   # 三連音八分音符
}

NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


# ──────────────────────────────────────────────
# QThread
# ──────────────────────────────────────────────

class TranscriberThread(QThread):
    progress = Signal(str, int)
    # raw_notes, jianpu_notes, tempo, key, beat_dur
    finished = Signal(list, list, float, str, float)
    error = Signal(str)

    def __init__(self, audio: np.ndarray, sr: int, parent=None,
                 initial_tempo: float = 0.0, initial_key: str = ''):
        super().__init__(parent)
        self.audio = audio
        self.sr = sr
        self.initial_tempo = initial_tempo      # >0 則跳過 BPM 偵測
        self.initial_key = initial_key          # 非空且非'自動偵測' 則跳過調性偵測

    def run(self):
        try:
            mono = self.audio.mean(axis=1) if self.audio.ndim == 2 else self.audio
            mono = mono.astype(np.float32)
            sr = self.sr

            # BPM — 用降採樣短段快速估計
            ANALYSIS_SR = 22050
            self.progress.emit("偵測節拍（BPM）...", 5)
            if sr == 44100:
                mono_ds = mono[::2]
            elif sr != ANALYSIS_SR:
                from scipy.signal import resample_poly
                import math
                g = math.gcd(sr, ANALYSIS_SR)
                mono_ds = resample_poly(mono, ANALYSIS_SR // g, sr // g).astype(np.float32)
            else:
                mono_ds = mono

            if self.initial_tempo > 0:
                tempo = self.initial_tempo
            else:
                tempo = _estimate_tempo_fast(mono_ds[:ANALYSIS_SR * 10], ANALYSIS_SR)
            beat_dur = 60.0 / tempo

            # Spotify Basic Pitch 音高偵測
            self.progress.emit("載入 Basic Pitch 模型...", 10)
            from basic_pitch.inference import predict as bp_predict
            from basic_pitch import ICASSP_2022_MODEL_PATH

            self.progress.emit("Basic Pitch 音高分析中...", 15)
            _, _, note_events = bp_predict(
                (mono, sr),
                model_or_model_path=ICASSP_2022_MODEL_PATH,
                onset_threshold=0.5,
                frame_threshold=0.3,
                minimum_note_length=58,
                minimum_frequency=65.0,    # C2
                maximum_frequency=2093.0,  # C7
                multiple_pitch_bends=False,
                melodia_trick=True,
            )

            self.progress.emit("整理音符...", 75)
            # 轉換為 raw_notes 格式，並從間隔推算休止符
            note_list = sorted(
                [(float(s), float(e), int(p)) for s, e, p, *_ in note_events],
                key=lambda x: x[0],
            )
            raw = []
            prev_end = 0.0
            min_rest = beat_dur * 0.12
            for start_t, end_t, pitch_midi in note_list:
                gap = start_t - prev_end
                if gap > min_rest:
                    raw.append({'midi': None, 'start': prev_end, 'dur': gap})
                raw.append({'midi': pitch_midi, 'start': start_t, 'dur': end_t - start_t})
                prev_end = end_t

            # 調性
            if self.initial_key and self.initial_key not in ('', '自動偵測'):
                key = self.initial_key
            else:
                self.progress.emit("偵測調性...", 80)
                key = _detect_key(raw)

            self.progress.emit("節奏量化中（music21）...", 85)
            notes = _to_jianpu_music21(raw, key, beat_dur)

            self.progress.emit("完成！", 100)
            self.finished.emit(raw, notes, tempo, key, beat_dur)

        except Exception as e:
            import traceback
            self.error.emit(str(e) + '\n\n' + traceback.format_exc())


# ──────────────────────────────────────────────
# 公開轉換函式（供 UI 重新換調時呼叫）
# ──────────────────────────────────────────────

def convert_raw_to_jianpu(raw_notes: list, key: str, beat_dur: float) -> list:
    return _to_jianpu_music21(raw_notes, key, beat_dur)


# ──────────────────────────────────────────────
# 內部實作
# ──────────────────────────────────────────────

def _estimate_tempo_fast(mono: np.ndarray, sr: int, default: float = 120.0) -> float:
    """
    用 RMS envelope FFT 自相關法快速估 BPM，完全向量化無 Python loop。
    輸入最多 10 秒的 mono 音頻。若偵測失敗則回傳 default。
    """
    HOP = 256
    n_hops = (len(mono) - HOP) // HOP
    if n_hops < 4:
        return default

    # 向量化 RMS：reshape 後一次計算
    frames = mono[:n_hops * HOP].reshape(n_hops, HOP)
    rms = np.sqrt(np.mean(frames ** 2, axis=1)).astype(np.float32)
    rms -= rms.mean()
    if rms.std() < 1e-6:
        return default

    # FFT 自相關，O(n log n) 不用 np.correlate O(n²)
    n = len(rms)
    f = np.fft.rfft(rms, n=2 * n)
    corr = np.fft.irfft(f * np.conj(f))[:n].real

    # 搜尋範圍：40–200 BPM
    lo = max(1, int(60.0 / 200 * sr / HOP))
    hi = min(n - 1, int(60.0 / 40 * sr / HOP))
    if lo >= hi:
        return default

    peak = int(np.argmax(corr[lo:hi])) + lo
    beat_period = peak * HOP / sr
    tempo = 60.0 / beat_period if beat_period > 0 else default

    if tempo < 50 or tempo > 220:
        return default
    return float(tempo)


def _segment_notes(f0, voiced, times, beat_dur):
    """向量化音符分割，避免 Python loop。"""
    min_dur = beat_dur * 0.12

    # hz -> midi，只對 voiced frames 計算
    midi_f = np.full(len(f0), np.nan, dtype=np.float32)
    v_idx = np.where(voiced)[0]
    if len(v_idx):
        midi_f[v_idx] = 12.0 * np.log2(f0[v_idx] / 440.0) + 69.0
    midi_r = np.where(voiced, np.round(midi_f).astype(np.float32), np.nan)

    # 找出 voiced/unvoiced 段落邊界
    voiced_int = voiced.astype(np.int8)
    # 在頭尾加 0，讓 diff 能偵測開頭/結尾的段落
    padded = np.concatenate([[0], voiced_int, [0]])
    diff = np.diff(padded.astype(np.int16))
    starts = np.where(diff == 1)[0]   # voiced 段開始
    ends   = np.where(diff == -1)[0]  # voiced 段結束（不含）

    uv_starts = np.where(diff == -1)[0]   # unvoiced 段開始
    uv_ends   = np.where(diff == 1)[0]    # unvoiced 段結束（不含）

    notes = []

    # voiced 段
    for s, e in zip(starts, ends):
        if e <= s:
            continue
        dur = float(times[e - 1] - times[s])
        if dur < min_dur:
            continue
        seg_midi = midi_r[s:e]
        seg_midi = seg_midi[~np.isnan(seg_midi)]
        if len(seg_midi) == 0:
            continue
        pitch = int(round(float(np.median(seg_midi))))
        notes.append({'midi': pitch, 'start': float(times[s]), 'dur': dur})

    # unvoiced 段
    for s, e in zip(uv_starts, uv_ends):
        if e <= s:
            continue
        dur = float(times[e - 1] - times[s])
        if dur < min_dur:
            continue
        notes.append({'midi': None, 'start': float(times[s]), 'dur': dur})

    notes.sort(key=lambda n: n['start'])
    return notes


def _detect_key(raw_notes: list) -> str:
    major_p = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                         2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_p = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                         2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    pc = np.zeros(12)
    for n in raw_notes:
        if n['midi'] is not None:
            pc[int(n['midi']) % 12] += n['dur']

    if pc.sum() == 0:
        return 'C'
    pc /= pc.sum()

    best, best_key = -1.0, 'C'
    for s in range(12):
        sh = np.roll(pc, -s)
        for profile, sfx in [(major_p, ''), (minor_p, 'm')]:
            score = float(np.dot(sh, profile))
            if score > best:
                best, best_key = score, NOTE_NAMES[s] + sfx
    return best_key


def _to_jianpu_music21(raw_notes: list, key: str, beat_dur: float) -> list:
    """
    使用 music21 量化節奏（支援三連音、切分音），再轉換為 JianpuNote。
    若 music21 未安裝則 fallback 到舊版最近鄰量化。
    """
    try:
        from music21 import stream, note as m21note, duration as m21dur
    except ImportError:
        return _to_jianpu_fallback(raw_notes, key, beat_dur)

    is_minor = key.endswith('m')
    root_pc = NOTE_PC.get(key.rstrip('m'), 0)
    scale = MINOR_SCALE if is_minor else MAJOR_SCALE

    # ── 建立 music21 Stream ──
    s = stream.Stream()
    for n in raw_notes:
        offset_ql = n['start'] / beat_dur
        dur_ql = max(0.125, n['dur'] / beat_dur)

        if n['midi'] is None:
            elem = m21note.Rest()
        else:
            elem = m21note.Note()
            elem.pitch.midi = int(n['midi'])

        elem.duration = m21dur.Duration(quarterLength=dur_ql)
        s.insert(offset_ql, elem)

    # ── music21 量化（duple + triplet） ──
    try:
        sq = s.quantize(
            (4, 3),
            processOffsets=True,
            processDurations=True,
            inPlace=False,
        )
        elements = list(sq.flatten().notesAndRests)
    except Exception:
        elements = list(s.flatten().notesAndRests)

    # ── 轉換為 JianpuNote ──
    result = []
    for elem in elements:
        ql = float(elem.duration.quarterLength)
        if ql <= 0:
            continue

        is_triplet = _is_triplet_ql(ql)
        beats, dotted = _ql_to_beats(ql, is_triplet)

        if elem.isRest:
            result.append(JianpuNote('0', 0, beats, dotted, is_triplet))
        else:
            num, octave = _midi_to_num(int(elem.pitch.midi), root_pc, scale)
            result.append(JianpuNote(num, octave, beats, dotted, is_triplet))

    return result if result else _to_jianpu_fallback(raw_notes, key, beat_dur)


def _is_triplet_ql(ql: float) -> bool:
    """判斷一個 quarterLength 是否屬於三連音。"""
    # 三連音的 quarterLength 是 2/3 的倍數（且不是 duple 值）
    # 常見：2/3, 4/3, 1/3, 8/3
    denom_3 = round(ql * 3)
    if denom_3 == 0:
        return False
    reconstructed = denom_3 / 3.0
    if abs(reconstructed - ql) > 0.01:
        return False
    # 排除同時也是 duple 的值（如 1.0, 2.0, 4.0）
    denom_2 = round(ql * 4)
    if denom_2 > 0 and abs(denom_2 / 4.0 - ql) < 0.01:
        return False
    return True


def _ql_to_beats(ql: float, is_triplet: bool) -> tuple:
    """將 quarterLength 轉換為 (beats, dotted)。"""
    if is_triplet:
        # 三連音：直接回傳（保留分數值）
        return ql, False

    # Duple：找最近的有效拍值
    q = min(VALID_BEATS_DUPLE, key=lambda v: abs(v - ql))
    return q, (q in DOTTED_BEATS)


def _to_jianpu_fallback(raw_notes: list, key: str, beat_dur: float) -> list:
    """music21 不可用時的備用量化（最近鄰）。"""
    VALID_BEATS = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25]
    DOTTED = {3.0, 1.5, 0.75, 0.375}

    is_minor = key.endswith('m')
    root_pc = NOTE_PC.get(key.rstrip('m'), 0)
    scale = MINOR_SCALE if is_minor else MAJOR_SCALE

    result = []
    for n in raw_notes:
        dur_beats = n['dur'] / beat_dur
        q = min(VALID_BEATS, key=lambda v: abs(v - dur_beats))
        dotted = q in DOTTED
        if n['midi'] is None:
            result.append(JianpuNote('0', 0, q, dotted, False))
        else:
            num, octave = _midi_to_num(n['midi'], root_pc, scale)
            result.append(JianpuNote(num, octave, q, dotted, False))
    return result


def _midi_to_num(midi: int, root_pc: int, scale: list):
    pc = midi % 12
    rel = (pc - root_pc) % 12

    degree = min(range(len(scale)),
                 key=lambda i: min(abs(rel - scale[i]), 12 - abs(rel - scale[i])))
    num = str(degree + 1)

    ref_tonic = 60 + root_pc
    degree_ref = ref_tonic + scale[degree]
    octave = round((midi - degree_ref) / 12)

    return num, int(np.clip(octave, -2, 2))
