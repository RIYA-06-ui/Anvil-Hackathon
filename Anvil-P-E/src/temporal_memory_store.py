class TemporalMemoryStore:
    """
    Store operational memory indexed by behavior, not name.
    Handle topology drift gracefully.
    """
    
    def __init__(self, topology_tracker):
        self.topology_tracker = topology_tracker
        self.behavioral_index = {}
        self.temporal_index = {}
        self.causal_index = {}
        self.remediations = {}
    
    def store_event(self, event):
        """Store event with topology-aware indexing."""
        timestamp = event.get('ts', event.get('timestamp')) if isinstance(event, dict) else getattr(event, 'timestamp', 0)
        service = event.get('service') if isinstance(event, dict) else getattr(event, 'raw_service_name', getattr(event, 'service', ''))
        
        if service:
            if isinstance(event, dict):
                event['normalized_service'] = self.topology_tracker.normalize_service_name(service)
            else:
                setattr(event, 'normalized_service', self.topology_tracker.normalize_service_name(service))
        
        # Index temporally
        if timestamp not in self.temporal_index:
            self.temporal_index[timestamp] = []
        self.temporal_index[timestamp].append(event)
        
        # Index behaviorally
        kind = event.get('kind') if isinstance(event, dict) else getattr(event, 'kind', '')
        if kind == 'metric':
            data = event.get('data', {}) if isinstance(event, dict) else getattr(event, 'data', {})
            name = event.get('name', data.get('name', '')) if isinstance(event, dict) else getattr(event, 'name', data.get('name', ''))
            val = event.get('value', data.get('value', 0)) if isinstance(event, dict) else getattr(event, 'value', data.get('value', 0))
            
            behavior_sig = (
                'METRIC_ANOMALY',
                name,
                val > self._get_baseline(name)
            )
            if behavior_sig not in self.behavioral_index:
                self.behavioral_index[behavior_sig] = []
            self.behavioral_index[behavior_sig].append(event)
            
    def _get_baseline(self, name):
        return 0 # simplified
        
    def query_by_behavior(self, behavioral_signature, time_window=None):
        results = self.behavioral_index.get(behavioral_signature, [])
        if time_window:
            start, end = time_window
            results = [e for e in results if start <= (e.get('ts', e.get('timestamp')) if isinstance(e, dict) else getattr(e, 'timestamp', 0)) <= end]
        return results
    
    def query_across_renames(self, original_service, behavior):
        all_names = [original_service]
        if original_service in self.topology_tracker.rename_log:
            for new_name, _ in self.topology_tracker.rename_log[original_service]:
                all_names.append(new_name)
        
        results = []
        for name in all_names:
            events = [
                e for events_list in self.temporal_index.values()
                for e in events_list
                if (e.get('service') if isinstance(e, dict) else getattr(e, 'raw_service_name', getattr(e, 'service', ''))) == name or 
                   (e.get('normalized_service') if isinstance(e, dict) else getattr(e, 'normalized_service', '')) == original_service
            ]
            results.extend(events)
        
        return results

    def get_events_for_incident(self, incident_id):
        # Dummy implementation since we don't have real event tying yet
        return []

    def get_remediations(self, incident_id):
        return self.remediations.get(incident_id, [])
