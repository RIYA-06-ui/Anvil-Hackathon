class ContextExplainer:
    """
    Generate clear, audit trail narratives.
    """
    
    def explain_context(self, context, signal):
        iid = signal.get('incident_id', 'Unknown') if isinstance(signal, dict) else getattr(signal, 'incident_id', 'Unknown')
        ts = signal.get('ts', signal.get('timestamp', 'Unknown')) if isinstance(signal, dict) else getattr(signal, 'timestamp', 'Unknown')
        
        # Build rename context
        service = signal.get('service', '') if isinstance(signal, dict) else getattr(signal, 'service', '')
        original_service = context.get('_topology_mapping', service) # simplified for now
        rename_str = f" (now renamed {service})" if original_service and original_service != service else ""
        
        # Build causal narrative
        causal_chain = context.get('causal_chain', [])
        if causal_chain:
            root = causal_chain[0]
            leaf = causal_chain[-1]
            root_type = root.get('cause_type', root.get('edge_type', 'unknown'))
            p1 = f"Deploy of {original_service}{rename_str} at {ts} caused a {root_type}, which triggered upstream errors. "
        else:
            p1 = f"Incident {iid} on {service}{rename_str} was triggered at {ts}. "
            
        # Add similar incident matches
        similar_past = context.get('similar_past_incidents', [])
        if similar_past:
            sim = similar_past[0]
            similar_id = sim.get('incident_id', '') if isinstance(sim, dict) else sim[0]
            p1 += f"This matches {similar_id} with the same pattern."
        else:
            p1 += "No similar historical incidents found."

        return p1
