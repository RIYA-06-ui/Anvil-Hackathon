"""
diagnose6.py - Trace exact canonical state for svc-00-r7 after both ingest calls
"""
import sys, os
sys.path.insert(0, os.path.abspath('../../persistent-context-engine'))
sys.path.insert(0, os.path.abspath('.'))

from generator import generate, GenConfig
from adapters.myteam import Engine, _translate_event

cfg = GenConfig(seed=42, n_services=6, days=2)
ds = generate(cfg)

engine = Engine()
engine.ingest(ds.train_events)

inner = engine._engine
ig = inner._identity
im = inner._incident_memory

print("=== AFTER train ingest ===")
print(f"IdentityGraph aliases for svc-00*:")
for name, cid in ig.alias_map.items():
    if 'svc-00' in name:
        print(f"  {name} -> {cid}  entity_exists={cid in ig.entities}")

print(f"IncidentMemory canonicals with svc-00 incidents:")
for cid, incs in im._by_canonical.items():
    if incs:
        sample_inc = incs[0]
        print(f"  {cid} -> {len(incs)} incidents, sample={sample_inc.incident_id}")

print()
engine.ingest(ds.eval_events)

print("=== AFTER eval ingest ===")
print(f"IdentityGraph aliases for svc-00*:")
for name, cid in ig.alias_map.items():
    if 'svc-00' in name:
        print(f"  {name} -> {cid}  entity_exists={cid in ig.entities}  aliases={ig.get_all_aliases(cid)}")

print(f"IncidentMemory all canonicals:")
for cid, incs in im._by_canonical.items():
    print(f"  {cid} -> {len(incs)} incidents: {[i.incident_id for i in incs[:3]]}")

print()
print("=== ROOT CAUSE: svc-00-r7 signal resolves to which canonical? ===")
signal_canonical = ig.resolve("svc-00-r7")
print(f"ig.resolve('svc-00-r7') = {signal_canonical}")
print(f"IncidentMemory has incidents for that canonical: {len(im._by_canonical.get(signal_canonical, []))}")

print()
print("=== _merged_pairs ===")
print(engine._merged_pairs)

engine.close()
