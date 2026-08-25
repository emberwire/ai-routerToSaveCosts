import pytest
import time
from ai_router.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


def test_circuit_breaker_flow():
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=0.1)
    breaker = CircuitBreaker(config=config)

    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True

    # 1 failure
    breaker.record_failure("error 1")
    assert breaker.state == CircuitState.CLOSED

    # 2 failures -> trips to OPEN
    breaker.record_failure("error 2")
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False

    # Wait for recovery timeout
    time.sleep(0.15)
    assert breaker.can_execute() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Success in half-open resets to CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
