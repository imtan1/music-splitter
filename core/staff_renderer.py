"""
五線譜渲染器
使用 music21 建立 Stream，verovio 渲染為 SVG。
回傳 (svg_str, error_msg)：成功時 svg_str 有值、error_msg 為 None；
失敗時 svg_str 為 None、error_msg 為說明字串。
"""
import os
import tempfile

from core.transcriber import JianpuNote, NOTE_PC, MAJOR_SCALE, MINOR_SCALE


def _jianpu_to_midi_pitch(jn: JianpuNote, root_pc: int, scale: list) -> int:
    degree = int(jn.num) - 1
    ref_tonic = 60 + root_pc
    return ref_tonic + scale[degree] + jn.octave * 12


def render_staff_svg(
    notes: list,
    tempo: float,
    key_name: str,
    title: str = '',
) -> tuple[str | None, str | None]:
    """
    回傳 (svg_str, error_msg)。
    svg_str: SVG 字串（成功）或 None（失敗）
    error_msg: 錯誤說明字串（失敗）或 None（成功）
    """
    try:
        from music21 import stream, note as m21note, duration, meter
        from music21 import tempo as m21tempo, key as m21key, metadata
    except ImportError:
        return None, "缺少 music21 套件，請執行：\npip install music21"

    try:
        import verovio
    except ImportError:
        return None, "缺少 verovio 套件，請執行：\npip install verovio"

    is_minor = key_name.endswith('m')
    root_name = key_name.rstrip('m')
    root_pc = NOTE_PC.get(root_name, 0)
    scale = MINOR_SCALE if is_minor else MAJOR_SCALE

    # ── 建立 music21 Stream ──
    try:
        s = stream.Score()
        if title:
            s.metadata = metadata.Metadata()
            s.metadata.title = title
        part = stream.Part()
        part.append(meter.TimeSignature('4/4'))
        part.append(m21tempo.MetronomeMark(number=int(tempo)))
        part.append(m21key.Key(root_name, 'minor' if is_minor else 'major'))

        for jn in notes:
            ql = float(jn.beats)
            if ql <= 0:
                continue
            if jn.num == '0':
                elem = m21note.Rest()
            else:
                midi = _jianpu_to_midi_pitch(jn, root_pc, scale)
                elem = m21note.Note()
                elem.pitch.midi = int(midi)
            elem.duration = duration.Duration(quarterLength=ql)
            part.append(elem)

        s.append(part)
    except Exception as e:
        return None, f"建立樂譜資料失敗：{e}"

    # ── 匯出 MusicXML ──
    tmp_xml = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False, mode='w') as f:
            tmp_xml = f.name
        s.write('musicxml', fp=tmp_xml)
        with open(tmp_xml, 'r', encoding='utf-8') as f:
            xml_str = f.read()
    except Exception as e:
        return None, f"匯出 MusicXML 失敗：{e}"
    finally:
        if tmp_xml and os.path.exists(tmp_xml):
            try:
                os.unlink(tmp_xml)
            except OSError:
                pass

    # ── verovio 渲染 SVG ──
    try:
        import sys as _sys
        tk = verovio.toolkit()
        # PyInstaller bundle 中指定 verovio 資源目錄（MEI schema 等）
        if hasattr(_sys, '_MEIPASS'):
            import os as _os
            vdata = _os.path.join(_sys._MEIPASS, 'verovio', 'data')
            if _os.path.isdir(vdata):
                tk.setResourcePath(vdata)
        tk.setOptions({
            'adjustPageHeight': True,
            'pageWidth': 2200,
            'scale': 45,
            'svgHtml5': True,   # href 取代 xlink:href，瀏覽器 / WebEngine 相容
        })
        if not tk.loadData(xml_str):
            return None, "verovio 無法解析樂譜資料"
        svg = tk.renderToSVG(1)
        if not svg:
            return None, "verovio 渲染 SVG 失敗"
        return svg, None
    except Exception as e:
        return None, f"verovio 渲染失敗：{e}"
