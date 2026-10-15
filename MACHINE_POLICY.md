# Machine Policy：Inspection Robot + Active Perception

## 目前狀態（2026-10-10）

Project 已啟動。環境決策見 `docs/decisions/001-environment-and-platform.md`。

## 機器分工

| 工作 | 機器 |
|---|---|
| code / tests / decision logs / metrics 分析 | Mac（Python 3.12，`uv`） |
| Gazebo Harmonic + ROS 2 Jazzy 模擬、teleport harness、pilot、正式 render | **Mac Docker Desktop（arm64 容器，Ubuntu 24.04，headless 軟體渲染）** |
| 上述容器在 arm64 失敗時的備援 | `gpu-server` 的 Docker Desktop 以 amd64 建同一份 Dockerfile（CPU 渲染，不需 GPU） |
| detector training / fine-tuning、heavy batch inference、CUDA profiling | `gpu-server` → WSL2 `Ubuntu-22.04` → RTX 5070 Ti，**必須取得 GPU lock** |

**不要為了這個 Project 污染、升級或改造 `Ubuntu-22.04`。** 它保留給三個 Project 共用的 CUDA heavy compute。若日後確定需要原生 24.04，用 `wsl --install -d Ubuntu-24.04` 另建 distro（需使用者操作），不動 22.04。

## Mac

Mac 是預設開發機，也是 Core 模擬的正式主機（容器化）。

- 正式平台記錄以 Dockerfile + image digest 為準，commit 進 repo。
- Gazebo 容器只用本 Project 自己的 image / container 名稱（`inspection-ap-*`），不碰其他 Project 的 container / network / volume，不做全域 `docker system prune`。
- 「heavy」看資源用量，不是正式與否（PORTFOLIO.md）：大批次 render、多 worker 的開發 / 正式評估、完整測試都算。執行前先確認 `/tmp/ai-portfolio-mac-heavy.lock` 沒被其他 Project 持有；被持有時不要跑，也不要搶鎖或刪鎖。本專案的開發工作不取鎖，只檢查。
- v5 起的 runner 內建檢查（`activeperception/v5/maclock.py`）：啟動前與每個 job 開始前各查一次，被持有的 job 跳過並標記 SKIPPED。其他 Project 也在跑時，worker 數用 6 以下。
- 若日後正式 benchmark 需要取 Mac heavy lock，另寫規則與 wrapper，不借用其他 Project 的 wrapper。

## RTX 5070 Ti

只有以下工作真正需要時才送到遠端 GPU：

- detector training / fine-tuning（Advanced A）
- heavy batch inference
- CUDA-specific profiling / evaluation

ROS / Gazebo simulation、teleport harness、grader、Rule-based NBV、小型 detector CPU 推論都不因為有 GPU 就搬到 `gpu-server`。

### GPU Hard Lock

正式 Heavy GPU 工作必須和 Text-to-SQL、LLM Serving Lab 共用同一把 WSL lock：

```text
/tmp/ai-portfolio-gpu.lock
```

正式 Heavy GPU 命令必須使用 `flock -n` 包住：

```bash
ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- bash -lc "flock -n /tmp/ai-portfolio-gpu.lock <heavy-command>"'
```

執行前先檢查 GPU 是否被占用：

```bash
ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- bash -lc "nvidia-smi"'
```

若拿不到 lock 或 `nvidia-smi` 顯示別的 Project 正在用：

- 不得搶鎖、不得刪除 lock、不得終止其他 Project 的 process。
- 將 GPU 步驟記為 blocked / deferred，改做本 Project 其他可完成的 Core 工作。

一般 code、tests、小型 smoke test、資料處理不需要 GPU lock。

## Credential 安全

只使用已設定好的：

```bash
ssh gpu-server
```

不得要求、讀取、保存或搜尋 SSH 密碼、私鑰、sudo 密碼、Tailscale key、GitHub token 或其他 credential。repo 內不得出現 WSL 使用者名稱等帳號資訊。

## 遠端不可用

若桌機關機、SSH 失敗或 GPU lock 被占用：

- GPU 工作標記 blocked / deferred。
- 更新 `NEXT.md`。
- 繼續 simulation、dataset、grader、policy、analysis、tests 等可在 Mac 完成的 Core 工作。
- 不得把整個 Project 停掉。
