"""End-to-end worked example tests."""

import unittest
from datetime import datetime
from src.engine import PersistentContextEngine
from src.types import Event, IncidentSignal


class TestIntegration(unittest.TestCase):
    """Integration tests for the full engine workflow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.engine = PersistentContextEngine()
    
    def test_full_workflow(self):
        """Test complete engine workflow: ingest and reconstruct."""
        # Create events
        events = [
            {
                'timestamp': datetime.now().timestamp(),
                'kind': 'log',
                'service': 'service_a',
                'event_id': 'evt-1',
                'data': {'message': 'error 500', 'level': 'ERROR'}
            },
            {
                'timestamp': datetime.now().timestamp(),
                'kind': 'metric',
                'service': 'service_b',
                'event_id': 'evt-2',
                'data': {'metric_name': 'latency_p99', 'value': 5000}
            }
        ]
        
        # Ingest events
        self.engine.ingest(events)
        
        # Create incident signal for context reconstruction
        signal: IncidentSignal = {
            'incident_id': 'incident_001',
            'service': 'service_a',
            'timestamp': datetime.now().timestamp(),
            'severity': 'high',
            'data': {}
        }
        
        # Reconstruct context
        context = self.engine.reconstruct_context(signal, mode='fast')
        
        # Verify reconstruction returned valid context shape
        self.assertEqual(context['incident_id'], 'incident_001')
        self.assertIn('related_events', context)
        self.assertIn('causal_chain', context)
        self.assertIn('confidence', context)
        self.assertIsInstance(context['confidence'], float)


if __name__ == '__main__':
    unittest.main()
