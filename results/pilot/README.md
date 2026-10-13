# Pilot（SPEC §9）— 不是研究結果

- 資料：`data/episodes/gazebo-pilot.json`（`pilot` namespace，6 scene groups、24 episodes；永遠不進 final test）
- 影像：`renders/pilot`（image `sha256:49d6e69b…`），獨立重 render：`renders/pilot-rerender`
- detector：`detector-v1`（FRCNN-MobileNetV3，RTX 5070 Ti、GPU lock 下產生快取）
- decision rule：`decision-v0`、rule-NBV：`rule-nbv-v0`（尚未調參）
- 指令：`python -m activeperception.pilot --episodes data/episodes/gazebo-pilot.json --frames renders/pilot --detections runs/pilot/detector-v1.jsonl --rerender renders/pilot-rerender --out results/pilot`
- 完整輸出：`pilot_report.json`

| SPEC §9 項目 | 檢查 | 結果 |
|---|---|---|
| 三種狀態可區分 | 三狀態都出現（visible 6 / unobservable 6 / absent 12）；初始視角 max conf：visible 0.99、unobservable 0.004、absent 0.002；visible vs absent AUROC 1.0；**unobservable vs absent 只有 0.75**（單一視角分不出「看不到」與「不存在」）；所有視角取最大時 present vs absent AUROC 1.0 | 通過 |
| teleport deterministic | 24 episodes 獨立重 render：RGB / depth / labels 24/24、clear labels 12/12 逐像素相同 | 通過 |
| sensor timestamp | 312 張 frame 的 stamp 都晚於 teleport 參考 + settle（0.092–0.100 s），單調遞增；clear pass 在 full pass 之後；記錄的 pose 與 spec 相同 | 通過 |
| sensor transform | 96 個視角 depth vs ray-cast（planar）：中位誤差 0.25 mm、p99 0.50 mm；非物件像素 label 一致 ≥ 99.92% | 通過 |
| 四方法同候選集 | 106 個 (episode, viewpoint) 觀測在所有方法間完全相同；初始視角都在第一個；只走訪候選；budget 1 四方法輸出相同 | 通過 |
| grader 不吃 inconclusive | inconclusive 從未被算成 false-absent / false-present；correct ⇔ decision == expected | 通過 |

## Pilot sweep（v0 參數，僅供管線檢查）

24 episodes 太少，且參數未調，以下數字不用於任何結論：

- budget 3 / 5 時所有方法都把 12 個 present episodes 判對；差異全在 absent episodes。
- absent 需要 6 個方位扇區中至少 3 個「zone 未被擋住」的有效視角；budget 3 時若任何一個視角被擋就不可能達成。
- `rule-nbv-v0` 只用角度新穎性，沒有直接以 decision rule 計算的「未覆蓋扇區」為目標（Oracle 有），pilot 上沒有勝過 random。
  這是 M5 在 **train / val** 上改進 rule-NBV 時要處理的結構問題（另開 decision log，不在 pilot 或 test 上調參）。
