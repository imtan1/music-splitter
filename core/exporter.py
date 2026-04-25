"""
MP3 匯出模組
將 float32 音頻陣列透過 pydub 與 FFmpeg 匯出為 320kbps MP3 檔案，支援套用音量縮放。
"""
import os
import shutil
import tempfile
import numpy as np
import soundfile as sf
from pydub import AudioSegment


def _find_ffmpeg() -> str | None:
    """嘗試找到 ffmpeg 執行檔路徑。"""
    # 1. 與執行檔同資料夾（打包後優先用這個）
    base = getattr(__import__('sys'), '_MEIPASS', None)  # PyInstaller 解壓目錄
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
        base = os.path.dirname(base)  # 往上一層到專案根目錄
    bundled = os.path.join(base, 'ffmpeg.exe')
    if os.path.isfile(bundled):
        return bundled

    # 2. 系統 PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 3. Windows 常見安裝位置
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def _setup_pydub():
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        AudioSegment.converter = ffmpeg_path
        return True
    return False


_FFMPEG_AVAILABLE = _setup_pydub()

FFMPEG_INSTALL_MSG = (
    "找不到 ffmpeg，無法匯出 MP3。\n\n"
    "請安裝 ffmpeg：\n"
    "  方法一（推薦）：在終端機執行\n"
    "    winget install ffmpeg\n\n"
    "  方法二：手動下載 https://ffmpeg.org/download.html\n"
    "  解壓後將 bin 資料夾加入系統 PATH，\n"
    "  或放在 C:\\ffmpeg\\bin\\ 底下。\n\n"
    "安裝後重新啟動程式即可。"
)


def export_mp3(audio: np.ndarray, sample_rate: int, output_path: str, bitrate: str = "320k"):
    """
    將 float32 numpy audio (samples, 2) 輸出為 MP3 檔案（320kbps）。
    """
    if not _FFMPEG_AVAILABLE:
        raise RuntimeError(FFMPEG_INSTALL_MSG)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        sf.write(tmp_path, audio_int16, sample_rate, subtype="PCM_16")

        segment = AudioSegment.from_wav(tmp_path)
        segment.export(output_path, format="mp3", bitrate=bitrate)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
