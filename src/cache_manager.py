import time

class CacheManager:
    """
    Multi-layer caching for latency optimization.
    """
    
    def __init__(self, max_entries=10000):
        # L1: Hot cache for recent incidents (in-memory)
        self.hot_cache = {}  # incident_id -> Context
        self.hot_max = 1000
        
        # L2: Fingerprint cache (pre-computed, indexed)
        self.fingerprint_cache = {}  # incident_id -> BehavioralFingerprint
        
        # L3: Causal chain cache
        self.causal_cache = {}  # incident_id -> causal_chain
        
        # LRU eviction
        self.access_times = {}
    
    def get_or_compute_context(self, signal, compute_fn):
        """
        Try to return cached context; if not, compute and cache.
        """
        incident_id = signal.get('incident_id') if isinstance(signal, dict) else getattr(signal, 'incident_id', '')
        
        # Check L1
        if incident_id and incident_id in self.hot_cache:
            return self.hot_cache[incident_id]
        
        # Compute
        context = compute_fn(signal)
        
        # Cache in L1 (with LRU)
        if incident_id:
            if len(self.hot_cache) >= self.hot_max:
                oldest_id = min(self.access_times, key=self.access_times.get)
                del self.hot_cache[oldest_id]
                del self.access_times[oldest_id]
            
            self.hot_cache[incident_id] = context
            self.access_times[incident_id] = time.time()
        
        return context
    
    def warm_caches(self, recent_incidents, fingerprinter, graph_engine):
        """
        Pre-compute fingerprints and causal chains for recent incidents.
        """
        for incident_id, events in recent_incidents.items():
            self.fingerprint_cache[incident_id] = fingerprinter.extract(events)
            if events:
                self.causal_cache[incident_id] = graph_engine.build_causal_chain(
                    events[0],  # signal
                    events
                )
