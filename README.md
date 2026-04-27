# 音樂分源程式

自動將音樂拆分為人聲、鼓、貝斯、吉他、鋼琴、其他六條音軌，並提供混音播放、音量調整、MP3 下載、BPM/調性偵測、MIDI 分析、簡譜與五線譜生成功能。

採用淺色儀表板風格 UI（Indigo 主色調），波形圖支援點擊／拖曳跳轉播放位置，播放引擎使用低延遲模式以提升按鍵響應速度。

---

## 環境需求

- Python 3.10 以上
- NVIDIA GPU（選用，有則分源速度大幅提升）
- FFmpeg（MP3 匯出必要）

---

## 安裝步驟

### 方法一：一鍵安裝（推薦）

直接雙擊 **`setup.bat`**，腳本會自動：

1. 檢查 Python 3.10+，沒有則從 python.org 自動下載安裝
2. 檢查 FFmpeg，沒有則從官方直接下載並解壓至 `C:\ffmpeg\`
3. 偵測 NVIDIA GPU，有則自動安裝 CUDA 版 PyTorch（分源速度提升 10–20 倍）
4. 安裝所有 Python 套件（已裝的自動跳過）
5. 驗證安裝結果，並顯示各軟體安裝路徑

> 首次安裝需下載 PyTorch、Demucs 等大型套件，視網路速度約需 10–30 分鐘。

---

### 方法二：手動安裝

**步驟 1 — 安裝 FFmpeg**

手動下載後將 `bin` 資料夾加入系統 `PATH`，或解壓至 `C:\ffmpeg\`。

**步驟 2 — 安裝 Python 套件**
```bash
pip install -r requirements.txt
```

---

### 執行程式

```bash
python main.py
```
或雙擊 **`start.bat`**。

> **首次執行**會自動下載 Demucs `htdemucs_6s` 模型（約 300 MB），請確保網路連線正常。

---

## 功能說明

### 主頁面

1. 拖曳音樂檔案至畫面，或點擊選擇檔案
2. 支援格式：MP3、WAV、FLAC、M4A
3. 點擊「開始分離」（自動分離全部六條音軌）

---

### 分源結果頁（Mixer）

分源完成後進入 Mixer 頁面，每條音軌顯示為一列：

| 元件 | 說明 |
|------|------|
| 波形圖 | 顯示音訊振幅，播放時有進度線；可點擊或左右拖曳跳轉播放位置 |
| ▶ 播放 | 獨立播放該音軌（同時只允許一個來源播放） |
| M | 靜音（Mute）—整體播放時排除此軌 |
| S | 獨奏（Solo）—整體播放時只聽此軌 |
| 音量滑桿 | 0–150%，即時調整 |
| ⬇ MP3 | 下載此音軌（套用目前音量，MP3 320kbps） |
| ♪ MIDI | 人聲軌專屬：開啟 MIDI 分析視窗 |
| 節拍器列 | 開關節拍器、調整音量；速度由整體控制列的 BPM 決定 |

### 整體控制列

| 元件 | 說明 |
|------|------|
| ▶ 整體播放 | 所有音軌同步混音播放 |
| 進度條 | 可拖曳跳轉播放位置 |
| 速度 | 分源後優先以鼓軌偵測 BPM（精度較高），無鼓則退回原始混音；可手動調整 |
| 調性 | 分源後自動偵測調性，下拉選單以偵測調性為中心，往上 +8 半音（升記號）、往下 −8 半音（降記號）；切換後立即以 RubberBand 高品質移調，前段先用相位聲碼器即時預覽 |
| 整體音量 | 疊加在各軌音量之上 |
| ⬇ 下載混音 MP3 320k | 依目前音量/靜音狀態混音後下載 |

---

### MIDI 分析視窗（人聲軌專屬）

點擊人聲軌的「♪ MIDI」按鈕後開啟，功能如下：

| 功能 | 說明 |
|------|------|
| 音高分析 | 純 numpy FFT 自相關法偵測音高（monophonic），music21 量化節奏 |
| 波形顯示 | 分析完成後顯示人聲音軌波形；可點擊或拖曳跳轉 MIDI 播放位置 |
| ▶ 播放 MIDI | 播放由分析結果合成的 MIDI 音頻（三角波合成）；音符依原始時間軸對齊，不會有累積偏差 |
| 📜 五線譜 | 在瀏覽器開啟五線譜（verovio 渲染 SVG） |
| ♩ 簡譜 | 在瀏覽器開啟簡譜（matplotlib 渲染 PNG） |
| 調性 / 速度 | 分析完成後顯示於右上角 chip；沿用 Mixer 偵測結果，如需調整請返回 Mixer |
| 音量 | MIDI 播放音量可獨立調整（0–150%） |

> 分析過程：沿用 Mixer 的 BPM/調性 → FFT 自相關音高偵測 → 音符分割 → music21 節奏量化

---

### 五線譜視窗

- 使用 **music21** 建立樂譜資料，**verovio** 渲染為 SVG
- 渲染完成後自動以**系統預設瀏覽器**開啟（Chrome / Edge / Firefox 均可）
- 標題顯示來源檔案名稱（不含副檔名）

---

### 簡譜視窗

- 使用 **music21** 量化節奏（支援三連音、切分音）
- **matplotlib** 渲染為 PNG，嵌入 HTML 後以**系統預設瀏覽器**開啟
- 調性與速度直接沿用 MIDI 視窗的設定（如需調整，請在 Mixer 或 MIDI 視窗修改後重新開啟）
- 標題顯示來源檔案名稱（不含副檔名）

> **注意：** 自動轉譜準確度受錄音品質影響，建議以人聲音軌為主，複雜裝飾音等需人工校正。

---

## 硬體建議

| 設備 | 分源時間（4 分鐘歌曲） |
|------|----------------------|
| NVIDIA GPU（CUDA） | 約 1–3 分鐘 |
| Apple M 系列（MPS） | 約 3–5 分鐘 |
| 僅 CPU | 約 5–15 分鐘 |

---

## 專案結構

```
music-splitter/
├── main.py                  # 程式進入點
├── requirements.txt         # 依賴套件
├── core/
│   ├── separator.py         # Demucs 分源（背景執行緒）
│   ├── player.py            # 多軌同步播放引擎
│   ├── mixer.py             # 混音邏輯
│   ├── exporter.py          # MP3 匯出
│   ├── transcriber.py       # FFT 自相關音高偵測 + music21 節奏量化 → JianpuNote
│   ├── jianpu_renderer.py   # 簡譜渲染（matplotlib）
│   ├── staff_renderer.py    # 五線譜渲染（music21 + verovio → SVG）
│   ├── midi_synth.py        # MIDI 合成（三角波）
│   └── piano_roll.py        # Piano Roll 圖（備用）
└── ui/
    ├── main_window.py       # 主視窗
    ├── result_view.py       # Mixer 頁面
    ├── track_channel.py     # 單一音軌列
    ├── waveform_widget.py   # 波形圖 Widget
    ├── progress_dialog.py   # 分源進度
    ├── midi_view.py         # MIDI 分析視窗
    ├── jianpu_view.py       # 簡譜視窗
    ├── score_view.py        # 五線譜視窗
    └── styles.qss           # 淺色主題樣式（Indigo 主色調）
```

---

## 建置獨立執行檔（Windows .exe）

雙擊 **`build.bat`**，選擇 CPU 或 GPU 版本，腳本會自動完成所有步驟：

1. 安裝對應版本的 PyTorch（CPU 或 CUDA）
2. 安裝 PyInstaller
3. 清除舊的建置資料
4. PyInstaller 打包
5. 複製 FFmpeg（如系統已安裝）

| 版本 | 大小 | 適用對象 |
|------|------|---------|
| CPU | ~700 MB | 所有 Windows 電腦 |
| GPU | ~1.6 GB | 有 NVIDIA GPU，分源速度快 10–20 倍 |

| 輸出 | 位置 |
|------|------|
| 執行檔資料夾 | `dist\MusicSplitter\` |
| 主程式 | `dist\MusicSplitter\MusicSplitter.exe` |

> 直接將整個 `dist\MusicSplitter\` 資料夾複製給使用者即可，不需要安裝任何額外軟體。

---

## 常見問題

**Q：安裝腳本 setup.bat 執行沒有反應或閃退？**
A：請用滑鼠右鍵點 `setup.bat` → 「以系統管理員身分執行」，部分系統安裝 winget 套件需要管理員權限。

**Q：出現「Couldn't find ffmpeg」警告？**
A：FFmpeg 尚未安裝或未加入 PATH。執行 `setup.bat` 會自動處理；或手動執行 `winget install ffmpeg`。

**Q：分源速度很慢？**
A：未偵測到 CUDA GPU，目前以 CPU 執行。請確認已安裝對應版本的 PyTorch（含 CUDA）。

**Q：五線譜/簡譜結果不準確？**
A：自動轉譜為估算結果。可在 Mixer 頁面或 MIDI 視窗調整調性與速度後重新開啟。複雜裝飾音、滑音需人工校正。

**Q：首次執行卡住？**
A：正在下載 Demucs 模型（約 300 MB），請耐心等待並確保網路連線穩定。

**Q：五線譜視窗打開後沒有內容？**
A：請確認已安裝 `music21` 與 `verovio`（`pip install music21 verovio`），且系統有安裝瀏覽器。
