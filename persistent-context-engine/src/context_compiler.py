class ContextCompiler:
    """
    Assemble high-signal context from raw events and causal chains.
    """
    
    def __init__(self, signal_scorer, topology_tracker):
        self.scorer = signal_scorer
        self.topology_tracker = topology_tracker
    
    def compile(self, incident_signal, related_events, causal_chain, similar_incidents):
        scored_events = [
            (event, self.scorer.score_event(event, incident_signal, {
                'causal_chain': causal_chain
            }))
            for event in related_events
        ]
        scored_events.sort(key=lambda x: x[1], reverse=True)
        
        mode = incident_signal.get('mode', 'fast') if isinstance(incident_signal, dict) else getattr(incident_signal, 'mode', 'fast')
        k = 10 if mode == 'fast' else 20
        top_events = [event for event, _ in scored_events[:k]]
        
        unique_events = {}
        for event in top_events:
            eid = event.get('id', event.get('event_id')) if isinstance(event, dict) else getattr(event, 'event_id', getattr(event, 'id', ''))
            unique_events[eid] = event
            
        final_events = sorted(
            unique_events.values(),
            key=lambda e: e.get('ts', e.get('timestamp', 0)) if isinstance(e, dict) else getattr(e, 'timestamp', 0)
        )
        
        return {
            'related_events': final_events,
            'causal_chain': causal_chain,
            'similar_past_incidents': similar_incidents,
            'suggested_remediations': self._compile_remediations(
                similar_incidents,
                incident_signal
            ),
            'confidence': self._compute_confidence(
                causal_chain,
                similar_incidents,
                final_events
            ),
            'explain': self._generate_explanation(
                incident_signal,
                final_events,
                causal_chain,
                similar_incidents
            )
        }
    
    def _compile_remediations(self, similar_incidents, signal):
        remediations = []
        for match in similar_incidents[:3]:
            # tuple can be (past_id, similarity, role_mapping) or IncidentMatch dict depending on integration
            if isinstance(match, tuple):
                past_id, similarity, role_mapping = match
                action = "rollback"
                target = "service"
            else:
                past_id = match.get('incident_id')
                similarity = match.get('similarity', 0)
                action = match.get('remediation', 'rollback')
                target = "service"
                
            current_fix = {
                'action': action,
                'target': target,
                'version': 'N/A',
                'historical_outcome': 'resolved',
                'confidence': similarity * 0.95,
                'rationale': f"This remediation succeeded similarly in incident {past_id}"
            }
            remediations.append(current_fix)
        return remediations
    
    def _compute_confidence(self, causal_chain, similar_incidents, events):
        causal_strength = sum(
            edge.get('confidence', 0) for edge in causal_chain
        ) / len(causal_chain) if causal_chain else 0.0
        
        if similar_incidents:
            sims = [sim[1] if isinstance(sim, tuple) else sim.get('similarity', 0) for sim in similar_incidents[:3]]
            historical_matches = sum(sims) / len(sims)
        else:
            historical_matches = 0.0
            
        event_kinds = set((e.get('kind') if isinstance(e, dict) else getattr(e, 'kind', '')) for e in events)
        event_diversity = len(event_kinds) / 6.0
        
        return min((causal_strength + historical_matches + event_diversity) / 3.0, 0.95)
    
    def _generate_explanation(self, signal, events, causal_chain, similar_incidents):
        iid = signal.get('incident_id', 'Unknown') if isinstance(signal, dict) else getattr(signal, 'incident_id', 'Unknown')
        trigger = signal.get('trigger', 'alert') if isinstance(signal, dict) else getattr(signal, 'trigger', 'alert')
        narrative = f"Incident {iid} was triggered by {trigger}.\n\n"
        
        if causal_chain:
            narrative += "Causal sequence:\n"
            for i, edge in enumerate(causal_chain[:5], 1):
                ctype = edge.get('cause_type', edge.get('edge_type', 'unknown'))
                efftype = edge.get('effect_type', edge.get('to_event_id', 'unknown'))
                conf = edge.get('confidence', 0)
                narrative += f"{i}. {ctype} (confidence: {conf:.1%})\n"
                narrative += f"   ↓ caused ↓\n"
                narrative += f"{i}. {efftype}\n\n"
                
        if similar_incidents:
            sim = similar_incidents[0]
            score = sim[1] if isinstance(sim, tuple) else sim.get('similarity', 0)
            iid_sim = sim[0] if isinstance(sim, tuple) else sim.get('incident_id', '')
            narrative += f"Similar incident history: "
            if score > 0.85:
                narrative += f"Incident {iid_sim} shows {score:.0%} behavioral match. "
            narrative += "\n\n"
            
        narrative += f"Key evidence ({len(events)} events examined):\n"
        for event in events[:3]:
            kind = event.get('kind', '') if isinstance(event, dict) else getattr(event, 'kind', '')
            msg = event.get('msg', event.get('name', 'N/A')) if isinstance(event, dict) else getattr(event, 'data', {}).get('msg', 'N/A')
            narrative += f"- {kind}: {msg}\n"
            
        return narrative
