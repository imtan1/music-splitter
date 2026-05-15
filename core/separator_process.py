"""
分源進程管理器：維護一個持久化子進程（只啟動一次），
透過 Queue 傳送任務與接收結果，避免每次重新載入 torch/demucs。

取消時 kill 子進程，CPU 立即停止；下次分源時自動重啟子進程。
"""
import os
import pickle
import multiprocessing
from PySide6.QtCore import QThread, Signal

from core.separator_worker import worker_loop, STEMS, STEM_LABELS

# 全域持久化子進程（應用程式生命週期內只啟動一次）
_worker_process: multiprocessing.Process | None = None
_task_queue:    multiprocessing.Queue | None = None
_result_queue:  multiprocessing.Queue | None = None
_ctx = multiprocessing.get_context('spawn')


def _ensure_worker() -> tuple:
    """確保子進程存活，若已死亡則重新啟動。回傳 (task_q, result_q, process)。"""
    global _worker_process, _task_queue, _result_queue

    if _worker_process is None or not _worker_process.is_alive():
        _task_queue   = _ctx.Queue()
        _result_queue = _ctx.Queue()
        _worker_process = _ctx.Process(
            target=worker_loop,
            args=(_task_queue, _result_queue),
            daemon=True,
        )
        _worker_process.start()

    return _task_queue, _result_queue, _worker_process


def shutdown_worker():
    """應用程式關閉時呼叫，清理子進程。"""
    global _worker_process, _task_queue
    if _worker_process and _worker_process.is_alive():
        try:
            _task_queue.put(('quit',))
            _worker_process.join(timeout=3)
        except Exception:
            pass
        if _worker_process.is_alive():
            _worker_process.kill()


class SeparatorProcess(QThread):
    progress  = Signal(str, int)                        # (message, percent)
    finished  = Signal(dict, float, str, str, object)  # result, tempo, key, bpm_source, beat_times
    error     = Signal(str)
    cancelled = Signal()

    def __init__(self, input_path: str, stems: list, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.stems = stems
        self._killed = False

    def cancel(self):
        """立即殺死子進程，CPU 使用率馬上下降。下次分源會自動重啟。"""
        global _worker_process
        self._killed = True
        if _worker_process and _worker_process.is_alive():
            _worker_process.kill()
            _worker_process.join(timeout=2)
            _worker_process = None  # 標記需要重啟

    def run(self):
        """QThread 主體：送任務給持久化子進程，輪詢結果。"""
        self._killed = False
        task_q, result_q, proc = _ensure_worker()

        # 送出任務
        task_q.put(('run', self.input_path, self.stems))

        tmp_path = None
        try:
            while True:
                if self._killed:
                    self.cancelled.emit()
                    return

                try:
                    msg = result_q.get(timeout=0.1)
                except Exception:
                    # timeout — 檢查子進程是否意外死亡
                    if not proc.is_alive():
                        if not self._killed:
                            self.error.emit('分源子進程意外終止')
                        else:
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
