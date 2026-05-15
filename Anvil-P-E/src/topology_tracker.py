class TopologyTracker:
    """
    Track topology mutations and maintain mappings across drift.
    """
    
    def __init__(self):
        self.rename_log = {}  # old_name -> list of new names over time
        self.dependency_history = {}  # timestamp -> dependency graph
        self.current_mapping = {}  # current_name -> original_name
    
    def record_rename(self, event):
        """Process topology 'rename' event."""
        # Use get fallback for dict/object access
        data = event.get('data', {}) if isinstance(event, dict) else getattr(event, 'data', {})
        old_name = event.get('from', data.get('old_service')) if isinstance(event, dict) else getattr(event, 'from', data.get('old_service'))
        new_name = event.get('to', data.get('new_service')) if isinstance(event, dict) else getattr(event, 'to', data.get('new_service'))
        timestamp = event.get('ts', event.get('timestamp')) if isinstance(event, dict) else getattr(event, 'timestamp', 0)
        
        if not old_name or not new_name:
            return

        if old_name not in self.rename_log:
            self.rename_log[old_name] = [(new_name, timestamp)]
        else:
            self.rename_log[old_name].append((new_name, timestamp))
        
        original = self.current_mapping.get(old_name, old_name)
        self.current_mapping[new_name] = original
        if old_name in self.current_mapping:
            del self.current_mapping[old_name]
    
    def record_dependency_shift(self, event):
        """Process topology 'dependency_shift' event."""
        timestamp = event.get('ts', event.get('timestamp')) if isinstance(event, dict) else getattr(event, 'timestamp', 0)
        data = event.get('data', {}) if isinstance(event, dict) else getattr(event, 'data', {})
        old_deps = data.get('old_deps', {})
        new_deps = data.get('new_deps', {})
        service = event.get('service') if isinstance(event, dict) else getattr(event, 'raw_service_name', getattr(event, 'service', ''))
        
        self.dependency_history[timestamp] = {
            'old': old_deps,
            'new': new_deps,
            'affected_service': service
        }
    
    def get_historical_name(self, current_name, at_time=None):
        """Reverse map: given current name, find original name at a time."""
        for original, renames in self.rename_log.items():
            for new_name, rename_time in renames:
                if new_name == current_name:
                    if at_time is None or rename_time <= at_time:
                        return original
        return current_name
    
    def normalize_service_name(self, name):
        """Get the canonical/original name of a service."""
        return self.current_mapping.get(name, name)
