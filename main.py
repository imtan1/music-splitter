import sys
import os
import threading

# 確保專案根目錄在 import 路徑內
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import MainWindow


def _prewarm_librosa():
    """背景預熱 librosa / numba JIT，避免首次按 MIDI 按鈕時凍結（GPU 機器尤其明顯）。"""
    try:
        import librosa  # noqa: F401
    except Exception:
        pass


def main():
    # 啟動背景執行緒預熱，不阻塞 UI
    threading.Thread(target=_prewarm_librosa, daemon=True).start()

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
