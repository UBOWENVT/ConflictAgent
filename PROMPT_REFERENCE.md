# ConflictAgent — 完整提示词参考 (solver)

本文件 = 实际发给 solver LLM (OpenAI / Gemini) 的全部内容，逐字。
来源：`conflictagent/solver.py` 的 `SYSTEM_PROMPT` + `build_prompt()`。
判官 (judge) 用的是另一套提示词，在 `judge.py`，不在本文件范围。

当前上下文策略 = **整文件**（即将改为方法 2「窗口」）。除文件槽位外，其余一字不变。

---

## 1. SYSTEM PROMPT（两家逐字相同）

```text
You are an expert software engineer resolving a Git merge conflict. You are shown the WHOLE file. It contains one or more conflict regions in diff3 form:
  <<<<<<< left      one side's change
  ||||||| base      common ancestor
  =======
  >>>>>>> right     the other side's change

Exactly one conflict region is tagged [[RESOLVE THIS CONFLICT]] on its <<<<<<< line. Use the rest of the file as context, but act ONLY on the tagged conflict.

First judge whether the tagged conflict is a TRUE conflict: one where the two sides make genuinely incompatible changes that require human judgment to reconcile, so no single automatic resolution is clearly correct. Otherwise it is resolvable.

Respond in EXACTLY one of these two forms, with the verdict on the first line:

VERDICT: RESOLVE
<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< line through its >>>>>>> line. Output ONLY that code: no conflict markers, no fences, no commentary.>

or

VERDICT: TRUE_CONFLICT
(output nothing after this line)
```

---

## 2. USER MESSAGE — 首轮（无重试）

结构 = 一行抬头 + 整个 diff3 文件（目标块的 `<<<<<<<` 行被加了 `   [[RESOLVE THIS CONFLICT]]`）。

模板：

```text
## File (resolve only the tagged conflict):
{整个文件，diff3 形式，目标块已标记}
```

---

## 3. USER MESSAGE — 重试轮（校验失败时）

同样的文件，后面追加上一次的失败尝试 + 校验错误 + 修正指令。最多重试 MAX_RETRIES 次。

模板：

```text
## File (resolve only the tagged conflict):
{整个文件，diff3 形式，目标块已标记}

## Your previous attempt did NOT pass validation:
{上一次模型输出的解}

## Validator error:
{校验器报的错，例如 "Output still contained conflict markers (<<<<<<< / ======= / >>>>>>>)."}

Fix the problem. Output the verdict line then only the corrected resolved code.
```

---

## 4. 完整拼装实例（一个 2 冲突块的小文件，目标=第 2 个块）

下面是 system + user 拼好后、真正发出去的完整字节（小例子，方便通读）。

### 4a. 发给模型的 SYSTEM（同第 1 节）

### 4b. 发给模型的 USER（首轮）

```text
## File (resolve only the tagged conflict):
package com.example;

import com.example.util.Helper;
<<<<<<< left
import com.example.A;
||||||| base
import com.example.Old;
=======
import com.example.B;
>>>>>>> right

public class Demo {
    public int compute(int x) {
<<<<<<< left   [[RESOLVE THIS CONFLICT]]
        return x * 2;
||||||| base
        return x;
=======
        return x * 3;
>>>>>>> right
    }
}
```

注意：第 1 个冲突块（import 那个）**没有**标记，第 2 个块（方法体）`<<<<<<<` 行末尾被加了 `   [[RESOLVE THIS CONFLICT]]`。模型只解第 2 个，第 1 个仅作上下文。

### 4c. 发给模型的 USER（重试轮，假设上一轮没过校验）

```text
## File (resolve only the tagged conflict):
package com.example;

import com.example.util.Helper;
<<<<<<< left
import com.example.A;
||||||| base
import com.example.Old;
=======
import com.example.B;
>>>>>>> right

public class Demo {
    public int compute(int x) {
<<<<<<< left   [[RESOLVE THIS CONFLICT]]
        return x * 2;
||||||| base
        return x;
=======
        return x * 3;
>>>>>>> right
    }
}


## Your previous attempt did NOT pass validation:
import com.example.A;
import com.example.B;

## Validator error:
Output still contained conflict markers (<<<<<<< / ======= / >>>>>>>).

Fix the problem. Output the verdict line then only the corrected resolved code.
```

---

## 5. 期望的模型输出 & 解析

模型必须二选一回复：

可解：
```text
VERDICT: RESOLVE
        return x * 3;
```
（RESOLVE 后面是替换整个目标块 `<<<<<<< ... >>>>>>>` 的代码，不含任何标记/围栏/解释）

判为真冲突（punt）：
```text
VERDICT: TRUE_CONFLICT
```

`_parse()` 抓第一行的 `VERDICT:`：
- 含 RESOLVE → verdict='resolve'，其后的代码 = 目标块的解
- 含 TRUE_CONFLICT → verdict='true_conflict'（punt，记为 Detection 预测「这是真冲突」）
- 没有 VERDICT 行 → 兜底：含 TRUE_CONFLICT 字样则当 punt，否则把整段当作解

---

## 6. 两家怎么把同一套 system+user 接进 SDK

文本完全一样，只是机械接法不同（见 `llm.py`）：

- **OpenAI**：`messages=[{role:"system", content:SYSTEM}, {role:"user", content:USER}]`
- **Gemini**：`contents=USER`，`config=GenerateContentConfig(system_instruction=SYSTEM)`
- **Anthropic**（仅判官用）：`system=SYSTEM, messages=[{role:"user", content:USER}]`

---

## 7. 方法 2（窗口）将改动的唯一一处

- 第 2、3 节里「整个文件」的槽位 → 换成**窗口**：文件骨架（package + import 区 + 类声明行）+ 包住目标块的最小完整大括号作用域；文件小（≤ 阈值）则仍发整文件。
- SYSTEM 第 1 句 `You are shown the WHOLE file.` → 改成 `You are shown the relevant section of a file.`（不然对模型不实）。
- 标记机制、diff3、输出契约、重试逻辑：全部不变。
