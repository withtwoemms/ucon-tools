# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for `ucon.tools.mcp.system.audit`.

Invariants under test:
- `AuditRecord` JSON-line serialization round-trip.
- `StderrJsonSink` writes one record per line, flushed.
- `CollectingSink` captures records in order.
- All sinks satisfy the `AuditSink` Protocol at runtime.
- `EffectiveCapabilities.audit` is distinct from the operator-side
  `AuditSink`.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone

import pytest

from ucon.tools.mcp.system import (
    AuditRecord,
    AuditSink,
    CollectingSink,
    EffectiveCapabilities,
    StderrJsonSink,
)


# -----------------------------------------------------------------------------
# AuditRecord serialization
# -----------------------------------------------------------------------------

def _mk_record(
    event="activate",
    expires_at=None,
    lease_clamped_from=None,
) -> AuditRecord:
    return AuditRecord(
        event=event,
        tier="preview",
        bundle_name="core",
        bundle_version="1.0",
        bundle_provenance="builtin:core",
        activator="ops/test",
        timestamp=datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc),
        expires_at=expires_at,
        lease_clamped_from=lease_clamped_from,
    )


def test_audit_record_to_dict_iso_serializes_datetimes():
    rec = _mk_record(
        expires_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        lease_clamped_from=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    d = rec.to_dict()
    assert d["event"] == "activate"
    assert d["tier"] == "preview"
    assert d["bundle_name"] == "core"
    assert d["bundle_version"] == "1.0"
    assert d["bundle_provenance"] == "builtin:core"
    assert d["activator"] == "ops/test"
    assert d["timestamp"] == "2026-05-13T12:00:00+00:00"
    assert d["expires_at"] == "2026-05-14T00:00:00+00:00"
    assert d["lease_clamped_from"] == "2026-05-20T00:00:00+00:00"


def test_audit_record_to_dict_optional_fields_become_none():
    rec = _mk_record()
    d = rec.to_dict()
    assert d["expires_at"] is None
    assert d["lease_clamped_from"] is None


def test_audit_record_round_trip_preserves_all_fields():
    rec = _mk_record(
        event="clamp",
        expires_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        lease_clamped_from=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    restored = AuditRecord.from_dict(rec.to_dict())
    assert restored == rec


def test_audit_record_round_trip_with_none_optionals():
    rec = _mk_record()
    restored = AuditRecord.from_dict(rec.to_dict())
    assert restored == rec


def test_audit_record_is_frozen():
    rec = _mk_record()
    with pytest.raises(Exception):
        rec.event = "expire"  # type: ignore[misc]


# -----------------------------------------------------------------------------
# StderrJsonSink
# -----------------------------------------------------------------------------

def test_stderr_json_sink_writes_jsonl_to_provided_stream():
    stream = io.StringIO()
    sink = StderrJsonSink(stream=stream)
    rec = _mk_record()
    sink.emit(rec)
    line = stream.getvalue()
    assert line.endswith("\n")
    parsed = json.loads(line.rstrip("\n"))
    assert parsed == rec.to_dict()


def test_stderr_json_sink_one_record_per_line():
    stream = io.StringIO()
    sink = StderrJsonSink(stream=stream)
    sink.emit(_mk_record(event="activate"))
    sink.emit(_mk_record(event="deactivate"))
    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "activate"
    assert json.loads(lines[1])["event"] == "deactivate"


def test_stderr_json_sink_default_observes_monkeypatched_stderr(monkeypatch):
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake)
    sink = StderrJsonSink()  # constructed without explicit stream
    sink.emit(_mk_record())
    assert json.loads(fake.getvalue().rstrip("\n"))["event"] == "activate"


def test_stderr_json_sink_satisfies_protocol():
    assert isinstance(StderrJsonSink(stream=io.StringIO()), AuditSink)


# -----------------------------------------------------------------------------
# CollectingSink
# -----------------------------------------------------------------------------

def test_collecting_sink_captures_records_in_order():
    sink = CollectingSink()
    a = _mk_record(event="activate")
    b = _mk_record(event="deactivate")
    sink.emit(a)
    sink.emit(b)
    assert sink.records == [a, b]


def test_collecting_sink_satisfies_protocol():
    assert isinstance(CollectingSink(), AuditSink)


# -----------------------------------------------------------------------------
# Seam: AuditSink vs EffectiveCapabilities.audit
# -----------------------------------------------------------------------------

def test_audit_sink_distinct_from_eff_audit():
    """The operator-side `AuditSink` and the per-request
    `EffectiveCapabilities.audit` provenance tuple are distinct concepts.

    `AuditSink.emit` takes `AuditRecord` lifecycle events;
    `EffectiveCapabilities.audit` is a `tuple[Any, ...]` of provenance
    entries attached to a composed value.
    """
    sink = CollectingSink()
    eff = EffectiveCapabilities(
        unit_system=object(),
        tools=frozenset(),
        formula_tools=frozenset(),
        audit=("core@1.0",),
    )
    # Different shapes.
    assert isinstance(eff.audit, tuple)
    assert not isinstance(eff.audit, AuditSink)
    # The sink does not accept provenance strings.
    assert not hasattr(eff.audit, "emit")
    # The sink's records list is empty until lifecycle events are emitted.
    assert sink.records == []
