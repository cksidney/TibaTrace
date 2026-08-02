"""Integration reliability engine.

Provides durable retry, dead-letter queue management, and circuit-breaker
for national health system integrations.

ALL RULES:
- Exponential backoff with jitter for all retries.
- Messages exceeding MAX_ATTEMPTS are dead-lettered, never silently dropped.
- Circuit-breaker trips after FAILURE_THRESHOLD consecutive failures.
- Rate limiting is enforced per provider per second and per minute.
- NEVER log secret values, access tokens, or PII.
"""
from __future__ import annotations

import logging
import math
import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone

from apps.integrations.models import (
    IntegrationAttempt,
    IntegrationDeadLetter,
    IntegrationMessage,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 300.0  # 5 minutes
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
CIRCUIT_BREAKER_RECOVERY_SECONDS = 60


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitState:
    CLOSED = "CLOSED"      # Normal operation.
    OPEN = "OPEN"          # Trips after failures; blocks requests.
    HALF_OPEN = "HALF_OPEN"  # Test probe after recovery window.


@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker."""
    provider_type: str
    failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD
    recovery_seconds: int = CIRCUIT_BREAKER_RECOVERY_SECONDS
    state: str = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)

    def record_success(self) -> None:
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_at = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.warning(
                        "CircuitBreaker OPEN for provider '%s' after %d consecutive failures.",
                        self.provider_type, self.failure_count,
                    )
                self.state = CircuitState.OPEN

    def is_open(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return False
            if self.state == CircuitState.OPEN:
                if time.monotonic() - self.last_failure_at > self.recovery_seconds:
                    logger.info(
                        "CircuitBreaker entering HALF_OPEN for provider '%s'.",
                        self.provider_type,
                    )
                    self.state = CircuitState.HALF_OPEN
                    return False  # Allow one probe through.
                return True
            # HALF_OPEN: allow through.
            return False


_CIRCUIT_BREAKERS: dict[str, CircuitBreaker] = {}
_CB_LOCK = threading.Lock()


def get_circuit_breaker(provider_type: str) -> CircuitBreaker:
    with _CB_LOCK:
        if provider_type not in _CIRCUIT_BREAKERS:
            _CIRCUIT_BREAKERS[provider_type] = CircuitBreaker(provider_type=provider_type)
        return _CIRCUIT_BREAKERS[provider_type]


# ---------------------------------------------------------------------------
# Backoff calculation
# ---------------------------------------------------------------------------

def compute_backoff_seconds(attempt_number: int) -> float:
    """Exponential backoff with full jitter.

    Formula: min(MAX, BASE * 2^attempt) * uniform(0, 1)
    This produces a bounded, randomised delay that avoids thundering-herd.
    """
    cap = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * math.pow(2, attempt_number))
    return random.uniform(0, cap)  # noqa: S311 -- not cryptographic


# ---------------------------------------------------------------------------
# Dead-letter queue management
# ---------------------------------------------------------------------------

def dead_letter_message(message: IntegrationMessage, reason: str) -> IntegrationDeadLetter:
    """Move a message to the dead-letter queue.

    Should be called after MAX_ATTEMPTS is exhausted.
    """
    message.state = IntegrationMessage.MessageState.DEAD_LETTERED
    message.dead_lettered_at = timezone.now()
    message.save(update_fields=["state", "dead_lettered_at", "last_error"])

    dlq = IntegrationDeadLetter.objects.create(
        message=message,
        dead_lettered_at=timezone.now(),
        dead_letter_reason=reason,
    )
    logger.error(
        "IntegrationMessage dead-lettered: id=%s provider=%s type=%s reason=%s",
        message.id,
        message.provider.provider_type,
        message.message_type,
        reason[:200],  # Truncate; reason must not contain secrets.
    )
    return dlq


def record_attempt(
    *,
    message: IntegrationMessage,
    success: bool,
    http_status: int | None = None,
    response_time_ms: int | None = None,
    error_class: str = "",
    error_detail: str = "",
) -> IntegrationAttempt:
    """Record one delivery attempt and update the message state accordingly."""
    attempt = IntegrationAttempt.objects.create(
        message=message,
        success=success,
        http_status=http_status,
        response_time_ms=response_time_ms,
        error_class=error_class,
        error_detail=error_detail[:1000],  # Bounded; must not contain secrets.
    )

    message.attempt_count += 1
    cb = get_circuit_breaker(message.provider.provider_type)

    if success:
        message.state = IntegrationMessage.MessageState.DELIVERED
        message.delivered_at = timezone.now()
        cb.record_success()
    else:
        cb.record_failure()
        if message.attempt_count >= MAX_ATTEMPTS:
            dead_letter_message(message, error_detail or error_class or "Max attempts exceeded.")
        else:
            backoff = compute_backoff_seconds(message.attempt_count)
            message.next_retry_at = timezone.now() + timedelta(seconds=backoff)
            message.state = IntegrationMessage.MessageState.FAILED
            message.last_error = error_detail[:500]

    message.save()
    return attempt
