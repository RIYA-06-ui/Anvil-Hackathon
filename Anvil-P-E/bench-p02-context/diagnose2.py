"""
diagnose2.py - Diagnose why similar_past_count=0 and remediations=[]
Run from: bench-p02-context/
"""
import sys, os
sys.path.insert(0, os.path.abspath('../../persistent-context-engine'))
sys.path.insert(0, os.path.abspath('.'))

from generator import generate, GenConfig
from adapters.myteam import Engine, _translate_event, _parse_ts

cfg = GenConfig(seed=42, n_services=6, days=2)
ds = generate(cfg)

from collections import Counter
train_kinds = Counter(e['kind'] for e in ds.train_events)
print('Train event kinds:', dict(train_kinds))
print('Eval event kinds:', Counter(e['kind'] for e in ds.eval_events))
print('Num signals:', len(ds.eval_signals))
print()

print('=== GROUND TRUTH SAMPLE ===')
for gt in ds.ground_truth[:3]:
    print(gt)

print()
print('=== SAMPLE TRAIN REMEDIATION EVENTS ===')
rems = [e for e in ds.train_events if e.get('kind') == 'remediation']
for r in rems[:3]:
    print('  RAW:', r)
    print('  TRANSLATED:', _translate_event(r))
    print()

print('=== SAMPLE EVAL SIGNALS ===')
for s in ds.eval_signals[:3]:
    print(s)

print()
print('=== INGEST & RECONSTRUCT TEST ===')
engine = Engine()
engine.ingest(ds.train_events)
engine.ingest(ds.eval_events)

inner = engine._engine
print(f'EventStore total_events: {inner.event_count}')
print(f'IncidentMemory total_incidents: {inner._incident_memory.total_incidents}')
print(f'IdentityGraph aliases: {list(inner._identity.alias_map.items())[:10]}')

# Peek at incident memory
for cid, incs in inner._incident_memory._by_canonical.items():
    print(f'  canonical={cid}: {len(incs)} incidents -> {[i.incident_id for i in incs[:3]]}')

# Test one signal
sig = ds.eval_signals[0]
gt = ds.ground_truth[0]
print()
print(f'Signal: {sig}')
print(f'Ground truth: {gt}')
ctx = engine.reconstruct_context(sig, mode='fast')
print(f'related_events: {len(ctx["related_events"])}')
print(f'similar_past_incidents: {ctx["similar_past_incidents"]}')
print(f'suggested_remediations: {ctx["suggested_remediations"]}')

from metrics import score_match, score_remediation
in_top_k, precision = score_match(ctx, gt, k=5)
rem_ok = score_remediation(ctx, gt)
print(f'score_match: in_top_k={in_top_k}, precision={precision}')
print(f'score_remediation: {rem_ok}')
print(f'Expected remediation: {gt["expected_remediation"]}')

engine.close()
