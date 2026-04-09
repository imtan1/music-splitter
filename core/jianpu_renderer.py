"""
將 JianpuNote 列表渲染成 matplotlib Figure。
座標系：x = 拍數（0 ~ BEATS_PER_LINE），y 往負方向堆疊行。
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from core.transcriber import JianpuNote

# ──────────────────────────────────────────────
# 常數
# ──────────────────────────────────────────────

MEASURES_PER_LINE = 4   # 每行幾小節
BEATS_PER_MEASURE = 4   # 4/4 拍

BPL = MEASURES_PER_LINE * BEATS_PER_MEASURE  # 每行拍數 = 16

LINE_H   = 1.6   # 每行音樂高度（data units）
HEADER_H = 1.2   # 標題區高度

NUM_FS   = 13    # 音符數字 fontsize
DASH_FS  = 10    # 延音符 fontsize
DOT_MS   = 3.5   # 八度點 markersize
UL_LW    = 1.8   # 下劃線 linewidth

FLAT_DISPLAY  = {'Bb': '降B', 'Eb': '降E', 'Ab': '降A', 'Db': '降D', 'Gb': '降G'}
SHARP_DISPLAY = {'C#': '升C', 'F#': '升F', 'G#': '升G', 'D#': '升D', 'A#': '升A'}


# ──────────────────────────────────────────────
# 公開函式
# ──────────────────────────────────────────────

def render_jianpu(
    notes: list,
    tempo: float,
    key_name: str,
    title: str = "",
) -> plt.Figure:
    """
    將 JianpuNote 列表轉成 matplotlib Figure。
    """
    _setup_font()

    # 計算每個音符的起始拍位置
    positioned = []   # [(start_beat, JianpuNote)]
    cur = 0.0
    for note in notes:
        positioned.append((cur, note))
        cur += note.beats
    total_beats = cur

    n_measures = max(1, int(np.ceil(total_beats / BEATS_PER_MEASURE)))
    n_lines    = max(1, int(np.ceil(n_measures / MEASURES_PER_LINE)))

    # Figure 尺寸（以英寸為單位）
    fig_w = 14
    fig_h = (HEADER_H + n_lines * LINE_H) * 0.72  # 縮放比
    fig = plt.figure(figsize=(fig_w, max(fig_h, 3.0)), dpi=130, facecolor='white')

    total_data_h = HEADER_H + n_lines * LINE_H
    ax = fig.add_axes([0.02, 0.01, 0.96, 0.98])
    ax.set_xlim(0, BPL)
    ax.set_ylim(-total_data_h, 0)
    ax.axis('off')

    # ── 標題與調號 ──
    y = -0.08
    if title:
        ax.text(BPL / 2, y, title,
                ha='center', va='top', fontsize=18, fontweight='bold', color='black')
        y -= 0.55

    key_display = _format_key(key_name)
    ax.text(0.2, y,
            f'1 = {key_display}     ♩ = {int(tempo)}     4/4',
            ha='left', va='top', fontsize=11, color='black')

    # ── 各行音符 ──
    for line_i in range(n_lines):
        ls = line_i * BPL          # 此行第一拍的全曲拍位
        y_top = -(HEADER_H + line_i * LINE_H)
        y_mid = y_top - LINE_H * 0.50
        y_bot = y_top - LINE_H

        # 小節線
        for m in range(MEASURES_PER_LINE + 1):
            bx = m * BEATS_PER_MEASURE
            lw = 2.0 if m in (0, MEASURES_PER_LINE) else 1.0
            ax.plot([bx, bx], [y_top - 0.05, y_bot + 0.05],
                    'k-', linewidth=lw)

        # 此行的音符
        triplet_group: list = []   # [(lx, note), ...]，累積當前三連音組
        for pos, note in positioned:
            if pos < ls or pos >= ls + BPL:
                # 如果跨行則先收尾三連音組
                if triplet_group and not note.triplet:
                    _flush_triplet(ax, triplet_group, y_mid)
                    triplet_group = []
                continue
            lx = pos - ls
            _draw_note(ax, lx, y_mid, note)

            # 三連音括號處理
            if note.triplet:
                triplet_group.append((lx, note))
            else:
                if triplet_group:
                    _flush_triplet(ax, triplet_group, y_mid)
                    triplet_group = []

        # 收尾本行剩餘三連音組
        if triplet_group:
            _flush_triplet(ax, triplet_group, y_mid)
            triplet_group = []

    plt.tight_layout(pad=0.2)
    return fig


# ──────────────────────────────────────────────
# 內部繪圖函式
# ──────────────────────────────────────────────

def _draw_triplet_bracket(ax, x_start: float, x_end: float, y_mid: float):
    """在三連音組上方畫括號和數字 3。"""
    y_bracket = y_mid + 0.55
    ax.annotate(
        '', xy=(x_end, y_bracket), xytext=(x_start, y_bracket),
        arrowprops=dict(arrowstyle='-', color='black', lw=1.0),
    )
    ax.plot([x_start, x_start], [y_bracket, y_bracket - 0.10], 'k-', lw=1.0)
    ax.plot([x_end,   x_end  ], [y_bracket, y_bracket - 0.10], 'k-', lw=1.0)
    ax.text((x_start + x_end) / 2, y_bracket + 0.06, '3',
            ha='center', va='bottom', fontsize=8, color='black')


def _draw_note(ax, x: float, y_mid: float, note: JianpuNote):
    color = 'black'

    # 1. 主數字
    ax.text(x + 0.06, y_mid, note.num,
            ha='left', va='center',
            fontsize=NUM_FS, fontweight='bold', color=color)

    # 2. 高音點（數字上方）
    for d in range(max(0, note.octave)):
        ax.plot(x + 0.18, y_mid + 0.28 + d * 0.18,
                'ko', markersize=DOT_MS)

    # 3. 低音點（數字下方）
    for d in range(max(0, -note.octave)):
        ax.plot(x + 0.18, y_mid - 0.28 - d * 0.18,
                'ko', markersize=DOT_MS)

    # 4. 附點（短音符的附點在數字右側）
    if note.dotted and note.beats < 2.0:
        ax.text(x + 0.34, y_mid + 0.10, '.',
                ha='left', va='center', fontsize=16, color=color)

    # 5. 延音線（長音符在後續拍上畫破折號）
    if note.beats >= 2.0:
        n_dashes = int(note.beats) - 1
        for d_i in range(n_dashes):
            dash_x = x + (d_i + 1) + 0.15
            if dash_x < BPL - 0.1:
                ax.text(dash_x, y_mid, '—',
                        ha='left', va='center',
                        fontsize=DASH_FS, color=color)
        # 附點延音
        if note.dotted and note.beats >= 2.0:
            dot_x = x + int(note.beats) + 0.15
            if dot_x < BPL - 0.1:
                ax.text(dot_x, y_mid + 0.10, '.',
                        ha='left', va='center', fontsize=14, color=color)

    # 6. 下劃線（短音符：八分音符一條，十六分音符兩條）
    x2 = x + note.beats * 0.82
    ul1 = y_mid - 0.24
    ul2 = y_mid - 0.36

    if note.beats <= 0.5:
        ax.plot([x + 0.03, x2], [ul1, ul1], 'k-', linewidth=UL_LW)
    if note.beats <= 0.25:
        ax.plot([x + 0.03, x2], [ul2, ul2], 'k-', linewidth=UL_LW)


def _format_key(key_name: str) -> str:
    root = key_name.rstrip('m')
    is_minor = key_name.endswith('m')
    display = FLAT_DISPLAY.get(root) or SHARP_DISPLAY.get(root) or root
    if is_minor:
        display += '（小調）'
    return display


def _flush_triplet(ax, group: list, y_mid: float):
    """為一組三連音畫括號（每 3 個音一組）。"""
    # 每 3 個為一組
    for i in range(0, len(group), 3):
        chunk = group[i:i + 3]
        if len(chunk) < 2:
            continue
        x_start = chunk[0][0]
        last_lx, last_note = chunk[-1]
        x_end = last_lx + last_note.beats
        _draw_triplet_bracket(ax, x_start, x_end, y_mid)


def _setup_font():
    plt.rcParams['font.sans-serif'] = [
        'Microsoft JhengHei', 'Microsoft YaHei',
        'SimHei', 'Arial Unicode MS', 'DejaVu Sans',
    ]
    plt.rcParams['axes.unicode_minus'] = False
