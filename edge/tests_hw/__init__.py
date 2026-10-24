"""Hardware bring-up tests for the Raspberry Pi. Each one runs on its own:

    python -m edge.tests_hw.test_camera --real
    python -m edge.tests_hw.test_dht22 --real
    python -m edge.tests_hw.test_stepper --real
    python -m edge.tests_hw.test_backend_link

Each prints PASS / WARN / FAIL with troubleshooting hints and exits 1 on FAIL.
(They are NOT pytest tests - they need the real hardware. Without --real they
follow MOCK_HARDWARE from .env.)
"""
