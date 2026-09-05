#!/usr/bin/env python3
"""Estimate recent Claude Code transcript cost and gate excessive burn rate."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_MEASUREMENT_INCOMPLETE = 3
EXIT_BURN_RATE_EXCEEDED = 10

_DEFAULT_CONFIG = Path.home() / ".claude" / "fleet-usage-guard.json"
_DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_MILLION = Decimal(1_000_000)
_MONEY_QUANTUM = Decimal("0.01")
_MODEL_SUFFIX_RE = re.compile(r"\[\d+[a-zA-Z]?\]$")


@dataclass(frozen=True)
class ModelPrice:
    """Anthropic API list prices in USD per million tokens."""

    model_prefix: str
    input_usd: Decimal
    output_usd: Decimal
    cache_read_multiplier: Decimal = Decimal("0.1")


# Longest prefixes are checked first. Prices are API list-price estimates, not billing rates.
_MODEL_PRICES = tuple(
    sorted(
        (
            ModelPrice("claude-fable-5-1", Decimal("10"), Decimal("50"), Decimal("0.025")),
            ModelPrice("claude-fable-5", Decimal("10"), Decimal("50")),
            ModelPrice("claude-opus-5", Decimal("15"), Decimal("75")),
            ModelPrice("claude-opus-4-8", Decimal("15"), Decimal("75")),
            ModelPrice("claude-opus-4-7", Decimal("15"), Decimal("75")),
            ModelPrice("claude-opus-4-6", Decimal("15"), Decimal("75")),
            ModelPrice("claude-sonnet-5", Decimal("3"), Decimal("15")),
            ModelPrice("claude-haiku-4-5", Decimal("1"), Decimal("5")),
        ),
        key=lambda price: len(price.model_prefix),
        reverse=True,
    )
)


@dataclass(frozen=True)
class GuardConfig:
    """User-owned guard settings."""

    window_minutes: int
    max_usd_per_hour: Decimal


@dataclass(frozen=True)
class UsageSample:
    """One unique API request reconstructed from a transcript entry."""

    timestamp: datetime
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_5m_tokens: int
    cache_creation_1h_tokens: int

    @property
    def signature(self) -> tuple[str, int, int, int, int, int]:
        """Fields that repeated JSONL rows must preserve."""
        return (
            self.model,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_creation_5m_tokens,
            self.cache_creation_1h_tokens,
        )

    @property
    def has_any_tokens(self) -> bool:
        return any(self.signature[1:])


@dataclass(frozen=True)
class Measurement:
    """Burn-rate decision plus audit information."""

    status: str
    window_minutes: int
    threshold_usd_per_hour: Decimal
    estimated_cost_usd: Decimal
    estimated_usd_per_hour: Decimal
    rows_with_usage: int
    unique_requests: int
    duplicate_rows: int
    skipped_rows: int
    unpriced_models: tuple[str, ...]
    invalid_recent_rows: int
    inconsistent_requests: int
    scan_errors: tuple[str, ...]


class ConfigError(ValueError):
    """The user-owned configuration is missing or invalid."""


class MeasurementError(RuntimeError):
    """The transcript source cannot be scanned."""


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _token_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _usage_sample(record: dict[str, Any], timestamp: datetime) -> UsageSample:
    message = record["message"]
    usage = message["usage"]
    if not isinstance(usage, dict):
        raise ValueError("message.usage must be an object")
    cache_creation = usage.get("cache_creation")
    if cache_creation is None:
        cache_creation = {}
    if not isinstance(cache_creation, dict):
        raise ValueError("cache_creation must be an object")

    creation_5m = _token_count(
        cache_creation.get("ephemeral_5m_input_tokens", 0),
        "ephemeral_5m_input_tokens",
    )
    creation_1h = _token_count(
        cache_creation.get("ephemeral_1h_input_tokens", 0),
        "ephemeral_1h_input_tokens",
    )
    creation_total = _token_count(
        usage.get("cache_creation_input_tokens", creation_5m + creation_1h),
        "cache_creation_input_tokens",
    )
    # Older transcript rows only carried the aggregate. Anthropic's historical default was 5m.
    if creation_total > creation_5m + creation_1h:
        creation_5m += creation_total - creation_5m - creation_1h

    model = message.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("message.model must be a non-empty string")
    return UsageSample(
        timestamp=timestamp,
        model=model,
        input_tokens=_token_count(usage["input_tokens"], "input_tokens"),
        output_tokens=_token_count(usage["output_tokens"], "output_tokens"),
        cache_read_tokens=_token_count(usage["cache_read_input_tokens"], "cache_read_input_tokens"),
        cache_creation_5m_tokens=creation_5m,
        cache_creation_1h_tokens=creation_1h,
    )


def _price_for_model(model: str) -> ModelPrice | None:
    normalized = _MODEL_SUFFIX_RE.sub("", model).strip()
    for price in _MODEL_PRICES:
        if normalized == price.model_prefix or normalized.startswith(price.model_prefix + "-"):
            return price
    return None


def _sample_cost(sample: UsageSample) -> Decimal | None:
    price = _price_for_model(sample.model)
    if price is None:
        if sample.model == "<synthetic>" and not sample.has_any_tokens:
            return Decimal(0)
        return None
    return (
        Decimal(sample.input_tokens) * price.input_usd
        + Decimal(sample.output_tokens) * price.output_usd
        + Decimal(sample.cache_read_tokens) * price.input_usd * price.cache_read_multiplier
        + Decimal(sample.cache_creation_5m_tokens) * price.input_usd * Decimal("1.25")
        + Decimal(sample.cache_creation_1h_tokens) * price.input_usd * Decimal("2")
    ) / _MILLION


def _is_usage_record(record: object) -> bool:
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return False
    message = record.get("message")
    return isinstance(message, dict) and "usage" in message


def evaluate_burn_rate(
    projects_dir: Path,
    *,
    now: datetime,
    window_minutes: int,
    threshold_usd_per_hour: Decimal,
) -> Measurement:
    """Scan transcripts, deduplicate API requests, and make the burn-rate decision."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    if threshold_usd_per_hour <= 0:
        raise ValueError("threshold_usd_per_hour must be positive")
    if not projects_dir.is_dir():
        raise MeasurementError(f"transcript directory not found: {projects_dir}")

    now = now.astimezone(UTC)
    window_start = now - timedelta(minutes=window_minutes)
    grouped: dict[tuple[str, str], tuple[UsageSample, int, bool]] = {}
    skipped_rows_count = 0
    invalid_recent_rows = 0
    scan_errors: list[str] = []

    for root, _dirs, files in os.walk(projects_dir, followlinks=True):
        for fname in files:
            if not fname.endswith(".jsonl"):
                continue
            transcript = Path(root) / fname
            try:
                transcript_mtime = datetime.fromtimestamp(transcript.stat().st_mtime, UTC)
            except OSError as exc:
                scan_errors.append(f"{transcript}: {exc}")
                continue
            may_contain_recent_usage = transcript_mtime >= window_start
            try:
                stream = transcript.open("r", encoding="utf-8", errors="replace")
            except OSError as exc:
                scan_errors.append(f"{transcript}: {exc}")
                continue
            with stream:
                for raw in stream:
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        skipped_rows_count += 1
                        if may_contain_recent_usage:
                            invalid_recent_rows += 1
                        continue
                    if not _is_usage_record(record):
                        continue
                    try:
                        timestamp = _parse_timestamp(record.get("timestamp"))
                    except (TypeError, ValueError):
                        skipped_rows_count += 1
                        if may_contain_recent_usage:
                            invalid_recent_rows += 1
                        continue

                    message = record["message"]
                    message_id = message.get("id")
                    request_id = record.get("requestId")
                    if (
                        not isinstance(message_id, str)
                        or not message_id
                        or not isinstance(request_id, str)
                        or not request_id
                    ):
                        if window_start <= timestamp <= now:
                            invalid_recent_rows += 1
                        continue
                    try:
                        sample = _usage_sample(record, timestamp)
                    except (KeyError, TypeError, ValueError):
                        if window_start <= timestamp <= now:
                            invalid_recent_rows += 1
                        continue

                    key = (message_id, request_id)
                    current = grouped.get(key)
                    if current is None:
                        grouped[key] = (sample, 1, False)
                        continue
                    earliest, row_count, inconsistent = current
                    inconsistent = inconsistent or earliest.signature != sample.signature
                    if sample.timestamp < earliest.timestamp:
                        earliest = sample
                    grouped[key] = (earliest, row_count + 1, inconsistent)

    cost = Decimal(0)
    rows_with_usage = 0
    unique_requests = 0
    duplicate_rows = 0
    inconsistent_requests = 0
    unpriced_models: set[str] = set()

    for sample, row_count, inconsistent in grouped.values():
        if not window_start <= sample.timestamp <= now:
            continue
        rows_with_usage += row_count
        unique_requests += 1
        duplicate_rows += row_count - 1
        if inconsistent:
            inconsistent_requests += 1
            continue
        sample_cost = _sample_cost(sample)
        if sample_cost is None:
            unpriced_models.add(sample.model)
            continue
        cost += sample_cost

    hourly_rate = cost * Decimal(60) / Decimal(window_minutes)
    incomplete = bool(
        unpriced_models or invalid_recent_rows or inconsistent_requests or scan_errors
    )
    if hourly_rate > threshold_usd_per_hour:
        status = "burn_rate_exceeded"
    elif incomplete:
        status = "measurement_incomplete"
    else:
        status = "below_threshold"

    return Measurement(
        status=status,
        window_minutes=window_minutes,
        threshold_usd_per_hour=threshold_usd_per_hour,
        estimated_cost_usd=cost,
        estimated_usd_per_hour=hourly_rate,
        rows_with_usage=rows_with_usage,
        unique_requests=unique_requests,
        duplicate_rows=duplicate_rows,
        skipped_rows=skipped_rows_count,
        unpriced_models=tuple(sorted(unpriced_models)),
        invalid_recent_rows=invalid_recent_rows,
        inconsistent_requests=inconsistent_requests,
        scan_errors=tuple(scan_errors),
    )


def build_broadcast_message(measurement: Measurement) -> str | None:
    """Build the stop message only for a proven burn-rate breach."""
    if measurement.status != "burn_rate_exceeded":
        return None
    rate = measurement.estimated_usd_per_hour.quantize(_MONEY_QUANTUM)
    threshold = measurement.threshold_usd_per_hour.quantize(_MONEY_QUANTUM)
    return (
        f"立即停手：最近 {measurement.window_minutes} 分鐘的 Anthropic API list-price "
        f"估值為 ${rate}/hr，超過你設定的 ${threshold}/hr。"
        "這是燒錢速率觸發，不是額度快用完；請先判斷這段工作是否值得繼續。"
    )


def _decimal_setting(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ConfigError(f"{field} must be a positive number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ConfigError(f"{field} must be a positive number") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ConfigError(f"{field} must be a positive number")
    return parsed


def load_config(path: Path) -> GuardConfig:
    """Load the required user-owned threshold and window settings."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("config root must be an object")

    window = payload.get("window_minutes")
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise ConfigError("window_minutes must be a positive integer")
    threshold = _decimal_setting(payload.get("max_usd_per_hour"), "max_usd_per_hour")
    return GuardConfig(window_minutes=window, max_usd_per_hour=threshold)


def _measurement_payload(measurement: Measurement) -> dict[str, Any]:
    return {
        "status": measurement.status,
        "reason": "burn_rate" if measurement.status == "burn_rate_exceeded" else None,
        "pricing_basis": "Anthropic API list-price estimate; not a billing amount",
        "window_minutes": measurement.window_minutes,
        "threshold_usd_per_hour": float(measurement.threshold_usd_per_hour),
        "estimated_cost_usd": float(measurement.estimated_cost_usd.quantize(_MONEY_QUANTUM)),
        "estimated_usd_per_hour": float(
            measurement.estimated_usd_per_hour.quantize(_MONEY_QUANTUM)
        ),
        "rows_with_usage": measurement.rows_with_usage,
        "unique_requests": measurement.unique_requests,
        "duplicate_rows": measurement.duplicate_rows,
        "skipped_rows": measurement.skipped_rows,
        "unpriced_models": list(measurement.unpriced_models),
        "invalid_recent_rows": measurement.invalid_recent_rows,
        "inconsistent_requests": measurement.inconsistent_requests,
        "scan_errors": list(measurement.scan_errors),
        "broadcast_message": build_broadcast_message(measurement),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guard a Claude Code fleet using transcript-derived USD/hour estimates."
    )
    parser.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    parser.add_argument("--projects-dir", type=Path, default=_DEFAULT_PROJECTS_DIR)
    parser.add_argument(
        "--now",
        help=(
            "UTC/offset ISO-8601 snapshot time for deterministic replay; defaults to current time."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        now = _parse_timestamp(args.now) if args.now else datetime.now(UTC)
        measurement = evaluate_burn_rate(
            args.projects_dir,
            now=now,
            window_minutes=config.window_minutes,
            threshold_usd_per_hour=config.max_usd_per_hour,
        )
    except ConfigError as exc:
        print(json.dumps({"status": "config_error", "error": str(exc)}), file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except (MeasurementError, ValueError) as exc:
        print(
            json.dumps({"status": "measurement_incomplete", "error": str(exc)}),
            file=sys.stderr,
        )
        return EXIT_MEASUREMENT_INCOMPLETE

    print(json.dumps(_measurement_payload(measurement), ensure_ascii=False, indent=2))
    if measurement.status == "burn_rate_exceeded":
        return EXIT_BURN_RATE_EXCEEDED
    if measurement.status == "measurement_incomplete":
        return EXIT_MEASUREMENT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
