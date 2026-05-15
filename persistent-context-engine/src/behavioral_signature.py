import hashlib

class BehavioralFingerprint:
    """
    Extract a signature that is INVARIANT under topology drift.
    NOT based on service names or fixed identifiers.
    """
    
    def __init__(self):
        pass
    
    def extract(self, incident_events):
        """
        Convert a sequence of events into a canonical, renamable form.
        """
        # Step 1: Identify behavioral roles (which service is primary? which is client?)
        roles = self._infer_roles(incident_events)
        
        # Step 2: Build role-based causal chain
        abstracted_chain = self._abstract_causal_chain(
            incident_events, 
            roles
        )
        
        # Step 3: Encode as vector + structural hash
        vector = self._vectorize_behavior(abstracted_chain)
        structure_hash = self._compute_behavior_hash(abstracted_chain)
        
        return {
            "vector": vector,           # For similarity matching
            "structure_hash": structure_hash,  # For exact matching after normalization
            "roles": roles,             # For mapping current incident to historical
            "abstracted_chain": abstracted_chain,
        }
    
    def _infer_roles(self, events):
        """
        Determine: which service is the initiator? Which receives the error?
        Which gets rolled back? Parameterized by count, not name.
        """
        initiators = {}
        error_receivers = {}
        targets_of_action = {}
        
        for event in events:
            # Handle both dict access and attribute access just in case
            kind = event.get('kind') if isinstance(event, dict) else event.kind
            service = event.get('service') if isinstance(event, dict) else getattr(event, 'raw_service_name', getattr(event, 'service', None))
            level = event.get('level') if isinstance(event, dict) else getattr(event, 'data', {}).get('level', '')
            target = event.get('target') if isinstance(event, dict) else getattr(event, 'data', {}).get('target', '')
            action = event.get('action') if isinstance(event, dict) else getattr(event, 'data', {}).get('action', '')
            
            if kind == 'deploy':
                if service: initiators[service] = initiators.get(service, 0) + 1
            elif kind == 'log' and (level == 'error' or level == 'ERROR'):
                if service: error_receivers[service] = error_receivers.get(service, 0) + 1
            elif kind == 'remediation':
                if target: targets_of_action[target] = action
        
        # Return ROLES not names
        services_set = set()
        for event in events:
            service = event.get('service') if isinstance(event, dict) else getattr(event, 'raw_service_name', getattr(event, 'service', None))
            kind = event.get('kind') if isinstance(event, dict) else event.kind
            if kind in ('deploy', 'log') and service:
                services_set.add(service)

        return {
            "primary_actor": max(initiators, key=initiators.get) if initiators else None,
            "error_sink": max(error_receivers, key=error_receivers.get) if error_receivers else None,
            "remediation_target": list(targets_of_action.keys())[0] if targets_of_action else None,
            "role_transition": list(services_set)
        }
    
    def _abstract_causal_chain(self, events, roles):
        """
        Build causal chain that survives renaming.
        """
        abstracted = []
        for edge in self._build_causal_edges(events):
            abstracted_edge = {
                "from_role": self._role_of_service(edge['from'], roles),
                "to_role": self._role_of_service(edge['to'], roles),
                "event_type": edge['type'],
                "confidence": edge['confidence'],
                "temporal_delta_ms": edge['temporal_delta_ms'],
            }
            abstracted.append(abstracted_edge)
        return abstracted
    
    def _role_of_service(self, service_name, roles):
        for role, service_list in roles.items():
            if isinstance(service_list, list) and service_name in service_list:
                return role
            elif service_name == service_list:
                return role
        return "OTHER"
    
    def _vectorize_behavior(self, abstracted_chain):
        vector = [0.0] * 32
        
        role_sequence = [edge['from_role'] for edge in abstracted_chain]
        for i, role in enumerate(role_sequence[:8]):
            vector[i] = hash(role) % 256 / 256.0
        
        temporal_deltas = [edge['temporal_delta_ms'] for edge in abstracted_chain]
        mean_delta = sum(temporal_deltas) / len(temporal_deltas) if temporal_deltas else 0
        vector[8] = min(mean_delta / 10000.0, 1.0)
        
        event_types = {}
        for edge in abstracted_chain:
            event_types[edge['event_type']] = event_types.get(edge['event_type'], 0) + 1
        for i, (etype, count) in enumerate(event_types.items()):
            if i < 10:
                vector[9 + i] = count / max(1, len(abstracted_chain))
        
        return vector
    
    def _compute_behavior_hash(self, abstracted_chain):
        shape_str = "|".join([
            f"{edge['from_role']}-{edge['event_type']}-{edge['to_role']}"
            for edge in abstracted_chain
        ])
        return hashlib.md5(shape_str.encode()).hexdigest()
    
    def _build_causal_edges(self, events):
        """Construct causal edges from event stream."""
        edges = []
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.get('ts', getattr(e, 'timestamp', 0)))
        for i, ev_a in enumerate(sorted_events):
            for ev_b in sorted_events[i+1:i+6]:  # Look ahead 5 events
                ts_a = ev_a.get('ts', getattr(ev_a, 'timestamp', 0))
                ts_b = ev_b.get('ts', getattr(ev_b, 'timestamp', 0))
                delta = abs(ts_b - ts_a) * 1000
                if delta > 300000: continue # 5 minutes

                service_a = ev_a.get('service') if isinstance(ev_a, dict) else getattr(ev_a, 'raw_service_name', getattr(ev_a, 'service', ''))
                service_b = ev_b.get('service') if isinstance(ev_b, dict) else getattr(ev_b, 'raw_service_name', getattr(ev_b, 'service', ''))
                kind_a = ev_a.get('kind') if isinstance(ev_a, dict) else getattr(ev_a, 'kind', '')
                
                if service_a and service_b:
                    edges.append({
                        "from": service_a,
                        "to": service_b,
                        "type": kind_a,
                        "confidence": 0.8 if service_a != service_b else 0.5,
                        "temporal_delta_ms": delta
                    })
        return edges
