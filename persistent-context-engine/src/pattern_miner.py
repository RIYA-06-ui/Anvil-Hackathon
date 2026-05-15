from collections import defaultdict
from math import sqrt
from datetime import datetime

class IncidentPatternMiner:
    """
    Extract recurring incident shapes (patterns) from resolved incidents.
    """
    
    def __init__(self, topology_tracker, fingerprinter):
        self.topology_tracker = topology_tracker
        self.fingerprinter = fingerprinter
        self.patterns = {}  # pattern_id -> pattern_definition
        self.pattern_stats = {}  # pattern_id -> {count, success_rate, avg_mttr}
    
    def mine_patterns(self, resolved_incidents):
        fingerprints = {}
        for incident_id, events in resolved_incidents.items():
            fp = self.fingerprinter.extract(events)
            fingerprints[incident_id] = fp
            
        clusters = self._cluster_by_behavior(fingerprints)
        
        for cluster_id, incident_ids in clusters.items():
            pattern = self._extract_pattern(incident_ids, fingerprints)
            self.patterns[f"pattern_{cluster_id}"] = pattern
            self.pattern_stats[f"pattern_{cluster_id}"] = self._compute_pattern_stats(
                incident_ids,
                resolved_incidents
            )
            
    def match_patterns(self, current_fp):
        matches = []
        for pattern_id, pattern_def in self.patterns.items():
            similarity = self._cosine_similarity(
                current_fp['vector'],
                pattern_def['canonical_vector']
            )
            if similarity > 0.75:
                matches.append({
                    'pattern_id': pattern_id,
                    'similarity': similarity,
                    'stats': self.pattern_stats.get(pattern_id, {}),
                    'success_rate': self.pattern_stats.get(pattern_id, {}).get('success_rate', 0.0)
                })
        return sorted(matches, key=lambda x: x['similarity'], reverse=True)[:3]

    def _cluster_by_behavior(self, fingerprints):
        clusters = defaultdict(list)
        processed = set()
        for incident_id, fp in fingerprints.items():
            if incident_id in processed:
                continue
            cluster_id = len(clusters)
            clusters[cluster_id].append(incident_id)
            processed.add(incident_id)
            
            for other_id, other_fp in fingerprints.items():
                if other_id in processed:
                    continue
                similarity = self._cosine_similarity(fp['vector'], other_fp['vector'])
                if similarity > 0.75:
                    clusters[cluster_id].append(other_id)
                    processed.add(other_id)
        return clusters
        
    def _cosine_similarity(self, vec1, vec2):
        dot = sum(a * b for a, b in zip(vec1, vec2))
        mag1 = sqrt(sum(a * a for a in vec1))
        mag2 = sqrt(sum(b * b for b in vec2))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)
        
    def _extract_pattern(self, incident_ids, fingerprints):
        avg_vector = [0.0] * len(fingerprints[incident_ids[0]]['vector'])
        for incident_id in incident_ids:
            for i, val in enumerate(fingerprints[incident_id]['vector']):
                avg_vector[i] += val / len(incident_ids)
        return {
            'incident_ids': incident_ids,
            'canonical_vector': avg_vector,
            'description': f"Pattern with {len(incident_ids)} instances",
        }
        
    def _compute_pattern_stats(self, incident_ids, resolved_incidents):
        mttr_values = []
        successes = 0
        
        for incident_id in incident_ids:
            events = resolved_incidents[incident_id]
            signals = [e for e in events if (e.get('kind') if isinstance(e, dict) else getattr(e, 'kind', '')) == 'incident_signal']
            remediations = [e for e in events if (e.get('kind') if isinstance(e, dict) else getattr(e, 'kind', '')) == 'remediation']
            
            if signals and remediations:
                sig_ts = signals[0].get('ts', signals[0].get('timestamp')) if isinstance(signals[0], dict) else getattr(signals[0], 'timestamp', 0)
                rem_ts = remediations[-1].get('ts', remediations[-1].get('timestamp')) if isinstance(remediations[-1], dict) else getattr(remediations[-1], 'timestamp', 0)
                mttr = self._time_delta(sig_ts, rem_ts)
                mttr_values.append(mttr)
                
                if any((r.get('outcome') if isinstance(r, dict) else getattr(r, 'data', {}).get('outcome', '')) == 'resolved' for r in remediations):
                    successes += 1
                    
        return {
            'count': len(incident_ids),
            'success_count': successes,
            'success_rate': successes / len(incident_ids) if incident_ids else 0.0,
            'avg_mttr_minutes': sum(mttr_values) / len(mttr_values) / 60.0 if mttr_values else 0.0,
        }
        
    def _time_delta(self, ts1, ts2):
        if isinstance(ts1, str):
            try: ts1 = datetime.fromisoformat(ts1.replace('Z', '+00:00')).timestamp()
            except: ts1 = 0
        if isinstance(ts2, str):
            try: ts2 = datetime.fromisoformat(ts2.replace('Z', '+00:00')).timestamp()
            except: ts2 = 0
        return abs(float(ts2) - float(ts1))
