# 002 — 任務定義凍結：三種真實狀態、episode schema、候選 viewpoint、split、budget

- **日期**：2026-10-10
- **狀態**：凍結（pilot 前仍可依 pilot 發現修正，但必須另開 decision log；正式 test 後不得更動）
- **是否在看過正式結果後才新增 / 修改**：否。

## 問題

SPEC §2–§4、§8 定義了三種 GT 狀態、teleport 隔離、frozen episode set 與 budget，但實作需要把它們變成可被測試的精確定義。

## 定義

### Ground truth state（每個 episode）

| 狀態 | 條件 |
|---|---|
| `absent` | 場景中沒有目標物件 |
| `visible` | 物件存在，且**初始 viewpoint** 的 GT visibility score ≥ 0.5 |
| `unobservable` | 物件存在，但初始 viewpoint 的 GT visibility score < 0.5 |

GT visibility score ∈ [0, 1]：物件朝向相機那一面的表面取樣點中，落在 FOV 內且視線未被遮擋的比例，再乘上投影面積不足時的懲罰因子（area_frac / 0.002，上限 1）。由 world 的 oracle pass 計算（synthetic：解析幾何；Gazebo：之後用 segmentation / depth 比對實作，同一個 `labeling.py` 做標籤）。

另記錄 `revealable`：物件存在且（初始或任一候選 viewpoint）的 GT visibility ≥ 0.5。

**SPEC 文字差異記錄**：SPEC §2 寫 `visible` 為「初始/可達視角可觀測」。本決策採「初始視角」為 visible / unobservable 的分界，「可達視角」資訊改以 `revealable` 另外記錄，用於 grading（見 003）。這樣 GT 狀態不隨 budget 改變。若使用者希望改回「初始或可達」的定義，需另開 decision log。

### 系統輸出

只能是 `present / absent / inconclusive`。「沒偵測到」不得直接等同 `absent`（由 shared decision rule 強制，見 004）。

### Episode schema（`activeperception/types.py`）

- `EpisodeSpec`：`namespace, scene_group, variant, seed, split, generator_version, zone, camera, initial_viewpoint, candidate_viewpoints, layout`。
- `layout`（物件存在與否、物件 pose、遮擋物）只給 simulator 與 oracle pass；policy 只拿得到 `DeployableEpisode`（zone、camera、initial viewpoint、candidate viewpoints）。
- `EpisodeGroundTruth`：`state, revealable, visibility_initial, visibility_by_viewpoint, zone_visible_by_viewpoint, labeling_version`，只給 grader 與 Oracle NBV。

### 候選 viewpoint（gen-v1）

- 12 個候選，等角分佈在以 inspection zone 中心為圓心的環上；環的相位、半徑（2.0 ± 0.2 m）、高度（1.1 ± 0.2 m）由 `(namespace, generator_version, scene_group)` 的獨立隨機流決定。
- 初始 viewpoint 為另一個獨立隨機方位（半徑 2.0、高度 1.1），不屬於候選集合，id = -1。
- 所有 viewpoint 都朝向 zone 中心。
- **候選集合與初始 viewpoint 與物件 pose、存在與否、遮擋物完全無關**（`tests/test_leakage.py`）。它們只依賴「要巡檢哪個區域」，這是部署時本來就知道的資訊。

### Scene group 與 variants

每個 scene group 有 4 個 variants：v0 present、v1 absent、v2 present + 小幅遮擋 jitter、v3 absent + 小幅遮擋 jitter。同一 group 共用候選 viewpoint、初始 viewpoint 與遮擡物基礎佈局。present / absent 在每個 group 內 1:1。

遮擋物為方柱（0.4–0.8 m 寬、0.9–1.5 m 高），1–3 個，放在半徑 0.85–1.3 m 的環上；50% 的 group 會刻意把一個方柱放在初始視線上，以產生足夠的 `unobservable` episodes。這是控制 layout，不是用 GT 標籤篩選。

### Split

- 以 scene group 為最小單位：`sha256("split", namespace, generator_version, group) % 1000` → train < 400、val < 600、其餘 test（40 / 20 / 40）。
- 同一 group 的 4 個 variants 必定同 split（`tests/test_episodes.py`）。
- `pilot` namespace 永遠是 `PILOT` split，且 seed 流與正式 namespace 完全不同。pilot episodes 不進 final test。

### Budget 協定

- budget B = 允許的觀測總數，**含初始視角**。B = 1 時所有方法退化為 Single View（harness test 驗證四個方法在 B=1 輸出完全一致）。
- 正式 budget 組合預定為 {1, 3, 5}，pilot 之後、正式 test 之前凍結（另開 decision log 記錄最終值）。
- 候選 viewpoint 與 budget 對四個方法完全相同；harness 拒絕重訪與未知 id。

## 候選方案與取捨

- 候選 viewpoint 曾考慮「依場景幾何自適應生成」：否決，因為任何依賴遮擋物的生成都可能洩漏 GT。
- GT 狀態曾考慮用「任一候選可見」定義 visible：否決，因為那會讓 GT 狀態與候選集合 / budget 耦合，改以 `revealable` 另記。

## 被凍結的項目

generator version `gen-v1`、labeling version `label-v1`（visible 門檻 0.5）、split 規則與比例、variants 結構、budget 含初始視角的計數方式、pilot namespace 隔離。
