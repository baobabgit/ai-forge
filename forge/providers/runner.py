"""Shared asynchronous subprocess runner for provider CLIs."""

import asyncio
import os
import re
import signal
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import BinaryIO, TextIO, cast

SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SECRET_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|API[_-]?KEY)", re.IGNORECASE)
CHUNK_SIZE = 64 * 1024
TERMINATION_GRACE_SECONDS = 2.0
CREATE_NEW_PROCESS_GROUP = 0x00000200


class RunnerStatus(StrEnum):
    """Normalized subprocess execution status."""

    OK = "OK"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class RunnerResult:
    """Result returned by the subprocess runner.

    :param status: Normalized execution status.
    :param code: Process return code, if a process was started.
    :param stdout: Captured standard output.
    :param stderr: Captured standard error.
    :param duration_seconds: Wall-clock execution duration.
    :param transcript_path: Path to the raw transcript.
    """

    status: RunnerStatus
    code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    transcript_path: Path


def transcript_path(
    artifacts_root: Path,
    bl_id: str,
    sequence: int,
    role: str,
    provider: str,
) -> Path:
    """Build the deterministic transcript path.

    :param artifacts_root: Root artifact directory.
    :param bl_id: Backlog item identifier.
    :param sequence: Invocation sequence number within the BL.
    :param role: Role name.
    :param provider: Provider name.
    :returns: The transcript path.
    :raises ValueError: If a path segment is unsafe.
    """
    safe_bl_id = _safe_segment(bl_id, "bl_id")
    safe_role = _safe_segment(role, "role")
    safe_provider = _safe_segment(provider, "provider")
    if sequence < 1:
        raise ValueError("sequence must be >= 1")
    return artifacts_root / safe_bl_id / f"{sequence}-{safe_role}-{safe_provider}.txt"


async def run_cli(
    command: Sequence[str],
    *,
    cwd: Path,
    bl_id: str,
    role: str,
    provider: str,
    timeout_seconds: float,
    sequence: int = 1,
    artifacts_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RunnerResult:
    """Run a provider CLI with streaming capture and transcript archival.

    :param command: Executable and arguments.
    :param cwd: Enforced working directory.
    :param bl_id: Backlog item identifier.
    :param role: Role name.
    :param provider: Provider name.
    :param timeout_seconds: Timeout in seconds.
    :param sequence: Invocation sequence number.
    :param artifacts_root: Optional artifact root, defaults to ``cwd / "artifacts"``.
    :param env: Optional non-secret environment overrides.
    :returns: Normalized runner result.
    :raises ValueError: If the command, timeout, path segments, or environment are invalid.
    """
    if not command:
        raise ValueError("command must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    resolved_cwd = cwd.resolve(strict=True)
    if not resolved_cwd.is_dir():
        raise ValueError("cwd must be a directory")

    transcript = transcript_path(
        artifacts_root or resolved_cwd / "artifacts",
        bl_id,
        sequence,
        role,
        provider,
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    subprocess_env = build_subprocess_environment(env)
    started_at = _timestamp()
    start = perf_counter()

    with transcript.open("w", encoding="utf-8", newline="\n") as transcript_file:
        _write_header(transcript_file, command, resolved_cwd, started_at)
        try:
            process = await _create_process(command, resolved_cwd, subprocess_env)
        except OSError as exc:
            stderr = str(exc)
            _write_event(transcript_file, "runner", f"spawn failed: {stderr}")
            return RunnerResult(
                status=RunnerStatus.ERROR,
                code=None,
                stdout="",
                stderr=stderr,
                duration_seconds=perf_counter() - start,
                transcript_path=transcript,
            )

        if process.stdout is None or process.stderr is None:
            raise RuntimeError("subprocess pipes were not created")
        lock = asyncio.Lock()
        stdout_task = asyncio.create_task(
            _capture_stream(process.stdout, transcript_file, lock, "stdout")
        )
        stderr_task = asyncio.create_task(
            _capture_stream(process.stderr, transcript_file, lock, "stderr")
        )

        timed_out = False
        try:
            code = await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
            _write_event(transcript_file, "runner", "timeout reached; terminating process")
            await _terminate_process_group(process)
            code = await process.wait()
        finally:
            stdout_bytes, stderr_bytes = await asyncio.gather(stdout_task, stderr_task)

        duration = perf_counter() - start
        status = RunnerStatus.TIMEOUT if timed_out else _status_from_code(code)
        _write_event(transcript_file, "runner", f"completed status={status} code={code}")

    return RunnerResult(
        status=status,
        code=code,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        duration_seconds=duration,
        transcript_path=transcript,
    )


def build_subprocess_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a minimal environment without secret-like variables.

    :param overrides: Optional non-secret variables to add.
    :returns: Sanitized environment.
    :raises ValueError: If an override key looks secret-bearing.
    """
    allowed_keys = {
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed_keys and not SECRET_KEY_PATTERN.search(key)
    }
    if overrides is None:
        return environment
    for key, value in overrides.items():
        if SECRET_KEY_PATTERN.search(key):
            raise ValueError(f"refusing to pass secret-like environment key: {key}")
        environment[key] = value
    return environment


async def _create_process(
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
) -> asyncio.subprocess.Process:
    if os.name == "nt":
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NEW_PROCESS_GROUP,
        )
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


async def _capture_stream(
    stream: asyncio.StreamReader,
    transcript_file: TextIO,
    lock: asyncio.Lock,
    label: str,
) -> bytes:
    captured = bytearray()
    while True:
        chunk = await stream.read(CHUNK_SIZE)
        if not chunk:
            return bytes(captured)
        captured.extend(chunk)
        await _write_stream_chunk(transcript_file, lock, label, chunk)


async def _write_stream_chunk(
    transcript_file: TextIO,
    lock: asyncio.Lock,
    label: str,
    chunk: bytes,
) -> None:
    async with lock:
        _write_chunk(transcript_file.buffer, label.encode("utf-8"), chunk)
        transcript_file.flush()


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        await _terminate_windows_process_tree(process)
        return
    try:
        _kill_process_group_signal(process.pid, int(signal.SIGTERM))
        await asyncio.wait_for(process.wait(), timeout=TERMINATION_GRACE_SECONDS)
    except (ProcessLookupError, TimeoutError):
        if process.returncode is None:
            _kill_process_group_signal(process.pid, _sigkill())


async def _terminate_windows_process_tree(process: asyncio.subprocess.Process) -> None:
    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(taskkill.communicate(), timeout=TERMINATION_GRACE_SECONDS)
    except (OSError, TimeoutError):
        if process.returncode is None:
            process.kill()


def _status_from_code(code: int) -> RunnerStatus:
    return RunnerStatus.OK if code == 0 else RunnerStatus.ERROR


def _kill_process_group_signal(pid: int, sig: int) -> None:
    killpg = cast(Callable[[int, int], None], vars(os)["killpg"])
    killpg(pid, sig)


def _sigkill() -> int:
    return cast(int, vars(signal).get("SIGKILL", signal.SIGTERM))


def _safe_segment(value: str, field_name: str) -> str:
    if not SAFE_SEGMENT_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} contains unsafe characters")
    return value


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_header(
    transcript_file: TextIO, command: Sequence[str], cwd: Path, started_at: str
) -> None:
    transcript_file.write(f"[{started_at}] runner started\n")
    transcript_file.write(f"cwd={cwd}\n")
    transcript_file.write(f"command={' '.join(command)}\n")
    transcript_file.flush()


def _write_event(transcript_file: TextIO, label: str, message: str) -> None:
    transcript_file.write(f"[{_timestamp()}] {label}: {message}\n")
    transcript_file.flush()


def _write_chunk(transcript_buffer: BinaryIO, label: bytes, chunk: bytes) -> None:
    transcript_buffer.write(b"[" + _timestamp().encode("utf-8") + b"] " + label + b": ")
    transcript_buffer.write(chunk)
    if not chunk.endswith(b"\n"):
        transcript_buffer.write(b"\n")
