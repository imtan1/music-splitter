"""
音頻 → 簡譜音符轉換
使用 librosa pyin 偵測音高，music21 做節奏量化。
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

    def __init__(self, audio: np.ndarray, sr: int, parent=None):
        super().__init__(parent)
        self.audio = audio
        self.sr = sr

    def run(self):
        try:
            import librosa
        except ImportError:
            self.error.emit("請先安裝 librosa：\npip install librosa")
            return

        try:
            mono = self.audio.mean(axis=1) if self.audio.ndim == 2 else self.audio

            # 降採樣到 22050 Hz，減少分析計算量
            # 44100→22050 為整數比 2:1，直接每兩個取一個，速度比 librosa.resample 快百倍
            ANALYSIS_SR = 22050
            self.progress.emit("音頻前處理中...", 5)
            if self.sr == 44100:
                mono = mono[::2]
                sr = ANALYSIS_SR
            elif self.sr != ANALYSIS_SR:
                from scipy.signal import resample_poly
                import math
                g = math.gcd(self.sr, ANALYSIS_SR)
                mono = resample_poly(mono, ANALYSIS_SR // g, self.sr // g).astype(np.float32)
                sr = ANALYSIS_SR
            else:
                sr = self.sr

            self.progress.emit("偵測節拍（BPM）...", 10)
            tempo, _ = librosa.beat.beat_track(y=mono, sr=sr, hop_length=512)
            tempo = float(np.atleast_1d(tempo)[0])
            if tempo < 50:
                tempo *= 2
            if tempo > 200:
                tempo /= 2
            beat_dur = 60.0 / tempo

            self.progress.emit("音高分析中（pyin，需要一點時間）...", 25)
            f0, voiced, _ = librosa.pyin(
                mono,
                fmin=librosa.note_to_hz('C2'),
                fmax=librosa.note_to_hz('C7'),
                sr=sr,
                hop_length=512,
            )
            times = librosa.times_like(f0, sr=sr, hop_length=512)

            self.progress.emit("分割音符...", 65)
            raw = _segment_notes(f0, voiced, times, beat_dur)

            self.progress.emit("偵測調性...", 75)
            key = _detect_key(raw)

            self.progress.emit("節奏量化中（music21）...", 80)
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

def _segment_notes(f0, voiced, times, beat_dur):
    import librosa

    min_dur = beat_dur * 0.12
    midi = np.where(voiced,
                    librosa.hz_to_midi(np.where(voiced, f0, 440.0)),
                    np.nan)
    notes = []
    i = 0
    while i < len(voiced):
        if not voiced[i]:
            j = i + 1
            while j < len(voiced) and not voiced[j]:
                j += 1
            dur = float(times[j - 1] - times[i]) if j > i else 0.0
            if dur > min_dur:
                notes.append({'midi': None, 'start': float(times[i]), 'dur': dur})
            i = j
        else:
            pitch = round(float(midi[i]))
            j = i + 1
            while j < len(voiced) and voiced[j] and abs(float(midi[j]) - pitch) < 0.8:
                j += 1
            dur = float(times[j - 1] - times[i]) if j > i else 0.0
            if dur > min_dur:
                notes.append({'midi': pitch, 'start': float(times[i]), 'dur': dur})
            i = j
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
