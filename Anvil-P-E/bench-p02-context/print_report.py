import json

with open('final_l2_report.json') as f:
    r = json.load(f)

agg = r['aggregated']
sc  = r['score']

print('ANVIL P-02 - Final L2 Battery Report')
print('Seeds: 9999 31415 27182 16180 11235')
print('Config: 12 services, 7 days, fast mode')
print('=' * 50)
print('  recall@5            ', round(agg['recall@5'], 3))
print('  precision@5_mean    ', round(agg['precision@5_mean'], 3))
print('  remediation_acc     ', round(agg['remediation_acc'], 3))
print('  latency_p95_ms      ', round(agg['latency_p95_ms'], 2))
print('  latency_mean_ms     ', round(agg['latency_mean_ms'], 2))
print('  signals_total       ', agg['n_signals_total'])
print('=' * 50)
print('  WEIGHTED AUTOMATED  ', round(sc['weighted_score'], 3), '/', round(sc.get('max_automated', 0.80), 2))
print()
print('Per-seed breakdown:')
for seed_r in r['per_seed']:
    s = seed_r['summary']
    print(
        '  seed=' + str(seed_r['seed']),
        ' recall=' + str(round(s['recall@5'], 3)),
        ' precision=' + str(round(s['precision@5_mean'], 3)),
        ' remediation=' + str(round(s['remediation_acc'], 3)),
        ' p95ms=' + str(round(s['latency_p95_ms'], 2)),
    )
