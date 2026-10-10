# Machine Policy：Inspection Robot + Active Perception

## 目前狀態

Project 尚未開始，不做任何環境安裝，也不主動占用 Mac heavy lock 或遠端 GPU lock。

## 正式開始時的建議環境

ROS 2 Jazzy 的主要目標環境是 Ubuntu 24.04。Gazebo Harmonic 與 Jazzy 配套使用。

目前既有遠端 GPU 主機是：

```text
Mac
→ Tailscale / SSH
→ Windows host (`gpu-server`)
→ WSL2 `Ubuntu-22.04`
→ RTX 5070 Ti 16GB
```

**不要為了這個 Project 直接污染、升級或改造成 ROS 24.04 環境。**

正式開始時 ROS / Gazebo 優先使用獨立 Ubuntu 24.04 環境（實機 / 新 WSL distro / VM，依當時條件決定）。既有 `Ubuntu-22.04` 主要保留給共享 CUDA heavy compute。

## Mac

Mac 可用於：

- code / docs / tests
- dataset / metrics analysis
- 非 ROS-specific Python tooling

不要預設 Mac 是正式 ROS/Gazebo benchmark 主機。

## RTX 5070 Ti

只有以下工作真正需要時才送到遠端 GPU：

- detector training / fine-tuning
- heavy batch inference
- CUDA-specific profiling / evaluation

ROS / Gazebo simulation、teleport harness、grader、Rule-based NBV 等不因為有 GPU 就自動搬到 `gpu-server`。

## GPU Hard Lock

正式 Heavy GPU 工作必須和 Text-to-SQL、LLM Serving Lab 共用同一把 WSL lock：

```text
/tmp/ai-portfolio-gpu.lock
```

正式 Heavy GPU 命令必須使用 `flock -n` 包住。

執行前可先檢查：

```bash
ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- bash -lc "nvidia-smi"'
```

若拿不到 lock：

- 不得搶鎖。
- 不得刪除 lock。
- 不得終止其他 Project 的 process。
- 將 GPU 步驟記為 blocked / deferred，改做本 Project 其他可完成的 Core 工作。

一般 code、tests、小型 smoke test、資料處理不需要 GPU lock。

## Mac / Docker 資源規則

- 不碰其他 Project 的 Docker container / network / volume。
- 不使用其他 Project 的 Mac heavy lock，除非未來正式 benchmark 設計明確需要並另寫規則。
- 不做全域 Docker prune / restart 來解決本 Project 問題。

## Credential 安全

只使用已設定好的：

```bash
ssh gpu-server
```

不得要求、讀取、保存或搜尋 SSH 密碼、私鑰、sudo 密碼、Tailscale key、GitHub token 或其他 credential。

## 遠端不可用

若桌機關機、SSH 失敗或 GPU lock 被占用：

- GPU 工作標記 blocked / deferred。
- 更新 `NEXT.md`。
- 繼續 simulation、dataset、grader、policy、analysis、tests 等可在其他環境完成的 Core 工作。
- 不得把整個 Project 停掉。
