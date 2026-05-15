class ContextExplainer:
    """
    Generate clear, audit trail narratives.
    """
    
    def explain_context(self, context, signal):
        paragraphs = []
        
        iid = signal.get('incident_id', 'Unknown') if isinstance(signal, dict) else getattr(signal, 'incident_id', 'Unknown')
        ts = signal.get('ts', signal.get('timestamp', 'Unknown')) if isinstance(signal, dict) else getattr(signal, 'timestamp', 'Unknown')
        trigger = signal.get('trigger', 'alert') if isinstance(signal, dict) else getattr(signal, 'trigger', 'alert')
        
        # Paragraph 1
        p1 = f"Incident {iid} was triggered at {ts} by alert: {trigger}. "
        p1 += f"The system has analyzed {len(context.get('related_events', []))} related events."
        paragraphs.append(p1)
        
        # Paragraph 2
        causal_chain = context.get('causal_chain', [])
        if causal_chain:
            p2 = "Root cause analysis: "
            for i, edge in enumerate(causal_chain[:3], 1):
                ctype = edge.get('cause_type', edge.get('edge_type', 'unknown'))
                efftype = edge.get('effect_type', edge.get('to_event_id', 'unknown'))
                conf = edge.get('confidence', 0)
                p2 += f"\n{i}. {ctype} "
                p2 += f"(confidence {conf:.0%}) → "
                p2 += f"{efftype}"
        else:
            p2 = "No clear causal chain identified yet."
        paragraphs.append(p2)
        
        # Paragraph 3
        remediations = context.get('suggested_remediations', [])
        p3 = "Recommended actions: "
        if remediations:
            for rem in remediations[:2]:
                action = rem.get('action', '')
                target = rem.get('target', '')
                conf = rem.get('confidence', 0)
                p3 += f"\n• {action} on {target}"
                if rem.get('historical_outcome'):
                    p3 += f" (resolved similar incident {conf:.0%} of the time)"
        else:
            p3 += "None."
            
        similar_past = context.get('similar_past_incidents', [])
        if similar_past:
            sim = similar_past[0]
            if isinstance(sim, tuple):
                similar_id, similarity = sim[0], sim[1]
            else:
                similar_id = sim.get('incident_id', '')
                similarity = sim.get('similarity', 0)
            p3 += f"\nThis pattern is {similarity:.0%} similar to incident {similar_id}."
            
        paragraphs.append(p3)
        return "\n\n".join(paragraphs)
