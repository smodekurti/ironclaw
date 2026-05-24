import pytest
import time
import tempfile
import os
from ironclaw.security.audit import AuditLog

def test_audit_latency(benchmark):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    
    audit = AuditLog(path)
    
    def log_event():
        audit.record("test_event", data="benchmark_payload")
        
    # The benchmark will run this repeatedly and measure execution time
    benchmark(log_event)
    
    audit.close()
    os.remove(path)
