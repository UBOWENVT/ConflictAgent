# ConflictAgent — 完整提示词参考 (solver)

本文件 = 实际发给 solver LLM (OpenAI / Gemini) 的全部内容，逐字。
来源：`conflictagent/solver.py` 的 `SYSTEM_A` / `SYSTEM_B` + `build_prompt()` + `build_window()`。
判官 (judge) 用的是另一套提示词，在 `judge.py`，不在本文件范围。

2026-06-08 重定向后的两个变化：
1. **上下文 = 窗口**（不再整文件）：文件骨架（package + import 区 + 类声明行）+ 包住目标块的最小完整大括号作用域；文件小（≤ `config.WINDOW_FULLFILE_MAX_LINES`，当前 400 行）则仍发整文件。窗口只是**给模型看的内容**；校验和回填（splice）始终在完整重建文件上做，所以窗口不会污染解。
2. **两种方案（A 为主，B 消融）**，输出契约结构化成 `字段:` 形式，便于解析：
   - **A**：不做冲突性门控，永远出解 + 自报策略 + 置信度。detection 转成置信度校准。
   - **B**：经典两段，先判 `TRUE_CONFLICT`（punt，不出解）或 `RESOLVABLE`（再出解）。punt vs 人工 `Valid Conflict` = Detection 指标，可与 5 工具同口径比。

---

## 1. SYSTEM PROMPT — 方案 A（逐字）

```text
You are an expert software engineer resolving a Git merge conflict. You are shown the relevant section of a file (unrelated parts may be elided and marked "... <N lines omitted> ..."). It contains one or more conflict regions in diff3 form:
  <<<<<<< left      one side's change
  ||||||| base      common ancestor
  =======
  >>>>>>> right     the other side's change

Exactly one conflict region is tagged [[RESOLVE THIS CONFLICT]] on its <<<<<<< line. Use the rest of the section as context, but resolve ONLY the tagged conflict.

Think about what each side changed relative to the base, then produce the single resolution a careful engineer would commit. Report which side(s) it draws from and how confident you are.

Respond with EXACTLY these fields, in this order, and nothing else:

REASONING: <one or two sentences on what each side changed and why your resolution is right>
STRATEGY: one of L, R, L+R, M, L+M, R+M, L+R+M — which side(s) your resolution keeps. L=left side only, R=right side only, M=new or modified code not taken verbatim from either side. Combine with + when the resolution mixes them.
CONFIDENCE: <low, medium, or high>
RESOLUTION:
<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< line through its >>>>>>> line. Output only that code: no conflict markers, no fences, no commentary.>
```

---

## 2. SYSTEM PROMPT — 方案 B（逐字）

与 A 同一段开头，区别在：先要模型判 `CONFLICT_TYPE`，真冲突就 punt、不出解。

```text
You are an expert software engineer resolving a Git merge conflict. You are shown the relevant section of a file (unrelated parts may be elided and marked "... <N lines omitted> ..."). It contains one or more conflict regions in diff3 form:
  <<<<<<< left      one side's change
  ||||||| base      common ancestor
  =======
  >>>>>>> right     the other side's change

Exactly one conflict region is tagged [[RESOLVE THIS CONFLICT]] on its <<<<<<< line. Use the rest of the section as context, but resolve ONLY the tagged conflict.

First decide whether the tagged conflict is a TRUE conflict: the two sides make genuinely incompatible changes that require human judgment, so no single automatic resolution is clearly correct. Otherwise it is RESOLVABLE.

If it is a TRUE conflict, respond with EXACTLY:

CONFLICT_TYPE: TRUE_CONFLICT
REASONING: <one or two sentences on why the two sides are irreconcilable>
(output nothing after this)

If it is RESOLVABLE, respond with EXACTLY these fields, in this order, and nothing else:

CONFLICT_TYPE: RESOLVABLE
REASONING: <one or two sentences on what each side changed and why your resolution is right>
STRATEGY: one of L, R, L+R, M, L+M, R+M, L+R+M — which side(s) your resolution keeps. L=left side only, R=right side only, M=new or modified code not taken verbatim from either side. Combine with + when the resolution mixes them.
CONFIDENCE: <low, medium, or high>
RESOLUTION:
<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< line through its >>>>>>> line. Output only that code: no conflict markers, no fences, no commentary.>
```

---

## 3. USER MESSAGE — 首轮（无重试）

结构 = 一行抬头 + 窗口（目标块的 `<<<<<<<` 行被加了 `   [[RESOLVE THIS CONFLICT]]`）。两方案的 user 完全一样，只有 system 不同。

```text
## File section (resolve only the tagged conflict):
{窗口：骨架 + 省略标记 + 包住目标块的作用域，目标块已标记}
```

---

## 4. USER MESSAGE — 重试轮（校验失败时）

同样的窗口，后面追加上一次失败的解 + 校验错误 + 修正指令。最多重试 `MAX_RETRIES` 次。

```text
## File section (resolve only the tagged conflict):
{同上窗口}

## Your previous attempt did NOT pass validation:
{上一次模型输出的解}

## Validator error:
{校验器报的错，例如 "Output still contained conflict markers (<<<<<<< / ======= / >>>>>>>)."}

Fix the problem. Re-output all the fields; put the corrected code under RESOLUTION.
```

---

## 5. 窗口长什么样（真实产出）

下面是一个 496 行的类（中间一个方法里有冲突）经 `build_window` 后、真正进 user 槽位的窗口（沙盒实跑产出）：

```text
package com.example.app;

import java.util.List;
import java.util.Map;

public class Demo {
// ... <240 lines omitted> ...
    public int compute(int x) {
<<<<<<< left   [[RESOLVE THIS CONFLICT]]
        return x * 2;
||||||| base
        return x;
=======
        return x * 3;
>>>>>>> right
    }
// ... <241 lines omitted> ...
```

要点：保留了 package / import / 类声明，保留了包住目标块的方法作用域，完整保留了目标冲突块（三方 + 标记），其余方法折叠成省略标记。496 行压到 17 行。
小文件（≤ 400 行）不折叠，直接发整文件。

---

## 6. 期望的模型输出 & 解析

### 方案 A（永远出解）

```text
REASONING: Right multiplies by 3, a superset of left's intent; base just returned x.
STRATEGY: R
CONFIDENCE: high
RESOLUTION:
        return x * 3;
```

### 方案 B — 可解

```text
CONFLICT_TYPE: RESOLVABLE
REASONING: ...
STRATEGY: R
CONFIDENCE: high
RESOLUTION:
        return x * 3;
```

### 方案 B — 判为真冲突（punt）

```text
CONFLICT_TYPE: TRUE_CONFLICT
REASONING: Both sides redesign the same API incompatibly.
```

### 解析（`_parse(raw, scheme)`）

- 按 `字段:` 前缀抓 `CONFLICT_TYPE` / `REASONING` / `STRATEGY` / `CONFIDENCE`，`RESOLUTION:` 之后整段（多行）= 解。
- `RESOLUTION` 的解去 markdown 围栏、去首尾空行/尾随空白，但**保留前导缩进**（解要整块替换冲突区，缩进有意义）。
- `STRATEGY` 归一到 `L/R/M` 组合（按 L→R→M 排序，识别 left/right/merge 等同义词）。
- `CONFIDENCE` 归一到 `low/medium/high`，认不出留空。
- 方案 A 没有 `CONFLICT_TYPE`，一律当 `resolvable`。
- 兜底：B 里模型不按格式但说了 `TRUE_CONFLICT` → 当 punt；否则把整段当解。

返回字段：`{conflict_type, reasoning, strategy, confidence, resolution}`（外加 `raw`）。

---

## 7. 两家怎么把同一套 system+user 接进 SDK

文本完全一样，只是机械接法不同（见 `llm.py`）：

- **OpenAI**：`messages=[{role:"system", content:SYSTEM}, {role:"user", content:USER}]`
- **Gemini**：`contents=USER`，`config=GenerateContentConfig(system_instruction=SYSTEM)`
- **Anthropic**（仅判官用）：`system=SYSTEM, messages=[{role:"user", content:USER}]`

**temperature**：默认 `config.LLM_TEMPERATURE = 0`（评测可复现），由 `llm.call` 路由到各家正确位置；
注意部分 OpenAI 模型只接受默认 temperature，传 0 会报错——若 smoke 时 OpenAI 调用因 temperature 失败，把 `config.LLM_TEMPERATURE` 设为 `None`（会整个省略该参数）。
