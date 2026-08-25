import time
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass


class CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal operation: n8n requests pass through
    OPEN = "OPEN"          # Failing: n8n requests immediately bypassed (fail-open)
    HALF_OPEN = "HALF_OPEN"# Probing: testing if n8n service recovered


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 2
    recovery_timeout_seconds: float = 60.0
    execution_timeout_seconds: float = 3.0


class CircuitBreaker:
    """
    CTO Fail-Open Circuit Breaker.
    Guarantees that n8n failures or slow responses never block developer velocity.
    Auto-trips to OPEN after consecutive errors and auto-resets after cooldown.
    """

    def __init__(self, name: str = "n8n_pipeline", config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.last_success_time: float = 0.0
        self.last_error_message: Optional[str] = None

    def can_execute(self) -> bool:
        """Determines whether to attempt calling the external service or fail-open immediately."""
        if self.state == CircuitState.CLOSED:
            return True

        # Check if recovery cooldown period has expired
        if self.state == CircuitState.OPEN:
            now = time.time()
            if (now - self.last_failure_time) >= self.config.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # In half-open, allow one probe request
            return True

        return True

    def record_success(self):
        """Records successful execution and resets the breaker to CLOSED state."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_success_time = time.time()
        self.last_error_message = None

    def record_failure(self, error_message: str = "Unknown error"):
        """Records a failure and trips to OPEN if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.last_error_message = error_message

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN

    def trip(self, reason: str = "Manual or immediate trip"):
        """Manually trips the circuit breaker to OPEN state."""
        self.state = CircuitState.OPEN
        self.last_failure_time = time.time()
        self.last_error_message = reason


# Global circuit breaker instance for the research pipeline
_global_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    global _global_breaker
    if _global_breaker is None:
        _global_breaker = CircuitBreaker()
    return _global_breaker
