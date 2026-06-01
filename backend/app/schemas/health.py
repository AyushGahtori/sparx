from typing import Literal

from pydantic import BaseModel, Field


class DependencyHealth(BaseModel):
    status: Literal["connected", "not_configured", "unavailable"]
    message: str
    configured: bool


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    backend: Literal["healthy"] = "healthy"
    firebase: Literal["connected", "not_configured", "unavailable"]
    mongodb: Literal["connected", "not_configured", "unavailable"] = "not_configured"
    twilio: Literal["connected", "not_configured", "unavailable"]
    deepgram: Literal["connected", "not_configured", "unavailable"]
    gemma: Literal["connected", "not_configured", "unavailable"]
    timestamp: str
    uptime: str
    environment: str
    details: dict[str, DependencyHealth] = Field(default_factory=dict)


class QueueHealth(BaseModel):
    status: Literal["healthy", "degraded"]
    loop_running: bool
    active_items: int
    last_cycle_started_at: str | None = None
    last_cycle_completed_at: str | None = None
    recovered_items: int = 0
    last_error: str | None = None


class SystemHealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    backend: Literal["healthy", "degraded"]
    firebase: Literal["connected", "not_configured", "unavailable"]
    mongodb: Literal["connected", "not_configured", "unavailable"] = "not_configured"
    twilio: Literal["connected", "not_configured", "unavailable"]
    deepgram: Literal["connected", "not_configured", "unavailable"]
    gemma: Literal["connected", "not_configured", "unavailable"]
    campaign_queue: Literal["healthy", "degraded"]
    callback_queue: Literal["healthy", "degraded"]
    ai_queue: Literal["healthy", "degraded"]
    uptime: str
    timestamp: str
    environment: str
    memory_usage_mb: float
    cpu_usage_percent: float
    queues: dict[str, QueueHealth] = Field(default_factory=dict)
    details: dict[str, DependencyHealth] = Field(default_factory=dict)
