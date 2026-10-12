"""The single-shot cost estimate of harness/analyze.py on synthetic run_eval.py records."""
from __future__ import annotations

import json
import re

from harness.analyze import single_shot_estimate


def test_single_shot_estimate_counts_calls_and_retries(samples, tmp_path):
    sid = "junit4@4c8d3ff5"
    assert sid in samples
    run = tmp_path / "run.jsonl"

    def write(n_rounds):
        rec = {"kind": "llm", "id": sid, "provider": "openai", "n_rounds": n_rounds,
               "final_resolution": '\t\treturn "4.11-SNAPSHOT";'}
        run.write_text(json.dumps({"kind": "_meta"}) + "\n" + json.dumps(rec) + "\n")
        out = single_shot_estimate(str(run))
        m = re.search(r"1 records, (\d+) model calls .* ~\$(\d+\.\d+)", out)
        assert m, out
        return int(m.group(1)), out

    calls1, _ = write(1)
    calls4, out4 = write(4)
    assert (calls1, calls4) == (1, 4)
    assert "no thinking tokens" in out4


def test_process_signals_read_off_the_tool_calls():
    from inspect_ai.log import EvalSample
    from inspect_ai.model import ChatMessageAssistant
    from inspect_ai.tool import ToolCall

    from harness.analyze import process_signals

    def call(i, fn, **args):
        return ChatMessageAssistant(content="", tool_calls=[ToolCall(id=str(i), function=fn, arguments=args)])

    msgs = [call(1, "bash", command="ls -la"), call(2, "check_java", path="A.java"),
            call(3, "bash", command="grep -n crfModel A.java"),
            call(4, "view_file", path="/opt/harness/check_java.py"),
            call(5, "replace_text", path="A.java", old="x", new="y"), call(6, "submit", answer="done")]
    s = EvalSample(id="x", epoch=1, input="", target="", messages=msgs, metadata={"scenario_id": "x"})
    assert process_signals("m", s) == {
        "model": "m", "id": "x", "searched": True, "probed_environment": True,
        "checked_before_editing": True, "read_checker_source": True}
    quiet = EvalSample(id="y", epoch=1, input="", target="", metadata={"scenario_id": "y"},
                       messages=[call(1, "view_file", path="A.java"), call(2, "replace_text", path="A.java"),
                                 call(3, "check_java", path="A.java")])
    sig = process_signals("m", quiet)
    assert not any(sig[k] for k in ("searched", "probed_environment", "checked_before_editing",
                                    "read_checker_source"))
