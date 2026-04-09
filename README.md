# 音樂分源程式

自動將音樂拆分為人聲、鼓、貝斯、吉他、鋼琴、其他六條音軌，並提供混音播放、音量調整、MP3 下載與簡譜生成功能。

---

## 環境需求

- Python 3.10 以上
- NVIDIA GPU（選用，有則分源速度大幅提升）
- FFmpeg（MP3 匯出必要）

---

## 安裝步驟

### 1. 安裝 FFmpeg

**方法一（推薦）：**
```bash
winget install ffmpeg
```

**方法二（手動）：**
1. 前往 https://ffmpeg.org/download.html 下載 Windows 版本
2. 解壓後將 `bin` 資料夾路徑加入系統環境變數 `PATH`
3. 或直接解壓至 `C:\ffmpeg\`（程式會自動偵測此路徑）

安裝完成後重新開啟終端機。

---

### 2. 安裝 Python 套件

```bash
cd D:\claudeCode\music-splitter
pip install -r requirements.txt
```

> 首次安裝時間較長（需下載 PyTorch、Demucs 等大型套件）。

---

### 3. 執行程式

```bash
python main.py
```

> **首次執行**會自動下載 Demucs `htdemucs_6s` 模型（約 300 MB），請確保網路連線正常。

---

## 功能說明

### 主頁面

1. 拖曳音樂檔案至畫面，或點擊選擇檔案
2. 支援格式：MP3、WAV、FLAC、M4A
3. 勾選要分離的音軌（預設全選）
4. 點擊「開始分離」

### 分源結果頁（Mixer）

分源完成後進入 Mixer 頁面，每條音軌顯示為一列：

| 元件 | 說明 |
|------|------|
| 波形圖 | 顯示音訊振幅，播放時有進度線 |
| ▶ 播放 | 獨立播放該音軌（不受 M/S 影響） |
| M | 靜音（Mute）—整體播放時排除此軌 |
| S | 獨奏（Solo）—整體播放時只聽此軌 |
| 音量滑桿 | 0–150%，即時調整 |
| ⬇ MP3 | 下載此音軌（套用目前音量，MP3 320kbps） |
| ♩ 簡譜 | 自動分析音高並生成簡譜（適合人聲軌） |

### 整體控制列

| 元件 | 說明 |
|------|------|
| ▶ 整體播放 | 所有音軌同步混音播放 |
| 進度條 | 可拖曳跳轉播放位置 |
| 整體音量 | 疊加在各軌音量之上 |
| ⬇ 下載混音 MP3 320k | 依目前音量/靜音狀態混音後下載 |

### 簡譜生成

點擊任意音軌的「♩ 簡譜」按鈕後：

1. 程式自動偵測音高、速度、調性
2. 生成簡譜圖像顯示於視窗中
3. 可手動調整「調性」與「速度」後點擊「重新生成」
4. 點擊「⬇ 儲存 PNG」匯出圖片

> **注意：** 自動轉譜準確度受錄音品質影響，建議以人聲音軌為主，結果可能需要人工微調。

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
├── PLAN.md                  # 規劃文件
├── README.md
├── core/
│   ├── separator.py         # Demucs 分源（背景執行緒）
│   ├── player.py            # 多軌同步播放引擎
│   ├── mixer.py             # 混音邏輯
│   ├── exporter.py          # MP3 匯出
│   ├── transcriber.py       # 音高偵測 → 簡譜音符
│   └── jianpu_renderer.py   # 簡譜渲染（matplotlib）
└── ui/
    ├── main_window.py       # 主視窗
    ├── result_view.py       # Mixer 頁面
    ├── track_channel.py     # 單一音軌列
    ├── waveform_widget.py   # 波形圖
    ├── progress_dialog.py   # 分源進度
    ├── jianpu_view.py       # 簡譜視窗
    └── styles.qss           # 深色主題樣式
```

---

## 建置 Windows 安裝檔

若要將程式打包成 `.exe` 安裝檔，需要額外安裝以下工具：

| 工具 | 用途 | 下載 |
|------|------|------|
| PyInstaller | 將 Python 打包成執行檔 | `pip install pyinstaller` |
| Inno Setup 6 | 建立 Windows 安裝精靈 | https://jrsoftware.org/isinfo.php |

### 建置步驟

```bash
# 確認在虛擬環境中，且已安裝所有套件
pip install -r requirements.txt

# 執行建置腳本（一鍵完成所有步驟）
build.bat
```

建置腳本會依序執行：
1. 安裝 / 升級 PyInstaller
2. 清除舊的建置資料
3. PyInstaller 打包（約 10–20 分鐘）
4. Inno Setup 建立安裝檔

### 輸出位置

| 輸出 | 位置 |
|------|------|
| 執行檔資料夾 | `dist\MusicSplitter\` |
| Windows 安裝檔 | `dist\installer\音樂分源程式_安裝檔_v1.0.0.exe` |

> **注意：** 因包含 PyTorch 與 Demucs，打包後總大小約 **500–800 MB**，安裝檔壓縮後約 **300–500 MB**，屬正常現象。

### 相關檔案

| 檔案 | 說明 |
|------|------|
| `build.spec` | PyInstaller 設定（可調整排除套件、圖示等） |
| `installer.iss` | Inno Setup 腳本（可調整安裝路徑、捷徑等） |
| `build.bat` | 一鍵建置腳本 |

---

## 常見問題

**Q：出現「Couldn't find ffmpeg」警告？**
A：FFmpeg 尚未安裝或未加入 PATH，請依照上方安裝步驟操作。

**Q：分源速度很慢？**
A：未偵測到 CUDA GPU，目前以 CPU 執行。確認已安裝 NVIDIA 驅動與對應版本的 PyTorch（含 CUDA）。

**Q：簡譜結果不準確？**
A：自動轉譜為估算結果，可在簡譜視窗中手動調整調性與速度後重新生成。複雜裝飾音、滑音等需人工校正。

**Q：首次執行卡住？**
A：正在下載 Demucs 模型（約 300 MB），請耐心等待並確保網路連線穩定。
