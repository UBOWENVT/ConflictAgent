"""Inspect logs -> one JSONL record per (scenario, model), in scripts/run_eval.py's record schema.

The records feed the unified offline scoring (evaluation/run_unified_eval.py) the same way the
single-shot runs do: `final_resolution` is the agent's resolution (the cleaned region the harness
scorer extracted from the final file) and `dev_region` is the developer's resolution of the same
target block, recomputed here from the child file exactly as scripts/run_eval.py computes it.
The child file is read only here, after the run. Agent-specific fields ride along (`outcome`,
`extraction`, `limit`, ...).

    python -m harness.export logs/2026-*.eval --out outputs/stage3/agent_<stamp>.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inspect_ai.log import EvalLog, EvalSample, read_eval_log  # noqa: E402

from conflictagent import data, groundtruth, merge  # noqa: E402

log = logging.getLogger(__name__)

SCORER = "conflict_file_scorer"
# Inspect provider prefix -> the provider names the single-shot records use
PROVIDERS = {"openai": "openai", "google": "gemini", "mockllm": "mock"}


def provider_of(model: str) -> str:
    prefix = model.split("/", 1)[0]
    if prefix not in PROVIDERS:
        raise ValueError(f"no provider mapping for model {model!r}")
    return PROVIDERS[prefix]


def developer_regions(ids: set[str]) -> dict[str, tuple[str | None, str, int]]:
    """{id: (dev_region, dev_status, target_idx)}, computed as scripts/run_eval.py does."""
    out = {}
    for s in data.load_scenarios(java_only=True):
        if s.id not in ids:
            continue
        fv = data.load_full_versions(s)
        merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
        tgt, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
        region, status = groundtruth.resolution_region(fv["child"], merged, tgt)
        out[s.id] = (region, status, tgt)
    missing = ids - out.keys()
    if missing:
        raise ValueError(f"scenarios not found: {sorted(missing)}")
    return out


def sample_record(log_: EvalLog, sample: EvalSample) -> dict:
    """The export record of one sample, without dev_region (added by export_records)."""
    m = sample.metadata
    score = (sample.scores or {}).get(SCORER)
    sm = score.metadata if score is not None else {}
    outcome = "error" if sample.error is not None or score is None else sm["outcome"]
    resolution = (score.answer or "") if score is not None else ""
    return {
        "kind": "llm", "setting": "agent", "scheme": "A",
        "id": m["scenario_id"], "provider": provider_of(log_.eval.model),
        "model": log_.eval.model,
        "valid_conflict": m["valid_conflict"],
        "n_blocks": m["n_blocks"], "target_idx": m["target_idx"],
        "status": "resolved" if resolution.strip() else "empty",
        "outcome": outcome,
        "extraction": sm.get("extraction"),
        "final_resolution": resolution,
        "final_valid": sm.get("structurally_valid"),
        "submitted": sm.get("submitted"),
        "limit": sample.limit.type if sample.limit is not None else None,
        "error": sample.error.message if sample.error is not None else None,
        "log": log_.location, "sample_uuid": sample.uuid,
    }


def export_records(log_paths: list[str]) -> list[dict]:
    """One record per (scenario, model). When a sample appears in several logs (eval-retry), the
    latest log wins unless its copy errored and an earlier one did not."""
    chosen: dict[tuple[str, str], dict] = {}
    logs = [read_eval_log(p) for p in log_paths]
    for lg in sorted(logs, key=lambda x: x.eval.created):
        if lg.status not in ("success", "error"):
            log.warning("%s: status %s", lg.location, lg.status)
        for sample in lg.samples or []:
            if sample.epoch != 1:
                raise ValueError(f"{lg.location}: epoch {sample.epoch}; one epoch expected")
            rec = sample_record(lg, sample)
            key = (rec["id"], rec["model"])
            prev = chosen.get(key)
            if prev is not None and rec["outcome"] == "error" and prev["outcome"] != "error":
                continue
            chosen[key] = rec
    records = sorted(chosen.values(), key=lambda r: (r["model"], r["id"]))
    dev = developer_regions({r["id"] for r in records})
    for r in records:
        region, status, tgt = dev[r["id"]]
        if tgt != r["target_idx"]:
            raise ValueError(f"{r['id']}: target block {tgt} != sample's {r['target_idx']}")
        r["dev_status"], r["dev_region"] = status, region
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logs", nargs="+", help="Inspect .eval log files")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    records = export_records(args.logs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    for r in records:
        by.setdefault(r["model"], {}).setdefault(r["outcome"], 0)
        by[r["model"]][r["outcome"]] += 1
    log.info("%d records -> %s", len(records), out)
    for model, counts in by.items():
        log.info("  %s: %s", model, dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
