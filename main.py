import sys
import os

# 禁止 numba 初始化 CUDA，避免有 GPU 的機器首次 import librosa 時
# 花費 2-10 分鐘編譯 CUDA kernel 而造成程式凍結。
# demucs 使用 PyTorch CUDA，不受此設定影響。
os.environ.setdefault('NUMBA_DISABLE_CUDA', '1')

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
