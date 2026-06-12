from __future__ import annotations

import re
import json
import ssl
import subprocess
import time
from functools import lru_cache
from http.client import HTTPSConnection
from urllib.parse import urlparse
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


class PublicTunnelService:
    tunnel_url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.process: subprocess.Popen | None = None
        self.active_tunnel_url: str | None = None
        self.stderr_log_path = self.settings.logs_dir / "cloudflared.err.log"
        self.stdout_log_path = self.settings.logs_dir / "cloudflared.out.log"

    def ensure_started_for_local_development(
        self,
        *,
        wait_until_reachable: bool = False,
        force_refresh: bool = False,
    ) -> str | None:
        if self.settings.environment != "local" or not self.settings.auto_public_tunnel_enabled:
            return self.settings.normalized_public_base_url

        if self.settings.normalized_public_base_url and not self.settings.uses_cloudflare_quick_tunnel:
            return self.settings.normalized_public_base_url

        if self._has_active_quick_tunnel() and not force_refresh:
            return self.settings.normalized_public_base_url

        if self.settings.normalized_public_base_url and not force_refresh and self.is_public_base_url_reachable():
            return self.settings.normalized_public_base_url

        tunnel_url = self._start_cloudflared_quick_tunnel(wait_until_reachable=wait_until_reachable)
        self.settings.public_base_url = tunnel_url
        self.active_tunnel_url = tunnel_url
        self._persist_public_base_url(tunnel_url)
        logger.info("Cloudflare quick tunnel started and PUBLIC_BASE_URL set for this backend process: %s", tunnel_url)
        return tunnel_url

    def ensure_public_url_ready_for_call(self) -> None:
        if not self.settings.has_public_base_url:
            if self.settings.environment == "local" and self.settings.auto_public_tunnel_enabled:
                self.ensure_started_for_local_development(wait_until_reachable=True, force_refresh=True)
            else:
                raise AppError(
                    status_code=400,
                    code="public_base_url_missing",
                    message="PUBLIC_BASE_URL must be configured so Twilio can reach the backend status webhooks and media stream bridge.",
                )

        if self.is_public_base_url_reachable() or self.is_quick_tunnel_ready_for_external_webhooks():
            return

        if self.settings.environment == "local" and self.settings.auto_public_tunnel_enabled and self.settings.uses_cloudflare_quick_tunnel:
            try:
                self.ensure_started_for_local_development(wait_until_reachable=True, force_refresh=True)
            except AppError as exc:
                if exc.code != "public_base_url_unreachable" or not self.settings.normalized_public_base_url:
                    raise
                logger.warning(
                    "Cloudflare quick tunnel URL was detected but was slow to become reachable; retrying readiness probe."
                )
                if self._wait_until_public_base_url_reachable(self.settings.public_tunnel_start_timeout_seconds):
                    return
                raise

            if self.is_public_base_url_reachable() or self.is_quick_tunnel_ready_for_external_webhooks():
                return

        if not self.is_public_base_url_reachable() and not self.is_quick_tunnel_ready_for_external_webhooks():
            raise AppError(
                status_code=503,
                code="public_base_url_unreachable",
                message=(
                    "The public backend URL is not reachable. Start the Cloudflare tunnel or configure a valid "
                    "PUBLIC_BASE_URL before starting a Twilio call."
                ),
                details={"public_base_url": self.settings.normalized_public_base_url},
            )

    def is_public_base_url_reachable(self) -> bool:
        base_url = self.settings.normalized_public_base_url
        if not base_url:
            return False
        try:
            # Use the lightweight root endpoint here. /api/health checks external
            # dependencies such as Firestore, so a database outage can falsely
            # make an otherwise valid Twilio tunnel look unreachable.
            request = Request(f"{base_url}/", method="GET")
            with urlopen(request, timeout=self.settings.public_tunnel_health_timeout_seconds) as response:
                return 200 <= response.status < 300
        except (OSError, URLError, TimeoutError, ValueError):
            return False

    def is_quick_tunnel_ready_for_external_webhooks(self) -> bool:
        base_url = self.settings.normalized_public_base_url
        if not base_url or not self.settings.uses_cloudflare_quick_tunnel:
            return False
        return (
            self._is_managed_tunnel_running()
            and self._has_registered_tunnel_connection()
            and self._is_local_origin_reachable()
            and self._is_public_dns_resolvable(base_url)
        )

    def _wait_until_public_base_url_reachable(self, timeout_seconds: int | float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_public_base_url_reachable() or self.is_quick_tunnel_ready_for_external_webhooks():
                return True
            time.sleep(0.5)
        return self.is_public_base_url_reachable() or self.is_quick_tunnel_ready_for_external_webhooks()

    def _start_cloudflared_quick_tunnel(self, *, wait_until_reachable: bool) -> str:
        executable = self.settings.cloudflared_executable_file
        if not executable.exists():
            raise AppError(
                status_code=503,
                code="cloudflared_missing",
                message=(
                    "Cloudflared is required for automatic local Twilio tunnels but was not found. "
                    f"Expected it at {executable}."
                ),
            )

        self._stop_managed_process()
        self._stop_existing_quick_tunnels()
        self.stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_log_path.write_text("", encoding="utf-8")
        self.stdout_log_path.write_text("", encoding="utf-8")
        stderr_handle = self.stderr_log_path.open("a", encoding="utf-8")
        stdout_handle = self.stdout_log_path.open("a", encoding="utf-8")
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self.process = subprocess.Popen(
            [
                str(executable),
                "tunnel",
                "--protocol",
                self.settings.cloudflared_protocol.strip().lower(),
                "--url",
                f"http://127.0.0.1:{self.settings.app_port}",
            ],
            cwd=str(self.settings.project_root),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            creationflags=creation_flags,
        )

        deadline = time.monotonic() + self.settings.public_tunnel_start_timeout_seconds
        tunnel_url: str | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AppError(
                    status_code=503,
                    code="cloudflared_start_failed",
                    message="Cloudflared exited before creating a public tunnel.",
                    details={"log": self._read_recent_tunnel_log()},
                )
            if tunnel_url is None:
                tunnel_url = self._extract_tunnel_url_from_logs()
                if tunnel_url:
                    self.settings.public_base_url = tunnel_url
                    self.active_tunnel_url = tunnel_url
                    self._persist_public_base_url(tunnel_url)
                    if not wait_until_reachable:
                        return tunnel_url
                    logger.info("Cloudflare quick tunnel URL detected, waiting for it to become reachable: %s", tunnel_url)
            if tunnel_url and wait_until_reachable and (
                self.is_public_base_url_reachable() or self.is_quick_tunnel_ready_for_external_webhooks()
            ):
                return tunnel_url
            time.sleep(0.5)

        if tunnel_url is None:
            raise AppError(
                status_code=503,
                code="cloudflared_start_timeout",
                message="Cloudflared did not provide a public tunnel URL in time.",
                details={"log": self._read_recent_tunnel_log()},
            )

        raise AppError(
            status_code=503,
            code="public_base_url_unreachable",
            message="Cloudflared started a tunnel but the public URL was not reachable in time.",
            details={"public_base_url": tunnel_url, "log": self._read_recent_tunnel_log()},
        )

    def _persist_public_base_url(self, tunnel_url: str) -> None:
        env_path = self.settings.backend_dir / ".env"
        if not env_path.exists():
            return
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
            updated = False
            for index, line in enumerate(lines):
                if line.startswith("PUBLIC_BASE_URL="):
                    lines[index] = f"PUBLIC_BASE_URL={tunnel_url}"
                    updated = True
                    break
            if not updated:
                lines.append(f"PUBLIC_BASE_URL={tunnel_url}")
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("Unable to persist PUBLIC_BASE_URL to backend/.env: %s", exc)

    def _extract_tunnel_url_from_logs(self) -> str | None:
        log_text = self._read_recent_tunnel_log()
        match = self.tunnel_url_pattern.search(log_text)
        return match.group(0) if match else None

    def _read_recent_tunnel_log(self) -> str:
        chunks = []
        for path in (self.stderr_log_path, self.stdout_log_path):
            if path.exists():
                chunks.append(path.read_text(encoding="utf-8", errors="ignore")[-5000:])
        return "\n".join(chunks)

    def _has_registered_tunnel_connection(self) -> bool:
        log_text = self._read_recent_tunnel_log().lower()
        return "registered tunnel connection" in log_text

    def _is_managed_tunnel_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def _is_local_origin_reachable(self) -> bool:
        try:
            request = Request(f"http://127.0.0.1:{self.settings.app_port}/", method="GET")
            with urlopen(request, timeout=self.settings.public_tunnel_health_timeout_seconds) as response:
                return 200 <= response.status < 300
        except (OSError, URLError, TimeoutError, ValueError):
            return False

    def _is_public_dns_resolvable(self, base_url: str) -> bool:
        host = urlparse(base_url).hostname
        if not host:
            return False
        connection: HTTPSConnection | None = None
        try:
            connection = HTTPSConnection(
                "cloudflare-dns.com",
                timeout=self.settings.public_tunnel_health_timeout_seconds,
                context=self._dns_probe_ssl_context(),
            )
            connection.request(
                "GET",
                f"/dns-query?name={host}&type=A",
                headers={"accept": "application/dns-json"},
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                return False
            payload = json.loads(response.read(4096).decode("utf-8", errors="ignore"))
            answers = payload.get("Answer") or []
            return any(str(answer.get("name", "")).rstrip(".").lower() == host.lower() for answer in answers)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return False
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _dns_probe_ssl_context() -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl._create_unverified_context()

    def _stop_managed_process(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.active_tunnel_url = None

    def _stop_existing_quick_tunnels(self) -> None:
        executable = str(self.settings.cloudflared_executable_file).lower()
        try:
            import psutil
        except Exception as exc:
            logger.warning("Unable to inspect existing cloudflared processes: %s", exc)
            return

        for process in psutil.process_iter(["pid", "exe", "cmdline"]):
            try:
                exe = str(process.info.get("exe") or "").lower()
                command = " ".join(process.info.get("cmdline") or []).lower()
                if executable not in exe and "cloudflared" not in command:
                    continue
                if " tunnel " not in f" {command} " or "trycloudflare" in command:
                    continue
                if f"127.0.0.1:{self.settings.app_port}" not in command:
                    continue
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def _has_active_quick_tunnel(self) -> bool:
        return bool(
            self.settings.environment == "local"
            and self.settings.auto_public_tunnel_enabled
            and self.settings.uses_cloudflare_quick_tunnel
            and self.process
            and self.process.poll() is None
            and self.active_tunnel_url
        )

    async def stop(self) -> None:
        self._stop_managed_process()


@lru_cache
def get_public_tunnel_service() -> PublicTunnelService:
    return PublicTunnelService(get_settings())
