import sys
import os
import threading

# GPU 機器上 numba 首次 import 時會 JIT 編譯大量 kernel，造成程式凍結數分鐘。
# 停用 numba CUDA，並在背景預熱 librosa，讓使用者使用 MIDI 功能時不再等待。
os.environ.setdefault('NUMBA_DISABLE_CUDA', '1')
os.environ.setdefault('NUMBA_DISABLE_JIT', '0')  # 保留 CPU JIT 但提早觸發


def _prewarm_librosa():
    """背景預熱 librosa/numba，避免首次按 MIDI 時凍結。"""
    try:
        import librosa  # noqa: F401
    except Exception:
        pass


threading.Thread(target=_prewarm_librosa, daemon=True).start()

# 確保專案根目錄在 import 路徑內
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("音樂分源程式")
    app.setStyle("Fusion")

    # 載入全域樣式表
    qss_path = os.path.join(os.path.dirname(__file__), "ui", "styles.qss")
    if os.path.exists(qss_path):
        with open(qss_path, encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
