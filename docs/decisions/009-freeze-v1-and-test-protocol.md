# 009 — 凍結 `decision-v1`、`rule-nbv-v1`、正式 budget 與 test / Gate 協定

- **日期**：2026-10-13
- **狀態**：**凍結**。之後任何改動只能以新版本號（v2）另開 decision log，並在新一輪 test 報告、保留 v1 結果。
- **是否在看過正式結果後才新增 / 修改**：否。寫於 `core` test split 跑任何 policy 之前；
  依據只有 train（調參）與 val（檢查）結果（`results/tuning/`）。

## 1. 凍結的參數（依 decision 008 協定選出）

### `decision-v1`（shared decision rule，四個方法共用）

| 參數 | v0 | **v1** |
|---|---|---|
| `tau_present` | 0.6 | **0.7** |
| `tau_absent` | 0.3 | **0.05** |
| `n_sectors` | 6 | **8** |
| `min_coverage` | 0.5（3 / 6） | **0.25（2 / 8）** |
| `effective_zone_fraction` | 0.5 | **0.3** |

結構不變（decision 004）。train 上 480 組中 435 組可行、5 組平手，依平手規則（覆蓋要求較嚴者、`tau_present` 較大者）選出。
`tau_absent` 的作用：任何 ≥ 0.05 的 fire hydrant 候選都會阻止宣告 absent（train 上 `tau_absent = 0.1` 即出現 false absent）。

### `rule-nbv-v1`

| 權重 | v0 | **v1** |
|---|---|---|
| `w_coverage`（扇區覆蓋增益） | — | **0** |
| `w_visibility`（depth 障礙物圖預測的 zone 可見度） | — | **1.0** |
| `w_novelty` | 1.0 | **0.5** |
| `w_attraction` | 1.0 | **0** |
| `w_unobstructed` | 0.5 | **0** |

train 上 192 組全部可行、140 組在最佳值 0.005 內，依平手規則（非零權重最少、平均視角數較少）選出。
其餘超參數（`tau_weak`、角度 σ 等）沿用 v0 預設值，但因權重為 0 不影響行為。

### 其他凍結項

- detector `detector-v1`（decision 005）、world `gen-v2` / `sdf-world-v2`、image `sha256:49d6e69b…`、labeling `label-v1`。
- Oracle NBV 使用 `decision-v1` 的扇區設定。
- Random NBV：run seeds **0–4**，報告以 5 個 seeds 的平均為主（每個 episode 的 correct 等旗標取 seed 平均後再彙總）。

## 2. 正式 budget（使用者 2026-10-13 決定）

**{1, 2, 3, 5}**（含初始視角）。另報 budget 1–8 的 success-vs-budget 曲線。
依據（val）：差異集中在 budget 2–3；budget ≥ 5 時四個方法 val accuracy 皆為 1.0。

## 3. Test 協定

- 資料：`data/episodes/gazebo-core.json` 的 `test` split（131 scene groups、524 episodes），只跑一次。
- 執行：`python -m activeperception.experiment test ...`；輸出目錄已存在時拒絕執行（防止「再跑一次看看」）。
- 指標（SPEC §7）：3-class accuracy、macro-F1、false-absent rate、false-present rate、inconclusive rate、avg viewpoints、
  ECE 與 reliability bins、visible / unobservable / absent 分層、success vs budget（1–8）、
  detector bbox 像素面積 / confidence 與成功率的關係。
- 不確定性：以 scene group 為 cluster 的 bootstrap（1000 次、seed 0、percentile 95% CI）；
  方法間比較用**成對**差異（同一批 episodes、同一組 bootstrap 重抽）。

## 4. Gate 判準（SPEC §10，預先登錄）

1. **Rule 穩定勝過 Random 與 Single**：在 budget 2 與 3，`rule − random` 與 `rule − single` 的 accuracy 成對差異 95% CI 下界都 > 0，
   且 rule 的 false-absent rate 不高於 random（同 budget）。budget 1 依定義相同；budget 5 預期飽和，只報告不判定。
2. **非 leakage**：`tests/test_leakage.py`（含 v1 特徵的 tripwire）與 replay label tripwire 通過；rule-NBV 只讀 deployable 觀測。
3. **殘餘失敗**：列出 rule 在 budget 2 / 3 判錯或 inconclusive 的 test episodes，依 GT 狀態與遮擋型態歸類，並確認可由 replay 重現。
4. **是否接近 oracle**：若每個正式 budget 的 `oracle − rule` accuracy 差 ≤ 0.02，或其 95% CI 含 0，判定「rule 已接近 oracle」——
   依 SPEC，此時**停止，不需要 RL**（Advanced C 不啟動）。

Gate 1–3 都成立才考慮 Advanced；即使成立，Advanced 也不是自動下一步（docs/EXPERIMENT_RULES.md），需由使用者決定。
