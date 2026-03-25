from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    protocol: str = "auto"
    disabled: bool = False


@dataclass(frozen=True)
class MCPConfig:
    servers: dict[str, MCPServerConfig]
    tooling: dict[str, dict[str, str]]


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_workspace_vars(value: str, root: Path) -> str:
    resolved = str(root)
    return (
        value.replace("${workspaceFolder}", resolved)
        .replace("${workspaceRoot}", resolved)
        .replace("{workspaceFolder}", resolved)
    )


def _expand_env_vars(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in {"workspaceFolder", "workspaceRoot"}:
            return match.group(0)
        return os.getenv(key, "")

    return _ENV_VAR_PATTERN.sub(replacer, value)


def _expand_template_vars(value: str, root: Path) -> str:
    return _expand_env_vars(_expand_workspace_vars(value, root))


def _locate_mcp_config_path(root: Path) -> Path | None:
    env_path = os.getenv("MCP_CONFIG_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return candidate.resolve()
    workspace_app_path = root / "app" / "mcp.json"
    if workspace_app_path.exists():
        return workspace_app_path
    app_dir = Path(__file__).resolve().parent
    app_path = app_dir / "mcp.json"
    if app_path.exists():
        return app_path
    return None


def load_mcp_config(workspace_root: str | Path | None) -> Optional[MCPConfig]:
    if not workspace_root:
        return None
    root = Path(workspace_root).resolve()
    config_path = _locate_mcp_config_path(root)
    if not config_path:
        return None
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    servers_raw = raw.get("mcpServers") or {}
    servers: dict[str, MCPServerConfig] = {}
    for name, cfg in servers_raw.items():
        if not isinstance(cfg, dict):
            continue
        env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
        expanded_env = {
            str(key): _expand_template_vars(str(value), root)
            for key, value in env.items()
            if value is not None
        }
        command = str(cfg.get("command") or "").strip()
        args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
        expanded_args = [
            _expand_template_vars(str(arg), root) for arg in args if arg is not None
        ]
        type_name = str(cfg.get("type") or "").strip().lower()
        url = str(cfg.get("url") or "").strip()
        headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
        expanded_headers = {
            str(key): _expand_template_vars(str(value), root)
            for key, value in headers.items()
            if value is not None
        }
        protocol = str(cfg.get("protocol") or "auto").strip().lower()
        disabled = bool(cfg.get("disabled"))

        if command:
            servers[name] = MCPServerConfig(
                name=name,
                transport="stdio",
                command=_expand_template_vars(command, root),
                args=expanded_args,
                env=expanded_env,
                protocol=protocol or "auto",
                disabled=disabled,
            )
            continue

        if url and type_name in {"http", "streamable-http", "streamable_http", "url"}:
            servers[name] = MCPServerConfig(
                name=name,
                transport="http",
                env=expanded_env,
                url=_expand_template_vars(url, root),
                headers=expanded_headers,
                disabled=disabled,
            )
            continue

        if not url:
            continue

        servers[name] = MCPServerConfig(
            name=name,
            transport="http",
            env=expanded_env,
            url=_expand_template_vars(url, root),
            headers=expanded_headers,
            disabled=disabled,
        )
    tooling = raw.get("tooling") if isinstance(raw.get("tooling"), dict) else {}
    tooling_map: dict[str, dict[str, str]] = {}
    for key, value in tooling.items():
        if isinstance(value, dict):
            tooling_map[key] = {
                str(tooling_key): _expand_template_vars(str(tooling_value), root)
                for tooling_key, tooling_value in value.items()
                if tooling_value is not None
            }
    return MCPConfig(servers=servers, tooling=tooling_map)


class MCPStdioSession:
    def __init__(self, server: MCPServerConfig) -> None:
        env = os.environ.copy()
        env.update(server.env)
        self.server = server
        self.protocol = self._detect_protocol(server)
        self.io_timeout_seconds = float(os.getenv("MCP_IO_TIMEOUT_SECONDS", "120"))
        if self._is_mcp_remote(server):
            self._cleanup_stale_mcp_remote_locks()
        self.process = subprocess.Popen(
            [server.command, *server.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=False,
        )

    @staticmethod
    def _detect_protocol(server: MCPServerConfig) -> str:
        configured = (server.protocol or "auto").lower()
        if configured in {"line", "line_json", "jsonl"}:
            return "line_json"
        if configured in {"content-length", "content_length", "headers"}:
            return "content_length"
        text = " ".join([server.command, *server.args]).lower()
        if "mcp-remote" in text:
            return "line_json"
        if "@modelcontextprotocol/server-filesystem" in text or "mcp-server-filesystem" in text:
            return "line_json"
        return "content_length"

    @staticmethod
    def _is_mcp_remote(server: MCPServerConfig) -> bool:
        text = " ".join([server.command, *server.args]).lower()
        return "mcp-remote" in text

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    @classmethod
    def _cleanup_stale_mcp_remote_locks(cls) -> None:
        auth_root = Path.home() / ".mcp-auth"
        if not auth_root.exists():
            return
        for version_dir in auth_root.glob("mcp-remote-*"):
            if not version_dir.is_dir():
                continue
            for lock_path in version_dir.glob("*_lock.json"):
                try:
                    payload = json.loads(lock_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                pid_value = payload.get("pid")
                try:
                    pid = int(str(pid_value))
                except Exception:
                    pid = -1
                if not cls._pid_exists(pid):
                    try:
                        lock_path.unlink()
                    except Exception:
                        continue

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()

    def _read_from_stdout(self, size: int, deadline: float) -> bytes:
        if not self.process.stdout:
            raise RuntimeError("MCP stdout not available")
        while True:
            if self.process.poll() is not None:
                raise RuntimeError("MCP server closed the connection")
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("MCP response timed out")
            ready, _, _ = select.select([self.process.stdout], [], [], min(remaining, 0.5))
            if not ready:
                continue
            chunk = os.read(self.process.stdout.fileno(), size)
            if not chunk:
                raise RuntimeError("MCP server closed the connection")
            return chunk

    def _write_message(self, payload: dict[str, Any]) -> None:
        if not self.process.stdin:
            raise RuntimeError("MCP stdin not available")
        if self.protocol == "line_json":
            body = (json.dumps(payload) + "\n").encode("utf-8")
            self.process.stdin.write(body)
        else:
            body = json.dumps(payload).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            self.process.stdin.write(header + body)
        self.process.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        deadline = time.time() + self.io_timeout_seconds
        if self.protocol == "line_json":
            line = b""
            while b"\n" not in line:
                line += self._read_from_stdout(1, deadline)
            data = json.loads(line.decode("utf-8", errors="replace").strip())
            return data

        header_bytes = b""
        while b"\r\n\r\n" not in header_bytes:
            header_bytes += self._read_from_stdout(1, deadline)
        header_text, remainder = header_bytes.split(b"\r\n\r\n", 1)
        headers = header_text.decode("utf-8", errors="replace").split("\r\n")
        content_length = 0
        for line in headers:
            if line.lower().startswith("content-length"):
                _, value = line.split(":", 1)
                content_length = int(value.strip())
                break
        body = remainder
        while len(body) < content_length:
            body += self._read_from_stdout(content_length - len(body), deadline)
        data = json.loads(body.decode("utf-8", errors="replace"))
        return data

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        self._write_message(payload)
        while True:
            response = self._read_message()
            if response.get("id") == request_id:
                return response

    def initialize(self) -> None:
        init_payload = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ai-multi-agent-assistant", "version": "1.0"},
        }
        self.request("initialize", init_payload)
        self._write_message({"jsonrpc": "2.0", "method": "initialized", "params": {}})


class MCPHttpSession:
    def __init__(self, server: MCPServerConfig) -> None:
        self.server = server
        self.url = str(server.url or "").strip()

        if not self.url:
            raise RuntimeError("MCP HTTP server URL is missing.")

        self.timeout_seconds = float(os.getenv("MCP_HTTP_TIMEOUT_SECONDS", "30"))

        self.headers = {
            str(key): str(value)
            for key, value in (server.headers or {}).items()
            if str(value).strip()
        }

        lowered = {key.lower() for key in self.headers}

        if "content-type" not in lowered:
            self.headers["Content-Type"] = "application/json"

        if "accept" not in lowered:
            self.headers["Accept"] = "application/json, text/event-stream"

        if "mcp-protocol-version" not in lowered:
            self.headers["MCP-Protocol-Version"] = "2024-11-05"

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.url, headers=self.headers, json=payload)
            response.raise_for_status()

            content_type = str(response.headers.get("content-type") or "").lower()
            if "text/event-stream" in content_type:
                data = self._parse_sse_payload(response.text)
            else:
                data = response.json()

        if not isinstance(data, dict):
            raise RuntimeError("MCP HTTP response was not a JSON object.")

        return data

    @staticmethod
    def _parse_sse_payload(text: str) -> dict[str, Any]:
        chunks: list[str] = []
        lines = text.splitlines()

        for line in lines:
            if not line.startswith("data:"):
                continue

            chunk = line[5:].lstrip()
            if not chunk or chunk == "[DONE]":
                continue

            chunks.append(chunk)

        if not chunks:
            raise RuntimeError("MCP HTTP SSE response had no data payload.")

        parsed_messages: list[dict[str, Any]] = []
        for chunk in chunks:
            try:
                candidate = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                parsed_messages.append(candidate)

        if not parsed_messages:
            raise RuntimeError("MCP HTTP SSE response did not contain valid JSON objects.")

        return parsed_messages[-1]


class MCPClient:
    def __init__(self, config: MCPConfig) -> None:
        self.config = config

    def _get_server(self, server_name: str) -> MCPServerConfig:
        server = self.config.servers.get(server_name)
        if not server:
            raise RuntimeError(f"MCP server '{server_name}' not configured")
        if server.disabled:
            raise RuntimeError(f"MCP server '{server_name}' is disabled")
        return server

    @staticmethod
    def _unwrap_result(response: dict[str, Any]) -> dict[str, Any]:
        if isinstance(response.get("error"), dict):
            error = response["error"]
            message = str(error.get("message") or "Unknown MCP error").strip()
            code = error.get("code")
            if code is None:
                raise RuntimeError(message)
            raise RuntimeError(f"{message} (code={code})")
        result = response.get("result")
        if isinstance(result, dict):
            return result
        return {}

    def list_tools(self, server_name: str) -> dict[str, Any]:
        server = self._get_server(server_name)
        if server.transport == "http":
            session = MCPHttpSession(server)
            response = session.request("tools/list", {})
            return self._unwrap_result(response)

        session = MCPStdioSession(server)
        try:
            session.initialize()
            response = session.request("tools/list", {})
            return self._unwrap_result(response)
        finally:
            session.close()

    def call_tool(self, server_name: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = self._get_server(server_name)
        if server.transport == "http":
            session = MCPHttpSession(server)
            response = session.request("tools/call", {"name": tool, "arguments": arguments})
            return self._unwrap_result(response)

        session = MCPStdioSession(server)
        try:
            session.initialize()
            response = session.request("tools/call", {"name": tool, "arguments": arguments})
            return self._unwrap_result(response)
        finally:
            session.close()
