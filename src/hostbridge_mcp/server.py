"""Authenticated remote operations MCP server (MCP Python SDK v2.x).

Tools run with the effective permissions of this process. Protect the HTTPS
endpoint with network controls in addition to the Bearer token.
"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import os
import signal
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.routing import Mount

TOKEN = os.environ["MCP_ACCESS_TOKEN"]
if len(TOKEN) < 32:
    raise RuntimeError("MCP_ACCESS_TOKEN must be at least 32 characters")

BASE = Path(os.getenv("MCP_FILE_ROOT", "/srv/agent-workspace")).resolve(strict=True)
COMMANDS_ENABLED = os.getenv("MCP_ENABLE_COMMANDS", "false").lower() == "true"
MAX_OUTPUT = int(os.getenv("MCP_MAX_OUTPUT_BYTES", "65536"))
MAX_FILE = int(os.getenv("MCP_MAX_FILE_BYTES", "1048576"))
MAX_TIMEOUT = int(os.getenv("MCP_MAX_TIMEOUT", "120"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hostbridge-mcp")
mcp = MCPServer("HostBridge MCP")


def safe_path(name: str) -> Path:
    candidate = Path(name)
    path = (candidate if candidate.is_absolute() else BASE / candidate).resolve()
    if not path.is_relative_to(BASE):
        raise ValueError("Path outside MCP_FILE_ROOT")
    return path


def user_result(ok: bool, **kwargs) -> dict:
    return {"ok": ok, **kwargs}


@mcp.tool()
def execute_command(command: str, cwd: str = ".", timeout: int = 30) -> dict:
    """Execute a shell command in the server workspace as the MCP service user.

    Supports pipes and Docker commands if the service user has permission.
    Never invokes sudo automatically. Only use on trusted, authorized servers.
    """
    if not COMMANDS_ENABLED:
        return user_result(False, error="Command execution disabled by administrator")
    if not command.strip():
        return user_result(False, error="Empty command")
    try:
        workdir = safe_path(cwd)
        if not workdir.is_dir():
            raise ValueError("cwd is not a directory")
        timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        log.info("execute cwd=%s command=%s", workdir, command[:2000])
        # Temporary files bound memory even for commands producing huge outputs.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            import subprocess
            proc = subprocess.Popen(
                ["/bin/bash", "-lc", command], cwd=str(workdir),
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                start_new_session=True,
                env={**os.environ, "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"},
            )
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            stdout.seek(0)
            stderr.seek(0)
            out = stdout.read(MAX_OUTPUT + 1)
            err = stderr.read(MAX_OUTPUT + 1)
        log.info("execute finished rc=%s timed_out=%s", proc.returncode, timed_out)
        return user_result(
            not timed_out and proc.returncode == 0,
            exit_code=proc.returncode, timed_out=timed_out,
            stdout=out[:MAX_OUTPUT].decode("utf-8", "replace"),
            stderr=err[:MAX_OUTPUT].decode("utf-8", "replace"),
            stdout_truncated=len(out) > MAX_OUTPUT,
            stderr_truncated=len(err) > MAX_OUTPUT,
        )
    except Exception as exc:
        log.exception("execute_command failed")
        return user_result(False, error=f"{type(exc).__name__}: {exc}")


@mcp.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file inside MCP_FILE_ROOT (up to configured size)."""
    try:
        target = safe_path(path)
        if not target.is_file():
            raise ValueError("Not a regular file")
        if target.stat().st_size > MAX_FILE:
            raise ValueError("File exceeds MCP_MAX_FILE_BYTES")
        content = target.read_text(encoding="utf-8")
        return user_result(True, path=str(target), content=content)
    except Exception as exc:
        return user_result(False, error=str(exc))


@mcp.tool()
def write_file(path: str, content: str, overwrite: bool = False) -> dict:
    """Atomically write UTF-8 text inside MCP_FILE_ROOT; overwrite must be explicit."""
    temp_name = None
    try:
        target = safe_path(path)
        if not target.parent.is_dir():
            raise ValueError("Parent directory does not exist")
        if target.exists() and (not overwrite or not target.is_file()):
            raise ValueError("Target exists or is not a regular file; set overwrite=true")
        payload = content.encode("utf-8")
        if len(payload) > MAX_FILE:
            raise ValueError("Content exceeds MCP_MAX_FILE_BYTES")
        if target.exists():
            mode = stat.S_IMODE(target.stat().st_mode)
        else:
            mode = 0o600
        fd, temp_name = tempfile.mkstemp(prefix=".mcp-", dir=target.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        if not overwrite and target.exists():
            raise ValueError("Target now exists")
        os.replace(temp_name, target)
        temp_name = None
        log.info("write path=%s bytes=%d", target, len(payload))
        return user_result(True, path=str(target), bytes_written=len(payload))
    except Exception as exc:
        return user_result(False, error=str(exc))
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


@mcp.tool()
def list_directory(path: str = ".") -> dict:
    """List entries in a directory inside MCP_FILE_ROOT."""
    try:
        directory = safe_path(path)
        if not directory.is_dir():
            raise ValueError("Not a directory")
        items = []
        for item in sorted(directory.iterdir(), key=lambda p: p.name)[:500]:
            details = item.lstat()
            items.append({"name": item.name, "directory": item.is_dir(),
                          "symlink": item.is_symlink(), "size": details.st_size})
        return user_result(True, path=str(directory), entries=items,
                           limited=len(items) == 500)
    except Exception as exc:
        return user_result(False, error=str(exc))


@mcp.tool()
def file_info(path: str) -> dict:
    """Return basic filesystem information for a path inside MCP_FILE_ROOT."""
    try:
        target = safe_path(path)
        st = target.stat()
        return user_result(True, path=str(target), is_file=target.is_file(),
                           is_dir=target.is_dir(), size=st.st_size,
                           mode=oct(stat.S_IMODE(st.st_mode)),
                           modified=datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat())
    except Exception as exc:
        return user_result(False, error=str(exc))


@mcp.tool()
def create_directory(path: str) -> dict:
    """Create a directory and missing parents inside MCP_FILE_ROOT."""
    try:
        target = safe_path(path)
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        log.info("mkdir path=%s", target)
        return user_result(True, path=str(target))
    except Exception as exc:
        return user_result(False, error=str(exc))


@mcp.tool()
def delete_file(path: str) -> dict:
    """Delete one regular file inside MCP_FILE_ROOT; will not delete directories."""
    try:
        target = safe_path(path)
        if not target.is_file() or target.is_symlink():
            raise ValueError("Only regular, non-symlink files can be deleted")
        target.unlink()
        log.info("delete path=%s", target)
        return user_result(True, path=str(target))
    except Exception as exc:
        return user_result(False, error=str(exc))


# SDK v2 requires transport settings here rather than in the constructor.
# Uvicorn owns the listening socket; the internal MCP app handles /mcp.
inner = mcp.streamable_http_app(
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
)

@asynccontextmanager
async def lifespan(_app):
    # Without this, requests fail: "Task group is not initialized".
    async with mcp.session_manager.run():
        yield

application = Starlette(routes=[Mount("/", app=inner)], lifespan=lifespan)

async def app(scope, receive, send):
    if scope["type"] == "http":
        # All MCP requests require authentication, including GET/DELETE.
        headers = dict(scope.get("headers", []))
        candidate = headers.get(b"authorization", b"")
        required = ("Bearer " + TOKEN).encode("utf-8")
        if not hmac.compare_digest(candidate, required):
            log.warning("unauthorized request path=%s", scope.get("path"))
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain"),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return
    await application(scope, receive, send)

