# GPU Guard

輕量、零安裝依賴（純 Python 標準庫）的 GPU 滿載監控 + 一鍵釋放小工具。專為 Windows + NVIDIA 消費級顯卡（GeForce）設計。

## 問題 (Problem)

跑 ComfyUI、本地 LLM 等 GPU 重度工作時，VRAM 容易被某個程式（例如反覆 reload 模型的 ComfyUI）吃到接近滿載，
導致後續生圖/推論卡死或整台電腦變得極度緩慢。過去唯一的解法是**整台電腦重新開機**，非常浪費時間、也很煩。

更麻煩的是：在 GeForce 消費級顯卡上，`nvidia-smi --query-compute-apps=...,used_memory` 的
`used_memory` 欄位固定回傳 `[N/A]`（這是 Windows WDDM 驅動架構的已知限制，不是 bug），
所以沒辦法直接用 nvidia-smi 看出「到底是哪個程式吃走了 VRAM」。

## 治標解法 (Workaround, not a root fix)

這個工具**不解決**上游程式本身為什麼會把 VRAM 吃滿（那是各程式自己的資源管理問題，屬於治本，
需要個別排查），但它讓你**不用重開機**就能立刻恢復可用：

1. 即時顯示 GPU 完整數據：VRAM 佔用、使用率、功耗、溫度、核心時脈、風扇轉速。
2. **紅線標準 + 快臨界預警**（v1.3 新增）：每項指標都有明確定義的紅線/警戒門檻（見下表），
   逼近紅線時跳出警示條 + 音效提醒，不用一直盯著畫面看。
3. 列出目前**佔用 VRAM 最多的各個程式**（per-process VRAM + per-process GPU 使用率）——關鍵技術點：
   改用 Windows 效能計數器 `\GPU Process Memory(*)\Dedicated Usage` 與
   `\GPU Engine(*)\Utilization Percentage`（跟工作管理員「詳細資料」分頁背後用的是同一份資料源），
   繞開 nvidia-smi 在 GeForce 上的限制，可以拿到跟工作管理員一致的真實數字。
4. VRAM 佔比 ≥25% 的程式標記「主要嫌疑」（紅框發光），10-25% 標記「次要留意」（金框）。
5. 一鍵「結束此程式」按鈕——只砍掉真正佔滿 VRAM 的那個程式，VRAM 立刻釋放，不必整台重開機。
6. 內建系統關鍵程序保護清單（`dwm`/`explorer`/`csrss`/`lsass`/`svchost` 等），這些名稱一律拒絕
   透過本工具結束，避免誤殺桌面/系統程序造成當機。

### 紅線標準 (Redline thresholds)

| 指標 | 快臨界(警戒) | 紅線(危險) | 依據 |
|---|---|---|---|
| VRAM 佔用 | 75% | 90% | 實測ComfyUI單一模型常駐即佔約50%，多開/reload後迅速逼近滿載 |
| GPU 使用率 | 85% | 98% | 持續接近100%代表GPU無餘裕處理其他任務 |
| 溫度 | 75°C | 85°C | 消費級顯卡普遍在85-90°C區間開始熱降頻，抓85°C留緩衝 |
| 功耗 | 85% | 95% | 逼近功耗牆(power limit)代表已達散熱/供電上限 |

任一指標超過紅線：頁面頂端跳出紅色警示條 + 播放提示音（同一次警報只響一次，指標降回警戒線以下才會重置）。
75%-紅線之間：跳出金色「快臨界」提示條，不出聲，純視覺提醒。

門檻定義在 `gpu_guard.html` 的 `REDLINE` 常數物件中，可依實際機器/顯卡調整。

## 架構

- `gpu_guard_server.py`：純 Python 標準庫（`http.server` + `subprocess` + `threading`），每 2 秒
  透過 `nvidia-smi`（整體資訊：VRAM/使用率/溫度/功耗/時脈/風扇）與 PowerShell `Get-Counter`
  （per-process VRAM + per-process GPU 使用率）收集一次資料，在 `:8091` 提供
  `GET /stats` 與 `POST /kill` 兩個極簡 API。無需安裝任何第三方套件。
- `gpu_guard.html`：純前端（無框架），視覺風格對齊公司內部設計標竿（深色漸層+發光強調色，
  不使用綠色），每 2 秒輪詢一次 `/stats`，可獨立用瀏覽器打開，或掛在任何靜態網站/內部入口網頁下面當一張卡片。

## 使用方式

```
pythonw gpu_guard_server.py   # 背景啟動後端，不會跳出黑窗
```
然後用瀏覽器開 `gpu_guard.html`（本機開發時後端固定在 `http://localhost:8091`）。

## 限制

- 目前僅在單張 NVIDIA GPU 的 Windows 環境測試（RTX 5060 Ti 16G / Windows 11）。
- per-process 數據讀取仰賴 Windows 效能計數器，理論上其他有安裝 NVIDIA 驅動的 Windows 機器都能用，
  但未在多 GPU / AMD / Linux 環境測試過。
- 「結束程式」是強制結束（`taskkill /F`），該程式若有未存檔的工作會直接遺失，使用前請自行確認。
- 音效警報使用瀏覽器 Web Audio API，需要頁面已有使用者互動或瀏覽器允許自動播放音效才會生效。

## Changelog

- **v1.4** (2026-07-04)：所有紅線門檻皆採百分比計算(VRAM佔比/使用率/功耗佔比)，自動依每台電腦自己的GPU總量/功耗上限調整，不綁死在特定型號；新增每個監控程式的白話說明(PROC_DESC對照表，開源後歡迎PR擴充)；新增偵測不到nvidia-smi(非NVIDIA顯卡)時的友善提示訊息。
- **v1.3** (2026-07-04)：新增紅線標準 + 快臨界預警（視覺警示條+音效），VRAM/使用率/溫度/功耗四項皆有明確門檻定義，版本號顯示於頁面。
- **v1.2** (2026-07-04)：視覺全面重新設計，對齊公司內部設計標竿（深色漸層背景、發光強調色、卡片左側色條、脈動警示動畫）。
- **v1.1** (2026-07-04)：新增完整GPU數據（溫度/功耗/時脈/風扇）與 per-process GPU 使用率；修正模組docstring中`\U`被誤判為unicode跳脫字元導致的語法錯誤。
- **v1.0** (2026-07-04)：初版。VRAM/使用率監控 + per-process VRAM breakdown + 一鍵結束程式 + 系統關鍵程序保護清單。

## 授權

MIT License —— 自由使用、修改、散布。歡迎 PR / Issue。
