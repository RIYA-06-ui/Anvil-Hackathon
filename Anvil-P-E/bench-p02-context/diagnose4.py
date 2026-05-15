"""
diagnose4.py - Check topology event ordering and canonical resolution for svc-00-r7
Run from: bench-p02-context/
"""
import sys, os
sys.path.insert(0, os.path.abspath('../../persistent-context-engine'))
sys.path.insert(0, os.path.abspath('.'))

from generator import generate, GenConfig
from adapters.myteam import _translate_event, _parse_ts

cfg = GenConfig(seed=42, n_services=6, days=2)
ds = generate(cfg)

print("=== TOPOLOGY EVENTS IN TRAIN (sorted by ts) ===")
topos = [e for e in ds.train_events if e.get("kind") == "topology"]
for t in topos:
    print(f"  ts={t['ts']}  change={t['change']}  from={t.get('from_')}  to={t.get('to')}")

print()
print("=== FIRST 3 REMEDIATION EVENTS (ts) ===")
rems = [e for e in ds.train_events if e.get("kind") == "remediation"]
for r in rems[:5]:
    print(f"  ts={r['ts']}  target={r.get('target')}  incident={r.get('incident_id')}")

print()
print("=== PROBLEM: order of events for svc-00 canonical ===")
# Check if rename event comes BEFORE remediation events for svc-00-r7
rename_events = [(e['ts'], e) for e in ds.train_events if e.get('kind') == 'topology' and e.get('change') == 'rename' and ('svc-00' in str(e.get('from_', '')) or 'svc-00' in str(e.get('to', '')))]
rem_svc00 = [(e['ts'], e) for e in ds.train_events if e.get('kind') == 'remediation' and 'svc-00' in str(e.get('target', ''))]

print("Rename events for svc-00:")
for ts, e in rename_events:
    print(f"  {ts}: {e}")

print("Remediation events for svc-00*:")
for ts, e in rem_svc00:
    print(f"  {ts}: target={e['target']}")

# Now simulate what happens if we process in order
print()
print("=== SIMULATING INGEST ORDER (topology + remediation for svc-00) ===")
all_svc00 = sorted(rename_events + rem_svc00, key=lambda x: x[0])
for ts, e in all_svc00:
    print(f"  {ts}: kind={e['kind']}  " + (f"from={e.get('from_')} to={e.get('to')}" if e['kind']=='topology' else f"target={e.get('target')}  incident={e.get('incident_id')}"))

print()
print("=== TRANSLATED TOPOLOGY EVENTS ===")
for _, e in rename_events:
    translated = _translate_event(e)
    print(f"  translated: {translated}")
