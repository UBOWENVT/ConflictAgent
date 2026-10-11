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
