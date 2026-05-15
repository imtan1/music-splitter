"""
分源進程管理器：用 QThread 在背景輪詢子進程狀態，
子進程執行 separator_worker.run_separation()。

取消時直接 kill 子進程，CPU 立即停止。
"""
import os
import pickle
import multiprocessing
from PySide6.QtCore import QThread, Signal

from core.separator_worker import run_separation, STEMS, STEM_LABELS


class SeparatorProcess(QThread):
    progress  = Signal(str, int)                        # (message, percent)
    finished  = Signal(dict, float, str, str, object)  # result, tempo, key, bpm_source, beat_times
    error     = Signal(str)
    cancelled = Signal()

    def __init__(self, input_path: str, stems: list, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.stems = stems
        self._process: multiprocessing.Process | None = None
        self._queue: multiprocessing.Queue | None = None

    def cancel(self):
        """立即殺死子進程，CPU 使用率馬上下降。"""
        if self._process and self._process.is_alive():
            self._process.kill()   # SIGKILL — 不可忽略，立即停止
            self._process.join(timeout=2)

    def run(self):
        """QThread 的主體：啟動子進程並輪詢 Queue。"""
        ctx = multiprocessing.get_context('spawn')  # Windows 安全
        self._queue = ctx.Queue()
        self._process = ctx.Process(
            target=run_separation,
            args=(self.input_path, self.stems, self._queue),
            daemon=True,  # 主程式結束時子進程自動回收
        )
        self._process.start()

        tmp_path = None
        try:
            while True:
                # 每 100ms 檢查一次 Queue，避免阻塞
                try:
                    msg = self._queue.get(timeout=0.1)
                except Exception:
                    # timeout — 子進程還在跑，檢查它是否意外死亡
                    if not self._process.is_alive():
                        exit_code = self._process.exitcode
                        if exit_code != 0:
                            # 被 kill() 或異常退出
                            self.cancelled.emit()
                        return
                    continue

                kind = msg[0]

                if kind == 'progress':
                    _, message, percent = msg
                    self.progress.emit(message, percent)

                elif kind == 'done':
                    _, tmp_path = msg
                    break

                elif kind == 'error':
                    _, message = msg
                    self.error.emit(message)
                    return

        except Exception as e:
            self.error.emit(f'進程通訊錯誤: {e}')
            return
        finally:
            # 確保子進程結束
            if self._process and self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=2)

        # 子進程已完成，讀取暫存結果
        if tmp_path is None:
            self.cancelled.emit()
            return

        try:
            with open(tmp_path, 'rb') as f:
                data = pickle.load(f)
        except Exception as e:
            self.error.emit(f'讀取分源結果失敗: {e}')
            return
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        self.finished.emit(
            data['result'],
            data['tempo'],
            data['key'],
            data['bpm_source'],
            data['beat_times'],
        )
