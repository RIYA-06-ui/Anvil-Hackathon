from datetime import datetime, timedelta

class SignalScorer:
    """
    Rank events by relevance to the incident.
    Prioritize high-signal evidence.
    """
    
    def __init__(self):
        self.weights = {
            'direct_causation': 1.0,
            'deploy_adjacent': 0.8,
            'correlated_metric': 0.7,
            'topology_adjacent': 0.6,
            'background_noise': 0.1,
        }
    
    def score_event(self, event, incident_signal, context_so_far):
        score = 0.0
        
        # Check: is this event in the direct causal chain?
        if self._is_in_causal_chain(event, context_so_far.get('causal_chain')):
            score += self.weights['direct_causation']
            
        kind = event.get('kind') if isinstance(event, dict) else getattr(event, 'kind', '')
        
        # Check: is this a deploy adjacent to the incident?
        if kind == 'deploy' and self._is_temporally_adjacent(event, incident_signal, window_ms=300000):
            score += self.weights['deploy_adjacent']
        
        # Check: does this metric correlate with others?
        if kind == 'metric' and self._correlates_with_other_metrics(event, context_so_far):
            score += self.weights['correlated_metric']
        
        # Penalty: is this just noise?
        if kind == 'log' and self._is_likely_noise(event):
            score += self.weights['background_noise']
            
        if score == 0.0:
            score = 0.3 # baseline
            
        return score
    
    def _is_in_causal_chain(self, event, causal_chain):
        if not causal_chain:
            return False
        event_id = event.get('id', event.get('event_id')) if isinstance(event, dict) else getattr(event, 'event_id', getattr(event, 'id', ''))
        for edge in causal_chain:
            if edge.get('cause_id', edge.get('from_event_id')) == event_id or edge.get('effect_id', edge.get('to_event_id')) == event_id:
                return True
        return False
    
    def _is_temporally_adjacent(self, event, incident_signal, window_ms=300000):
        # We assume ts/timestamp is epoch float for simplicity here
        ev_ts = event.get('ts', event.get('timestamp', 0)) if isinstance(event, dict) else getattr(event, 'timestamp', 0)
        sig_ts = incident_signal.get('ts', incident_signal.get('timestamp', 0)) if isinstance(incident_signal, dict) else getattr(incident_signal, 'timestamp', 0)
        
        if isinstance(ev_ts, str):
            try: ev_ts = datetime.fromisoformat(ev_ts.replace('Z', '+00:00')).timestamp()
            except: ev_ts = 0
        if isinstance(sig_ts, str):
            try: sig_ts = datetime.fromisoformat(sig_ts.replace('Z', '+00:00')).timestamp()
            except: sig_ts = 0
            
        delta = abs(ev_ts - sig_ts) * 1000
        return delta <= window_ms
    
    def _correlates_with_other_metrics(self, event, context):
        return True # Simplified
    
    def _is_likely_noise(self, event):
        common_noise = {'cache miss', 'connection timeout', 'retry attempt'}
        msg = event.get('msg', '') if isinstance(event, dict) else getattr(event, 'data', {}).get('msg', '')
        return any(phrase in msg.lower() for phrase in common_noise)
