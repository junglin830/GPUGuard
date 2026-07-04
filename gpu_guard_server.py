#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Guard - 輕量GPU滿載監控+一鍵釋放小工具 (2026-07-04)

問題背景：
  某些GPU重度程式(如ComfyUI長時間reload模型)會把VRAM吃到接近滿載，
  導致後續生圖/推論卡死，過去唯一解法是重開整台電腦，非常麻煩。

治標解法(本工具做的事)：
  1. 即時顯示GPU使用率與VRAM佔用(逼近滿載會標紅警示)。
  2. 列出目前佔用VRAM最多的各個程式(per-process breakdown)。
  3. 提供「結束該程式」按鈕，只需砍掉真正佔滿VRAM的那個程式，
     不必整台重開機，就能立刻釋放VRAM繼續工作。

技術筆記：
  - nvidia-smi在GeForce消費級顯卡上 --query-compute-apps 的 used_memory 欄位固定回傳
    [N/A]（這是Windows WDDM驅動的已知限制，不是bug），無法用nvidia-smi拿到per-process VRAM。
  - 改用Windows效能計數器 `\GPU Process Memory(*)\Dedicated Usage`（跟工作管理員內部用的
    是同一套資料源），可以拿到跟工作管理員「詳細資料」分頁一致的per-process VRAM數字。
"""
import json
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8091
POLL_SECONDS = 2

# 保護清單：這些程式名稱絕不允許透過本工具結束，避免誤殺桌面/系統關鍵程序
PROTECTED_NAMES = {
    "dwm", "explorer", "csrss", "wininit", "winlogon", "services", "lsass",
    "svchost", "system", "smss", "spoolsv", "taskhostw", "shellexperiencehost",
    "searchhost", "startmenuexperiencehost", "textinputhost", "fontdrvhost",
    "ctfmon", "sihost", "runtimebroker", "registry", "memory compression",
}

_latest = {"gpu": None, "processes": [], "ts": None, "error": None}
_lock = threading.Lock()


def _run_ps(cmd):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return r.stdout.strip()


def collect_once():
    gpu = None
    err = None
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw,power.limit",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.strip()
        if out:
            p = [x.strip() for x in out.split(",")]
            gpu = {
                "name": p[0], "memtotal": int(float(p[1])), "memused": int(float(p[2])),
                "util": int(float(p[3])), "temp": int(float(p[4])),
                "power": float(p[5]), "powerlimit": float(p[6]),
            }
    except Exception as e:
        err = "nvidia-smi失敗: " + str(e)

    processes = []
    try:
        ps_cmd = (
            "$c=Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue;"
            "if($c){$c.CounterSamples | Where-Object {$_.CookedValue -gt 20MB} | ForEach-Object {"
            "  $m=[regex]::Match($_.InstanceName,'pid_(\\d+)');"
            "  if($m.Success){"
            "    $pid_=$m.Groups[1].Value; $p=Get-Process -Id $pid_ -ErrorAction SilentlyContinue;"
            "    if($p){ [pscustomobject]@{pid=[int]$pid_; name=$p.ProcessName; mb=[math]::Round($_.CookedValue/1MB,0)} }"
            "  }"
            "} | Group-Object pid | ForEach-Object { $_.Group[0] } | Sort-Object mb -Descending | ConvertTo-Json -Compress"
            "}"
        )
        raw = _run_ps(ps_cmd)
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            processes = data or []
    except Exception as e:
        err = (err + "; " if err else "") + "per-process查詢失敗: " + str(e)

    with _lock:
        _latest["gpu"] = gpu
        _latest["processes"] = processes
        _latest["ts"] = time.strftime("%H:%M:%S")
        _latest["error"] = err


def collector_loop():
    while True:
        try:
            collect_once()
        except Exception as e:
            with _lock:
                _latest["error"] = "collector例外: " + str(e)
        time.sleep(POLL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 靜音，避免主控台噴log(本服務本來就無視窗執行)

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        if self.path == "/stats":
            with _lock:
                self._send_json(dict(_latest))
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/kill":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                pid = int(body.get("pid"))
            except Exception:
                self._send_json({"ok": False, "msg": "請求格式錯誤"}, 400)
                return
            with _lock:
                proc_list = list(_latest["processes"])
            target = next((p for p in proc_list if p.get("pid") == pid), None)
            name = (target or {}).get("name", "").lower()
            if name in PROTECTED_NAMES:
                self._send_json({"ok": False, "msg": f"{name} 是系統關鍵程序，禁止結束"}, 403)
                return
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                timeout=6, creationflags=subprocess.CREATE_NO_WINDOW)
                self._send_json({"ok": True, "msg": f"已結束 PID {pid} ({name})"})
            except Exception as e:
                self._send_json({"ok": False, "msg": str(e)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    t = threading.Thread(target=collector_loop, daemon=True)
    t.start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"GPU Guard server running on :{PORT}")
    server.serve_forever()
