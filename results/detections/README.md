# 偵測快取（Detection caches）

各次評估實際使用的 detector 輸出，2026-10-30 從本機 `runs/` 複製進 repo，路徑與 `runs/` 相同（`results/detections/<X>` ↔ `runs/<X>`）。
`core`、`holdout` 的快取原本就在 [`results/core/`](../core/)、[`results/holdout/`](../holdout/)，內容與本機版本逐位元相同，這裡不重複。

The detector outputs each evaluation actually used, copied from the local `runs/` on 2026-10-30 with the same
relative paths. With these files the formal results of v3–v5, R0b and Advanced B can be recomputed bit for bit from
re-rendered frames, without re-running the detector (CPU and GPU confidences may differ by up to ~0.004).

| 路徑 | 內容 |
|---|---|
| `<namespace>/detector-v1.jsonl` | `detector-v1`（torchvision FRCNN-MobileNetV3）在該 namespace 的模擬影像上的偵測：`v3` / `v3-dx` / `v4` / `v4-dx` / `v5` / `v5-dx` / `r0b`（正式）與 `v3-dev` / `v3-dev-dx` / `r0b-dev` / `pilot` / `nav-b0*`（開發） |
| `nav-b1/`、`nav-b2/teleport-detector-v1.jsonl` | Advanced B 的 teleport 對照組偵測 |
| `detv2/` | detector-v2（decision 027 / 030）：真實照片 dev / test 與 `detv2-sim` 上 v1 / v2 的偵測，三個訓練設定在 dev 上的偵測；E0（decision 036）用的 `base/v3-dev*.jsonl` |

- 只有偵測輸出（影像 ID、框、信心值），**不含照片**；照片的來源與授權見 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。
- detector-v2 的權重（`runs/detv2/*/weights.pth`）不在 repo 內，只在私人備份中（見 [docs/restore-from-backup.md](../../docs/restore-from-backup.md)）。
- 已釘進 `SEALED.sha256`：不得修改。要還原到 runner 預設讀取的位置：`rsync -a results/detections/ runs/`。
