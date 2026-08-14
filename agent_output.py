"""Compact agent payloads and deterministic terminal-output deltas."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol
import zlib


CURSOR_VERSION = 1
CURSOR_TAIL_BYTES = 4096
MAX_CURSOR_TOKEN_BYTES = 32 * 1024
MAX_CURSOR_STATE_BYTES = 16 * 1024
MIN_PARTIAL_OVERLAP_BYTES = 64


class AgentSummary(Protocol):
    host: str
    name: str
    pane_id: str
    workspace_id: str
    workspace_label: str
    status: str
    local: bool


class InvalidOutputCursor(ValueError):
    """Raised when an output cursor cannot be decoded safely."""


@dataclass(frozen=True)
class _CursorState:
    stream: str
    snapshot_size: int
    snapshot_hash: str
    tail: bytes


@dataclass(frozen=True)
class OutputDelta:
    """One bounded output result plus the cursor for the full new snapshot."""

    output: str
    truncated: bool
    cursor: str
    cursor_status: str
    delta: bool


def agent_address(agent: AgentSummary) -> str:
    """Return the stable human-readable address for one observed agent."""

    host = "local" if agent.local else agent.host
    target = agent.name or agent.pane_id
    return f"{host}/{target}"


def compact_agent_payload(agent: AgentSummary) -> dict[str, str]:
    """Return only fields needed to select and inspect a current agent."""

    return {
        "address": agent_address(agent),
        "status": agent.status,
        "workspace": agent.workspace_label or agent.workspace_id,
    }


def output_stream_id(identity: str) -> str:
    """Keep raw session metadata out of portable output cursors."""

    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _urlsafe_decode(value: str) -> bytes:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise InvalidOutputCursor("The output cursor is invalid.") from None
    if not encoded or len(encoded) > MAX_CURSOR_TOKEN_BYTES:
        raise InvalidOutputCursor("The output cursor is invalid.")
    try:
        return base64.b64decode(
            encoded + (b"=" * (-len(encoded) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except binascii.Error:
        raise InvalidOutputCursor("The output cursor is invalid.") from None


def _decompress_cursor(value: bytes) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(value, MAX_CURSOR_STATE_BYTES + 1)
        if len(decoded) > MAX_CURSOR_STATE_BYTES:
            raise InvalidOutputCursor("The output cursor is invalid.")
        decoded += decompressor.flush(MAX_CURSOR_STATE_BYTES + 1 - len(decoded))
    except (ValueError, zlib.error):
        raise InvalidOutputCursor("The output cursor is invalid.") from None
    if (
        len(decoded) > MAX_CURSOR_STATE_BYTES
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        raise InvalidOutputCursor("The output cursor is invalid.")
    return decoded


def _decode_cursor(cursor: str) -> _CursorState:
    decoded = _decompress_cursor(_urlsafe_decode(cursor))
    try:
        payload = json.loads(decoded)
        version = payload["v"]
        stream = payload["s"]
        snapshot_size = payload["n"]
        snapshot_hash = payload["h"]
        tail = base64.b64decode(payload["t"], validate=True)
        tail_hash = payload["q"]
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        raise InvalidOutputCursor("The output cursor is invalid.") from None
    hashes = (stream, snapshot_hash, tail_hash)
    if (
        not isinstance(payload, dict)
        or version != CURSOR_VERSION
        or not isinstance(snapshot_size, int)
        or isinstance(snapshot_size, bool)
        or snapshot_size < 0
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in hashes
        )
        or len(tail) > CURSOR_TAIL_BYTES
        or len(tail) > snapshot_size
        or _hash(tail) != tail_hash
    ):
        raise InvalidOutputCursor("The output cursor is invalid.")
    return _CursorState(stream, snapshot_size, snapshot_hash, tail)


def _encode_cursor(snapshot: bytes, stream: str) -> str:
    tail = snapshot[-CURSOR_TAIL_BYTES:]
    payload = {
        "h": _hash(snapshot),
        "n": len(snapshot),
        "q": _hash(tail),
        "s": stream,
        "t": base64.b64encode(tail).decode("ascii"),
        "v": CURSOR_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    compressed = zlib.compress(encoded, level=9)
    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def _find_exact_snapshot_end(snapshot: bytes, state: _CursorState) -> int | None:
    """Find the rightmost byte where the complete prior snapshot ends."""

    if state.snapshot_size == 0:
        return 0
    if not state.tail:
        return None
    search_from = len(snapshot)
    while search_from >= 0:
        tail_start = snapshot.rfind(state.tail, 0, search_from)
        if tail_start < 0:
            return None
        end = tail_start + len(state.tail)
        start = end - state.snapshot_size
        if start >= 0 and _hash(snapshot[start:end]) == state.snapshot_hash:
            return end
        search_from = tail_start
    return None


def _tail_overlap_delta(snapshot: bytes, state: _CursorState) -> bytes | None:
    """Use a long, exact tail overlap only when a full hash is unavailable."""

    if len(state.tail) < MIN_PARTIAL_OVERLAP_BYTES:
        return None

    tail_start = snapshot.rfind(state.tail)
    if tail_start >= 0:
        end = tail_start + len(state.tail)
        # An unchanged tail at EOF with a changed full hash is evidence of a
        # rewrite earlier in the screen, not evidence of an empty delta.
        return snapshot[end:] or None

    maximum = min(len(state.tail), len(snapshot))
    for overlap_size in range(maximum, MIN_PARTIAL_OVERLAP_BYTES - 1, -1):
        if state.tail[-overlap_size:] == snapshot[:overlap_size]:
            delta = snapshot[overlap_size:]
            return delta or None
    return None


def _utf8_suffix(value: bytes, max_bytes: int) -> tuple[str, bool]:
    if len(value) <= max_bytes:
        return value.decode("utf-8"), False
    suffix = value[-max_bytes:]
    while suffix:
        try:
            return suffix.decode("utf-8"), True
        except UnicodeDecodeError as error:
            if error.start != 0:
                raise
            suffix = suffix[error.end:]
    return "", True


def compact_output(
    snapshot: str,
    *,
    stream: str,
    max_bytes: int,
    cursor: str | None = None,
) -> OutputDelta:
    """Return a bounded full snapshot or a conservative delta.

    A complete prior snapshot is recognized by its hash even if a rolling
    terminal window dropped older bytes. If that is impossible, a long exact
    tail overlap is accepted. Rewrites and lost overlap safely fall back to the
    current snapshot and mark the cursor expired.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")
    current = snapshot.encode("utf-8")
    next_cursor = _encode_cursor(current, stream)

    if cursor is None:
        candidate = current
        cursor_status = "initial"
        is_delta = False
    else:
        state = _decode_cursor(cursor)
        if state.stream != stream:
            candidate = current
            cursor_status = "expired"
            is_delta = False
        elif (
            state.snapshot_size == len(current)
            and state.snapshot_hash == _hash(current)
        ):
            candidate = b""
            cursor_status = "current"
            is_delta = True
        else:
            exact_end = _find_exact_snapshot_end(current, state)
            if exact_end is not None:
                candidate = current[exact_end:]
                cursor_status = "current"
                is_delta = True
            else:
                overlap_delta = _tail_overlap_delta(current, state)
                if overlap_delta is not None:
                    candidate = overlap_delta
                    cursor_status = "current"
                    is_delta = True
                else:
                    candidate = current
                    cursor_status = "expired"
                    is_delta = False

    output, truncated = _utf8_suffix(candidate, max_bytes)
    return OutputDelta(
        output=output,
        truncated=truncated,
        cursor=next_cursor,
        cursor_status=cursor_status,
        delta=is_delta,
    )
