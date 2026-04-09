"""
Piano Roll 渲染器
將 raw_notes（精確時間 + MIDI 音高）畫成彩色橫條圖。
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
BLACK_KEYS = {1, 3, 6, 8, 10}


def render_piano_roll(raw_notes: list, title: str = '') -> plt.Figure:
    """
    raw_notes: [{'midi': int|None, 'start': float, 'dur': float}, ...]
    回傳 matplotlib Figure（深色背景 piano roll）。
    """
    _setup_font()

    voiced = [n for n in raw_notes if n.get('midi') is not None]

    if not voiced:
        fig, ax = plt.subplots(figsize=(12, 3), facecolor='#0d0d20')
        ax.set_facecolor('#0d0d20')
        ax.text(0.5, 0.5, '未偵測到音符', ha='center', va='center',
                color='#606090', fontsize=14, transform=ax.transAxes)
        ax.axis('off')
        return fig

    total_dur = max(n['start'] + n['dur'] for n in raw_notes)
    midi_min = max(20, min(n['midi'] for n in voiced) - 2)
    midi_max = min(108, max(n['midi'] for n in voiced) + 2)
    midi_range = midi_max - midi_min + 1

    fig_h = max(3.5, midi_range * 0.20)
    fig, ax = plt.subplots(figsize=(14, fig_h), facecolor='#0d0d20')
    ax.set_facecolor('#0d0d20')

    # 鋼琴鍵背景條
    for midi in range(midi_min, midi_max + 1):
        pc = midi % 12
        bg = '#13132a' if pc in BLACK_KEYS else '#1a1a30'
        ax.axhspan(midi - 0.5, midi + 0.5, color=bg, linewidth=0)

    # C 音虛線（方便對位）
    for midi in range(midi_min, midi_max + 1):
        if midi % 12 == 0:
            ax.axhline(midi - 0.5, color='#303060', linewidth=0.7, linestyle='--')

    # 繪製音符矩形
    for n in voiced:
        hue = (n['midi'] - midi_min) / max(1, midi_max - midi_min)
        r = 0.25 + 0.55 * hue
        g = 0.35 + 0.30 * (1.0 - hue)
        b = 0.95
        rect = patches.Rectangle(
            (n['start'], n['midi'] - 0.38),
            max(n['dur'], 0.04),
            0.76,
            linewidth=0.5,
            edgecolor='#ffffff30',
            facecolor=(r, g, b, 0.88),
        )
        ax.add_patch(rect)

    # Y 軸：只標 C、F、G
    ticks = [m for m in range(midi_min, midi_max + 1) if m % 12 in (0, 5, 7)]
    ax.set_yticks(ticks)
    ax.set_yticklabels(
        [f"{NOTE_NAMES[m % 12]}{m // 12 - 1}" for m in ticks],
        color='#7070a0', fontsize=8,
    )

    ax.set_xlim(0, total_dur)
    ax.set_ylim(midi_min - 0.5, midi_max + 0.5)
    ax.set_xlabel('時間（秒）', color='#7070a0', fontsize=10)
    ax.tick_params(axis='x', colors='#7070a0', labelsize=8)
    ax.tick_params(axis='y', left=True, length=3)
    for spine in ax.spines.values():
        spine.set_color('#252550')

    if title:
        ax.set_title(f'Piano Roll — {title}', color='#c4b5ff', fontsize=12, pad=6)

    plt.tight_layout(pad=0.4)
    return fig


def _setup_font():
    plt.rcParams['font.sans-serif'] = [
        'Microsoft JhengHei', 'Microsoft YaHei',
        'SimHei', 'Arial Unicode MS', 'DejaVu Sans',
    ]
    plt.rcParams['axes.unicode_minus'] = False
