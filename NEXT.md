# NEXT

## 目前位置

**Future / Parked Project。尚未開始。**

不要因為這個資料夾存在就自動建立 ROS workspace、下載 Gazebo assets 或開始實作。

## 使用者未來說「開始 robot 專案」後

1. 先確認正式執行環境（Ubuntu 24.04 / ROS 2 Jazzy / Gazebo Harmonic）。
2. 寫 environment/version decision log。
3. 若 detector training / heavy GPU inference 需要 RTX，先驗證 `ssh gpu-server` 與共享 `/tmp/ai-portfolio-gpu.lock`，不得與其他 Project 同時占用 GPU。
4. 建立最小 world + camera + 三狀態 episode generator。
5. 先實作 deterministic teleport viewpoint harness。
6. 寫 grader：`present / absent / inconclusive`。
7. 做 Single View baseline，再做 Random NBV。
8. Rule-based NBV 必須在正式 test 前凍結規則。

## Blocked

無。這是刻意暫停，不是 blocker。
