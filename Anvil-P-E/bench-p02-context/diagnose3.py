"""
diagnose3.py - Check signal/ground_truth family alignment and score each pair.
Run from: bench-p02-context/
"""
import sys, os
sys.path.insert(0, os.path.abspath('../../persistent-context-engine'))
sys.path.insert(0, os.path.abspath('.'))

from generator import generate, GenConfig
from adapters.myteam import Engine
from metrics import score_match, score_remediation

cfg = GenConfig(seed=42, n_services=6, days=2)
ds = generate(cfg)

print("=== SIGNAL / GROUND_TRUTH ALIGNMENT CHECK ===")
for i, (sig, gt) in enumerate(zip(ds.eval_signals, ds.ground_truth)):
    sig_family = sig["incident_id"].rsplit("-", 1)[-1]
    gt_family = gt["family"]
    match = sig_family == str(gt_family)
    print(f"  [{i}] signal={sig['incident_id']} sig_family={sig_family} | gt={gt['incident_id']} gt_family={gt_family}  ALIGNED={match}  svc={sig.get('service')}")

print()
print("=== TRAIN INCIDENT ID -> FAMILY BREAKDOWN ===")
train_incidents = [e for e in ds.train_events if e.get("kind") == "remediation"]
for r in train_incidents:
    iid = r.get("incident_id", "")
    fam = iid.rsplit("-", 1)[-1]
    print(f"  remedy incident={iid}  parsed_family={fam}  target={r.get('target')}")

print()
print("=== PER-SIGNAL SCORE BREAKDOWN ===")
engine = Engine()
engine.ingest(ds.train_events)
engine.ingest(ds.eval_events)

inner = engine._engine
print(f"IncidentMemory total: {inner._incident_memory.total_incidents}")
for cid, incs in inner._incident_memory._by_canonical.items():
    aliases = inner._identity.get_all_aliases(cid)
    print(f"  {cid} (aliases={aliases}): {[i.incident_id for i in incs]}")

print()
total_recall = 0
total_rem = 0
for sig, gt in zip(ds.eval_signals, ds.ground_truth):
    ctx = engine.reconstruct_context(sig, mode="fast")
    in_top_k, precision = score_match(ctx, gt, k=5)
    rem_ok = score_remediation(ctx, gt)
    total_recall += int(in_top_k)
    total_rem += int(rem_ok)
    past_ids = [p.get("incident_id") for p in ctx.get("similar_past_incidents", [])]
    rems_actions = [r.get("action") for r in ctx.get("suggested_remediations", [])]
    print(f"  signal={sig['incident_id']}  gt_family={gt['family']}  in_top_k={in_top_k}  rem_ok={rem_ok}")
    print(f"    past_ids={past_ids}")
    print(f"    rem_actions={rems_actions}  expected={gt['expected_remediation']}")

n = len(ds.eval_signals)
print()
print(f"SUMMARY: recall={total_recall}/{n}  remediation={total_rem}/{n}")
engine.close()
