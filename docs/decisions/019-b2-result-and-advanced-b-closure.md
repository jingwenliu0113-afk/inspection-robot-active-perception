# 019 — B2 結果與 Advanced B 結案

- **日期**：2026-10-14
- **狀態**：已判定（Advanced B 完成）
- **是否在看過正式結果後才新增 / 修改**：是——本檔記錄 `nav-b2` 結果，依 decision 018 預先登錄的問題判定；沒有修改任何參數、判準或資料。

## 執行

- `nav-b2`：40 scene groups × 4 variants = 160 episodes（absent 80、unobservable 38、visible 42），新 split `nav-eval`，decision 018 之後產生。
- 960 次閉迴路執行（4 個方法、Random 3 seeds、budget 5），commit `4955086`；980 次嘗試（20 次啟動看門狗重試，全部恢復）。
- 完整結果：[`results/nav-b2/README.md`](../../results/nav-b2/README.md)、`b1_report.json`。

## 結果（accuracy，teleport / Nav2，同一批 episodes）

| 方法 | budget 1 | 2 | 3 | 5 |
|---|---|---|---|---|
| Single | 0.525 / 0.525 | 0.525 / 0.525 | 0.525 / 0.525 | 0.525 / 0.525 |
| Random（3 seeds） | 0.525 / 0.525 | 0.908 / 0.902 | 0.981 / 0.983 | 1.000 / 1.000 |
| **Rule-NBV v2** | 0.525 / 0.525 | **0.988 / 0.981** | 1.000 / 1.000 | 1.000 / 1.000 |
| Oracle v2 | 0.525 / 0.525 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

## 判定（decision 018 §3）

| 問題 | 結果 | 判定 |
|---|---|---|
| Q1 安全 | 所有方法、所有 budget：false absent 0、false present 0、geometric risk 0 | **成立** |
| Q2 Nav2 − teleport | 全部在 −0.006 以內（最低 CI 下界 −0.019，邊界 −0.05） | **四個方法皆不劣於 teleport** |
| Q3 主動視角 | Rule − Single +0.456 [0.306, 0.613] / +0.475；Rule − Random +0.079 [0.044, 0.119] / +0.017 [0.004, 0.033] | **成立** |
| Q4 成本 | 每集行走距離 Rule 1.61 m vs Random 2.08 m（−0.46 [−0.80, −0.14]）；導航時間 −2.6 s [−4.5, −0.7] | 報告：Rule 較省 |

SPEC Advanced B 指標：導航 440 次，準確到點（reachable viewpoint）100%、Nav2 成功 100%、碰撞 0、逾時 0、進入 zone 0；
每次導航延遲（模擬、含重定位）p50 22.1 s、p95 28.4 s；位姿精修失敗 5 / 440（改用寬餘裕）。

## Advanced B 的結論

1. **在模擬中，把 teleport 換成真正的導航，不會讓 active perception 變差，也不會變得不安全**——前提是加上 decision 016 的三個元件：
   以 depth 對設施地圖做位姿精修、看穿判定的位姿餘裕、停點視角重定位。B0 已證明只靠 AMCL 位姿時，v2 的安全邊界會失效。
2. 主動視角（Rule-NBV v2）在導航下仍顯著勝過 Single 與 Random，而且走的路比 Random 短。
3. teleport 與 Nav2 的差異只有零星幾件（Nav2 下多了 `inconclusive`，從未變成錯誤答案）。

## 限制（照實揭露）

- 全部在 Gazebo 模擬中：差速里程計接近理想、起始位姿已知（停靠點）、牆與柱子的設施地圖事先已知、圍牆提供定位特徵。實機的里程計、地圖誤差與動態障礙都未測試。
- 場景為 `gen-nav-v1`（固定 2.0 m 視角環、1.1 m 桅桿相機、柱子與視角環保持間隙、8 m 圍牆），與 Core 的 gen-v2 不同，**數字不能與 Core 直接比較**。
- 感知仍是 Gazebo 的消防栓與 `detector-v1`；真實影像未驗證（sim-to-real 屬 SPEC Optional / Advanced A）。
- teleport 對照使用 Core 的 v2 路徑（精確位姿、無餘裕）；Q2 比較的是兩條完整流程。
- B0、`nav-b0c`、`nav-b0d`、`nav-b1` 都是開發 / 可行性資料；只有 `nav-b2` 是正式評估，且已用過，不再用於任何開發。

## 後續（需使用者決定）

- Advanced B 完成。Advanced C（RL）使用者先前決定暫不進行。
- 往實體機器人巡檢：SPEC 列為 Optional，需要硬體採購與真實影像的 detector 驗證，由使用者決定。
