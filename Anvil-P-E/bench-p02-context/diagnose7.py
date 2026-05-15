"""
diagnose7.py - Analyze recall failure patterns across multiple seeds
Run from: bench-p02-context/
"""
import sys, os
sys.path.insert(0, os.path.abspath('../../persistent-context-engine'))
sys.path.insert(0, os.path.abspath('.'))

from generator import generate, GenConfig
from adapters.myteam import Engine
from metrics import score_match, score_remediation

def run_seed(seed, n_services=12, days=7):
    cfg = GenConfig(seed=seed, n_services=n_services, days=days)
    ds = generate(cfg)

    engine = Engine()
    engine.ingest(ds.train_events)
    engine.ingest(ds.eval_events)

    inner = engine._engine
    im = inner._incident_memory

    results = []
    for sig, gt in zip(ds.eval_signals, ds.ground_truth):
        ctx = engine.reconstruct_context(sig, mode='fast')
        in_top_k, precision = score_match(ctx, gt, k=5)
        past_ids = [p.get('incident_id','') for p in ctx.get('similar_past_incidents', [])]
        past_families = [iid.rsplit('-',1)[-1] for iid in past_ids]

        results.append({
            'signal': sig['incident_id'],
            'sig_family': sig['incident_id'].rsplit('-',1)[-1],
            'gt_family': str(gt['family']),
            'svc': sig.get('service',''),
            'in_top_k': in_top_k,
            'precision': precision,
            'past_families': past_families,
            'n_past': len(past_ids),
        })

    # Count IncidentMemory distribution
    im_dist = {cid: len(incs) for cid, incs in im._by_canonical.items()}
    ig = inner._identity
    alias_dist = {}
    for cid, n in im_dist.items():
        aliases = ig.get_all_aliases(cid)
        alias_dist[tuple(aliases[:3])] = n

    return results, alias_dist

print('=== SEED 9999 (worst recall=0.3) ===')
results, im_dist = run_seed(9999)
fails = [r for r in results if not r['in_top_k']]
hits  = [r for r in results if r['in_top_k']]
print(f'Hits {len(hits)}/10:')
for r in hits:
    print(f'  HIT  signal={r["signal"]} gt_fam={r["gt_family"]} past_fam={r["past_families"][:3]}')
print(f'Misses {len(fails)}/10:')
for r in fails:
    print(f'  MISS signal={r["signal"]} gt_fam={r["gt_family"]} svc={r["svc"]} n_past={r["n_past"]} past_fam={r["past_families"][:5]}')
print()
print('IncidentMemory distribution (seed 9999):')
for aliases, n in sorted(im_dist.items(), key=lambda x: -x[1]):
    print(f'  {aliases}: {n} incidents')

print()
print('=== SEED 42 (best recall from previous) ===')
results42, _ = run_seed(42, n_services=6, days=2)
hits42  = [r for r in results42 if r['in_top_k']]
fails42 = [r for r in results42 if not r['in_top_k']]
print(f'Hits {len(hits42)}/10  Misses {len(fails42)}/10')
for r in fails42:
    print(f'  MISS signal={r["signal"]} gt_fam={r["gt_family"]} svc={r["svc"]} n_past={r["n_past"]} past_fam={r["past_families"][:5]}')
