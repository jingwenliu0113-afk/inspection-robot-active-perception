# 事件紀錄：本專案的測試與 rust-hnsw 正式 benchmark `text-6` 重疊（2026-10-16）

- **狀態**：紀錄完成，**交由 Rust HNSW 專案重新評估、必要時重跑**（使用者 2026-10-16 指示）。本專案不跨專案操作：沒有讀寫 rust-hnsw 的檔案、沒有碰它的行程或鎖。
- **影響範圍（本專案）**：無。v5 的正式步驟都在鎖釋放後才進行（decision 035）。

## 1. 時間線（Mac 本機時間，UTC+8）

| 時間 | 事件 |
|---|---|
| 03:13:33 | rust-hnsw 以 `tools/with-mac-lock` 取得 `/tmp/ai-portfolio-mac-heavy.lock`（owner pid 44410）。命令：`./scripts/formal_batch.sh results/batches/text-6.log --powermode 2 --skip-idle benchmarks/configs/text-formal-1-m16-order.toml benchmarks/configs/text-formal-2-m16-seeds-efc400.toml benchmarks/configs/text-formal-3-m8-efc100.toml benchmarks/configs/text-formal-4-highm-scaling.toml` |
| 約 03:14 | 本專案執行完整測試 `uv run pytest -q -p no:warnings -x`（v5 凍結前的檢查）。執行前的 load average 2.43 / 3.82 / 5.42 |
| 約 03:14–03:17 | 測試執行中（同一組測試在負載低時約 1.5 分鐘；當時估計 1.5–3 分鐘）。主要是單一 Python 行程，部分測試的 numpy / torch 可能使用多執行緒 |
| 03:17 前後 | 測試結束後，本專案才讀到鎖的持有者並發現重疊 |
| 03:17–07:52 | 本專案只做文件與 git 操作；以背景輪詢（每 60 秒 `[ -e lock ]`）等待 |
| 07:52:50 | 鎖釋放。之後本專案才產生 v5 正式資料、渲染、偵測與正式評測（至 10:38:35）與畫圖（至 10:40:56） |
| 10:41:29 | rust-hnsw 再次取得鎖（owner pid 4542，`bash results/profiles/gate-glove-plan.sh && bash results/profiles/gate-text-plan.sh`） |
| 約 10:42–10:44 | 本專案在鎖被持有期間執行了輕量操作：README 數字測試（12 個測試，只讀 JSON，約 1 秒）、`ruff check`、`seal verify`（雜湊約 115 個檔案）與 git commit / push。完整測試因檢查正確中止而沒有執行 |
| 11:25:36 | 鎖釋放；本專案才執行完整測試（277 passed） |

## 2. 原因

本專案的鎖檢查寫成「鎖存在就印出警告」，後面的命令仍照常執行：

```bash
ls /tmp/ai-portfolio-mac-heavy.lock 2>/dev/null && echo LOCK HELD; uptime; uv run pytest ...
```

輸出中出現了 `LOCK HELD`，但 pytest 照常執行。

## 3. 給 Rust HNSW 專案的資訊（由該專案判斷）

- 可能受影響的是 `text-6` 批次**開頭約 3 分鐘**，也就是 03:13:33 之後最早執行的量測。依命令順序，最可能是 `text-formal-1-m16-order.toml`。
- 干擾強度：本專案大約多占用 1 個 CPU 核心（短時間可能更多），沒有使用 GPU，也沒有大量磁碟 I/O。
- 建議由 Rust HNSW 專案對照 `results/batches/text-6.log` 的時間戳，判斷受影響的 run 是否需要重跑。
  若該專案的正式協定要求整批在無干擾下完成，也可能需要整批重跑。這是該專案的決定。
- 10:41 開始的 `gate-*-plan.sh` 期間，本專案只有上表所列的秒級操作。

## 4. 本專案的修正

1. 檢查改為「鎖存在就中止」：

```bash
[ -e /tmp/ai-portfolio-mac-heavy.lock ] && { cat /tmp/ai-portfolio-mac-heavy.lock/owner.txt; exit 1; }
```

2. v5 的 runner 內建檢查（`activeperception/v5/maclock.py`）：開發 runner 被持有時跳過 job，正式 runner 等鎖釋放再開始下一個 job。
3. 其他專案可能不取鎖就執行重工作（例如本機 LLM 伺服器占用 Apple GPU），所以新增預檢：`uv run python -m activeperception.preflight [--gpu]`。
   它同時檢查鎖、CPU 負載、記憶體與 Apple GPU 使用率，任何一項過高就不啟動（`activeperception/preflight.py`）。
4. 規則寫進 `MACHINE_POLICY.md` 與 `CLAUDE.md`。
