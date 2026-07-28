# 从磁盘上的 JSONL 重算指标

所有 headline 数字都不是"跑一次就消失"的——它们是磁盘上**两个 per-case JSONL** 的简单聚合。想复现，直接数这两个文件即可，**不需要再调用任何 LLM**。

| 指标 | 磁盘文件 | 行数 | 每行是什么 |
| --- | --- | --- | --- |
| ① 判官线（验判官）100% / 64.6% | `outputs/deepeval/meta_evaluation_20260727_062930.jsonl` | 292 | 一条判官裁决 vs 人工标签 |
| ①+② solver 线（量 LLM）≈55% / 95.8% | `outputs/deepeval/solver_eval_20260627_095221.jsonl` | 132 | 一条 (场景×provider) 的 ① accept + ② structurally_valid |

> 文件名带时间戳；如果重跑会生成新的一份，取 `outputs/deepeval/` 里最新的 `meta_evaluation_*` / `solver_eval_*` 即可。旧的 `metaval_2026062*`（303/310 行）是被取代的早期口径，`judge_calibration/calib_*`（563 行）是手搓判官时代，均为历史。

---

## 1. 判官线：precision 100% / recall 64.6%（n=292）

`meta_evaluation_*.jsonl` 每行字段：`{project, commit, tool, source, human(bool), judge(bool), score, reason}`。
`human` = 人工 0/1 标签，`judge` = GEval 判官裁决。混淆矩阵：

```python
import json
rows = [json.loads(l) for l in open("outputs/deepeval/meta_evaluation_20260727_062930.jsonl") if l.strip()]
TP = sum(r["judge"] and r["human"] for r in rows)          # 117
FP = sum(r["judge"] and not r["human"] for r in rows)      # 0
TN = sum(not r["judge"] and not r["human"] for r in rows)  # 111
FN = sum(not r["judge"] and r["human"] for r in rows)      # 64
precision = TP/(TP+FP)   # 100.0%
recall    = TP/(TP+FN)   # 64.6%
accuracy  = (TP+TN)/len(rows)  # 78.1%
```

FP=0 → precision 100%（判官说"可接受"从不冤枉）；recall 64.6% → 保守，会漏判一些其实可接受的解。

## 2. solver 线：true-conflict dev-match ≈55% floor，结构合法率 95.8%

`solver_eval_*.jsonl` 每行字段：`{id, provider, valid_conflict(bool), accept(bool ①), accept_score, structurally_valid(bool ②), accept_reason, valid_reason}`。

```python
s = [json.loads(l) for l in open("outputs/deepeval/solver_eval_20260627_095221.jsonl") if l.strip()]
true = [r for r in s if r["valid_conflict"]]               # 96 条 = 49 true 场景 × 两家(gemini 少 2)
# ① dev-match，按 provider 分层：
for p in ("openai","gemini"):
    t=[r for r in true if r["provider"]==p]
    print(p, sum(r["accept"] for r in t), "/", len(t))     # openai 27/49=55.1% · gemini 29/47=61.7%
# 报保守 floor = 两家低者 = 55.1%（pooled 是 56/96=58.3%，我们不报 pooled）
# ② 结构合法率：
print(sum(r["structurally_valid"] for r in true), "/", len(true))   # 92/96 = 95.8%
```

与 5 工具对比（AutoMerge 36.7% 等）：由 `scripts/compare_tools_geval.py` 用**同一个 ① 判官**判 xlsx 里各工具的解得到，口径同上。

---

## 3. 这两个 JSONL 本身从哪来（往上一层）

如果你要连"判官/结构判定"也重跑（会调用 LLM），而不是只聚合已判好的结果：

```
① 判官线：
  data/ConflictBench.xlsx
    → conflictagent/data.load_manual_labels()            627 条有标签的 pair
    → evaluation/dataset.build_metaevaluation_testcases() 丢 punt/file-level/空 → 292
    → evaluation/run_suite.py（跑 ① GEval，写 meta_evaluation_*.jsonl 并打印混淆矩阵）

②+① solver 线：
  data/scenarios/  → conflictagent/data.load_scenarios(java_only)  93 可重建
    → scripts/run_agent.py（solver.py 生成 + agent.py 生成-校验-重试环，写 outputs/eval/eval_A_complete.jsonl）
    → evaluation/build_complete_set.py（装配/去重 complete set）
    → evaluation/dataset.build_solver_testcases()（重建 input，定位 dev 区 → 67 场景 → 喂两家 132 条）
    → evaluation/run_solver_eval.py（跑 ①+②，写 solver_eval_*.jsonl）
```

- `outputs/eval/eval_A_complete.jsonl`（首行是 `kind=_meta` 的头，其余是每个场景两家的 solver 解）= solver 线的**再判前**原料。
- 判官线那 292 条的逐点来源（900→292 漏斗）见 `scripts/diagnostics/judge_funnel_provenance.py` 与 `docs/judge_funnel_900.xlsx`。

**一句话**：只想要数字 → 聚合第 1、2 节的两个 JSONL；想连判定一起重跑 → 从 `eval_A_complete.jsonl` / xlsx 走第 3 节的脚本链。权威数字表在 `docs/RESULTS.md`。
