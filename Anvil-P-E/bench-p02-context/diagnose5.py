"""
diagnose5.py - Check eval topology events and svc-00-r7 origin
"""
import sys, os
sys.path.insert(0, os.path.abspath('../../persistent-context-engine'))
sys.path.insert(0, os.path.abspath('.'))

from generator import generate, GenConfig

cfg = GenConfig(seed=42, n_services=6, days=2)
ds = generate(cfg)

print("=== ALL TOPOLOGY EVENTS (train + eval) ===")
all_topos = [e for e in ds.train_events + ds.eval_events if e.get("kind") == "topology"]
for t in sorted(all_topos, key=lambda e: e["ts"]):
    print(f"  ts={t['ts']}  change={t['change']}  from={t.get('from_')}  to={t.get('to')}")

print()
print("=== svc-00-r7 appears first in which events? ===")
for e in sorted(ds.train_events + ds.eval_events, key=lambda e: e["ts"]):
    svc = e.get("service", "") or e.get("target", "") or e.get("from_", "") or e.get("to", "")
    if "svc-00-r7" in str(svc):
        print(f"  ts={e['ts']}  kind={e['kind']}  svc_context={svc}")
        if e == (ds.train_events + ds.eval_events)[0]:
            break
        # show first 5 occurrences
        break

# Count svc-00-r7 occurrences
count = 0
for e in sorted(ds.train_events + ds.eval_events, key=lambda e: e["ts"]):
    svc = e.get("service", "") or e.get("target", "") or e.get("from_", "") or e.get("to", "")
    if "svc-00-r7" in str(svc):
        print(f"  ts={e['ts']}  kind={e['kind']}  svc={svc}")
        count += 1
        if count >= 5:
            break

print()
print(f"=== CHECKING: is 'svc-00-r7' a rename result from eval topology? ===")
for e in ds.eval_events:
    if e.get("kind") == "topology":
        print(f"  EVAL TOPO: {e}")

print()
print("=== GENERATOR INTERNAL: what renames happened for svc-00? ===")
# Re-run generator to track alias changes for svc-00
import random
from datetime import datetime, timedelta, timezone

cfg2 = GenConfig(seed=42, n_services=6, days=2)
rng = random.Random(cfg2.seed)
start = datetime.fromisoformat("2026-05-01T00:00:00+00:00")
duration = timedelta(days=cfg2.days)
canonical = [f"svc-{i:02d}" for i in range(cfg2.n_services)]
alias = {s: s for s in canonical}

mutation_times = sorted(start + duration * rng.random() for _ in range(cfg2.topology_mutations))
for mt in mutation_times:
    change = rng.choices(["rename", "dep_add", "dep_remove"], weights=[0.6, 0.2, 0.2])[0]
    if change == "rename":
        victim = rng.choice(canonical)
        old = alias[victim]
        new = f"{victim}-r{rng.randint(2, 9)}"
        print(f"  RENAME: {old} -> {new}  (canonical={victim}  at={mt.strftime('%Y-%m-%dT%H:%M:%SZ')})")
        alias[victim] = new

print()
print("=== FINAL ALIAS STATE ===")
for c, a in alias.items():
    print(f"  {c} -> {a}")
