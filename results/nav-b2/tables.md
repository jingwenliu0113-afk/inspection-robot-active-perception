### Accuracy

| 方法 | budget 1 | 2 | 3 | 5 |
|---|---|---|---|---|
| Single（teleport / Nav2） | 0.525 / 0.525 | 0.525 / 0.525 | 0.525 / 0.525 | 0.525 / 0.525 |
| Random（teleport / Nav2） | 0.525 / 0.525 | 0.908 / 0.902 | 0.981 / 0.983 | 1.000 / 1.000 |
| Rule-NBV v2（teleport / Nav2） | 0.525 / 0.525 | 0.988 / 0.981 | 1.000 / 1.000 | 1.000 / 1.000 |
| Oracle v2（teleport / Nav2） | 0.525 / 0.525 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

### Q1 安全（Nav2，budget 1–5 合計）

| 方法 | false absent | false present | geometric risk |
|---|---|---|---|
| single | 0 | 0 | 0 |
| random | 0 | 0 | 0 |
| rule | 0 | 0 | 0 |
| oracle | 0 | 0 | 0 |

### Q2 Nav2 − teleport（accuracy）

| 方法 | budget 2 | budget 3 |
|---|---|---|
| single | +0.000 [+0.000, +0.000] non-inferior | +0.000 [+0.000, +0.000] non-inferior |
| random | -0.006 [-0.015, +0.000] non-inferior | +0.002 [+0.000, +0.006] non-inferior |
| rule | -0.006 [-0.019, +0.000] non-inferior | +0.000 [+0.000, +0.000] non-inferior |
| oracle | +0.000 [+0.000, +0.000] non-inferior | +0.000 [+0.000, +0.000] non-inferior |

### Q3 主動視角（Nav2）

| 比較（Nav2） | budget 2 | budget 3 |
|---|---|---|
| Rule − single | +0.456 [+0.306, +0.613] holds | +0.475 [+0.325, +0.650] holds |
| Rule − random | +0.079 [+0.044, +0.119] holds | +0.017 [+0.004, +0.033] holds |

### Q4 成本（每個 episode）

- 行走距離：Rule 1.61 m、Random 2.08 m；差 -0.463 [-0.797, -0.143] m
- 導航時間（模擬）：Rule 10.9 s、Random 13.5 s；差 -2.646 [-4.496, -0.748] s

### 導航（SPEC Advanced B 指標）

- 導航次數 440；準確到點（path success / reachable viewpoint）1.000；Nav2 回報成功 440；碰撞 0；逾時 0；進入 zone 0
- 每次導航延遲（模擬，含重定位）p50 22.1 s、p95 28.4 s；重定位修正次數 {'0': 18, '1': 15, '2': 407}；精修失敗 5
