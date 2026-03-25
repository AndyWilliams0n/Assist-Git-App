from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import threading

START_TIME = datetime.now(timezone.utc)


@dataclass
class AgentDefinition:
    id: str
    name: str
    provider: str | None
    model: str | None
    group: str
    role: str
    kind: str
    enabled: bool = True
    dependencies: list[str] = field(default_factory=list)
    source: str | None = None
    description: str | None = None
    capabilities: list[str] = field(default_factory=list)


@dataclass
class AgentRuntime:
    last_active_at: datetime | None = None
    last_error: str | None = None
    in_flight: int = 0
    total_calls: int = 0


_registry: dict[str, AgentDefinition] = {}
_runtime: dict[str, AgentRuntime] = {}
_lock = threading.Lock()

AgentEventListener = Callable[[str, str, str | None, str | None], None]
_listeners: list[AgentEventListener] = []


def register_agent_listener(listener: AgentEventListener) -> None:
    with _lock:
        _listeners.append(listener)


def _fire_event(event: str, agent_id: str, error: str | None = None) -> None:
    with _lock:
        agent_name = _registry[agent_id].name if agent_id in _registry else None
        listeners_snapshot = list(_listeners)

    for listener in listeners_snapshot:
        try:
            listener(event, agent_id, agent_name, error)
        except Exception:
            pass


def _slugify(value: str) -> str:
    return "-".join(value.lower().strip().split())


def make_agent_id(group: str, name: str) -> str:
    return f"{_slugify(group)}:{_slugify(name)}"


def register_agent(defn: AgentDefinition) -> None:
    with _lock:
        _registry[defn.id] = defn
        _runtime.setdefault(defn.id, AgentRuntime())


def mark_agent_start(agent_id: str) -> None:
    with _lock:
        runtime = _runtime.setdefault(agent_id, AgentRuntime())
        runtime.in_flight += 1
        runtime.total_calls += 1
        runtime.last_active_at = datetime.now(timezone.utc)

    _fire_event("start", agent_id)


def mark_agent_end(agent_id: str, error: str | None = None) -> None:
    with _lock:
        runtime = _runtime.setdefault(agent_id, AgentRuntime())
        runtime.in_flight = max(0, runtime.in_flight - 1)
        runtime.last_active_at = datetime.now(timezone.utc)

        if error:
            runtime.last_error = error

    _fire_event("end", agent_id, error)


def _format_uptime(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


def build_agent_snapshot(provider_health: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    uptime_seconds = (now - START_TIME).total_seconds()
    if provider_health is None:
        provider_health = {}

    with _lock:
        definitions = list(_registry.values())
        runtime = {key: value for key, value in _runtime.items()}

    def provider_status(provider: str | None) -> dict[str, Any]:
        if not provider:
            return {"health": "unknown"}
        info = provider_health.get(provider, {}) if isinstance(provider_health, dict) else {}
        reachable = info.get("reachable")
        configured = info.get("configured")
        if configured is False:
            health = "unconfigured"
        elif reachable is False:
            health = "degraded"
        elif reachable is True:
            health = "ok"
        else:
            health = "unknown"
        return {
            "health": health,
            "model": info.get("model"),
            "provider_status": info,
        }

    agents: list[dict[str, Any]] = []
    for definition in definitions:
        runtime_info = runtime.get(definition.id, AgentRuntime())
        provider_info = provider_status(definition.provider)
        agents.append(
            {
                "id": definition.id,
                "name": definition.name,
                "provider": definition.provider,
                "model": definition.model or provider_info.get("model"),
                "group": definition.group,
                "role": definition.role,
                "kind": definition.kind,
                "enabled": definition.enabled,
                "dependencies": definition.dependencies,
                "source": definition.source,
                "description": definition.description,
                "capabilities": definition.capabilities,
                "is_active": runtime_info.in_flight > 0,
                "in_flight": runtime_info.in_flight,
                "last_active_at": runtime_info.last_active_at.isoformat() if runtime_info.last_active_at else None,
                "last_error": runtime_info.last_error,
                "total_calls": runtime_info.total_calls,
                "health": provider_info.get("health"),
                "provider_status": provider_info.get("provider_status"),
                "uptime_seconds": uptime_seconds,
                "status": "running" if runtime_info.in_flight > 0 else "idle",
            }
        )

    return {
        "updated_at": now.isoformat(),
        "app_uptime_seconds": uptime_seconds,
        "app_uptime": _format_uptime(uptime_seconds),
        "agents": sorted(agents, key=lambda item: (item["group"], item["name"])),
    }
