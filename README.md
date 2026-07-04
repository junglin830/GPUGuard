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

1. 即時顯示 GPU 使用率與 VRAM 佔用，逼近滿載時介面會變色警示（橘色 85%+ / 紅色 95%+）。
2. 列出目前**佔用 VRAM 最多的各個程式**（per-process breakdown）——關鍵技術點：改用 Windows
   效能計數器 `\GPU Process Memory(*)\Dedicated Usage`（跟工作管理員「詳細資料」分頁背後用的
   是同一份資料源），繞開 nvidia-smi 在 GeForce 上的限制，可以拿到跟工作管理員一致的真實數字。
3. 一鍵「結束此程式」按鈕——只砍掉真正佔滿 VRAM 的那個程式，VRAM 立刻釋放，不必整台重開機。
4. 內建系統關鍵程序保護清單（`dwm`/`explorer`/`csrss`/`lsass`/`svchost` 等），這些名稱一律拒絕
   透過本工具結束，避免誤殺桌面/系統程序造成當機。

## 架構

- `gpu_guard_server.py`：純 Python 標準庫（`http.server` + `subprocess` + `threading`），每 2 秒
  透過 `nvidia-smi`（整體資訊）與 PowerShell `Get-Counter`（per-process VRAM）收集一次資料，
  在 `:8091` 提供 `GET /stats` 與 `POST /kill` 兩個極簡 API。無需安裝任何第三方套件。
- `gpu_guard.html`：純前端（無框架），深色科技風介面，每 2 秒輪詢一次 `/stats`，可獨立用瀏覽器打開，
  或掛在任何靜態網站/內部入口網頁下面當一張卡片。

## 使用方式

```
pythonw gpu_guard_server.py   # 背景啟動後端，不會跳出黑窗
```
然後用瀏覽器開 `gpu_guard.html`（本機開發時後端固定在 `http://localhost:8091`）。

## 限制

- 目前僅在單張 NVIDIA GPU 的 Windows 環境測試（RTX 5060 Ti 16G / Windows 11）。
- per-process VRAM 讀取仰賴 Windows 效能計數器，理論上其他有安裝 NVIDIA 驅動的 Windows 機器都能用，
  但未在多 GPU / AMD / Linux 環境測試過。
- 「結束程式」是強制結束（`taskkill /F`），該程式若有未存檔的工作會直接遺失，使用前請自行確認。

## 授權

MIT License —— 自由使用、修改、散布。歡迎 PR / Issue。
