from .behavioral_signature import BehavioralFingerprint
import math

class BehavioralMatcher:
    """
    Match current incident to historical incidents across topology drift.
    """
    
    def __init__(self, fingerprinter: BehavioralFingerprint):
        self.fingerprinter = fingerprinter
        self.historical_fingerprints = {}  # Map incident_id -> fingerprint
        self.role_mappings = {}  # Track cross-rename mappings
    
    def index_historical_incident(self, incident_id, events):
        """Store behavioral signature of a past incident."""
        fp = self.fingerprinter.extract(events)
        self.historical_fingerprints[incident_id] = fp
    
    def find_similar_incidents(self, current_incident_events, mode="topology_drift_aware"):
        """
        Find matches despite topology drift.
        Returns: [(past_incident_id, similarity_score, role_mapping), ...]
        """
        current_fp = self.fingerprinter.extract(current_incident_events)
        
        matches = []
        for past_id, past_fp in self.historical_fingerprints.items():
            # Three levels of matching:
            
            # Level 1: Structural hash match (exact behavioral shape)
            if current_fp['structure_hash'] == past_fp['structure_hash']:
                similarity = 1.0
                role_mapping = self._infer_role_mapping(
                    current_fp['roles'], 
                    past_fp['roles']
                )
                matches.append((past_id, similarity, role_mapping))
            else:
                # Level 2: Vector similarity (behavioral proximity)
                similarity = self._cosine_similarity(
                    current_fp['vector'], 
                    past_fp['vector']
                )
                if similarity > 0.75:  # Threshold for behavioral equivalence
                    role_mapping = self._infer_role_mapping(
                        current_fp['roles'], 
                        past_fp['roles']
                    )
                    matches.append((past_id, similarity, role_mapping))
            
            # Level 3: Temporal pattern match (deltas, not absolute times)
            if mode == "topology_drift_aware":
                temporal_similarity = self._match_temporal_patterns(
                    current_fp['abstracted_chain'],
                    past_fp['abstracted_chain']
                )
                if temporal_similarity > 0.8:
                    role_mapping = self._infer_role_mapping(
                        current_fp['roles'], 
                        past_fp['roles']
                    )
                    matches.append((past_id, temporal_similarity * 0.9, role_mapping))
        
        # Sort by similarity, remove duplicates
        unique_matches = {}
        for m in matches:
            if m[0] not in unique_matches or unique_matches[m[0]][1] < m[1]:
                unique_matches[m[0]] = m
                
        matches_list = sorted(unique_matches.values(), key=lambda x: x[1], reverse=True)
        return matches_list[:5]  # Top 5
    
    def find_similar_incidents_fast(self, signal):
        # Fallback fast matcher using precomputed fingerprints
        return []
        
    def find_similar_incidents_deep(self, related_events, mode="topology_drift_aware_full"):
        return self.find_similar_incidents(related_events, mode=mode)
        
    def record_topology_change(self, from_svc, to_svc):
        pass

    def _infer_role_mapping(self, current_roles, past_roles):
        """
        Map roles from historical incident to current incident.
        Returns: {"payments-svc": "billing-svc", ...}
        """
        mapping = {}
        for role_key in current_roles:
            current_name = current_roles[role_key]
            past_name = past_roles.get(role_key)
            if current_name and past_name and current_name != past_name:
                # If they are lists
                if isinstance(current_name, list) and isinstance(past_name, list):
                    pass # complex mapping
                else:
                    mapping[past_name] = current_name
        return mapping
    
    def _cosine_similarity(self, vec1, vec2):
        """Standard cosine similarity between two vectors."""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)
    
    def _match_temporal_patterns(self, current_chain, past_chain):
        """Match the TIMING DELTAS, not absolute times."""
        if len(current_chain) != len(past_chain):
            return 0.0
        
        current_deltas = [e['temporal_delta_ms'] for e in current_chain]
        past_deltas = [e['temporal_delta_ms'] for e in past_chain]
        
        matches = 0
        for cd, pd in zip(current_deltas, past_deltas):
            if pd == 0:
                if cd < 500:
                    matches += 1
            elif abs(cd - pd) / pd < 0.3:
                matches += 1
        
        return matches / len(current_deltas) if current_deltas else 0.0
