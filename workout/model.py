from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

ZwoValue = Union[str, int, float, bool, None]
ZwoNode = Dict[str, Any]


@dataclass(frozen=True)
class Interval:
    duration: float
    power: Optional[float] = None
    cadence: Optional[float] = None
    type: Optional[str] = None
    attrs: Dict[str, ZwoValue] = field(default_factory=dict)

    @staticmethod
    def from_node(node: ZwoNode) -> "Interval":
        interval_info = node.get("interval") or {}
        duration = interval_info.get("duration")
        if duration is None:
            raise ValueError("Interval node is missing duration")
        return Interval(
            duration=float(duration),
            power=_optional_float(interval_info.get("power")),
            cadence=_optional_float(interval_info.get("cadence")),
            type=node.get("type"),
            attrs=dict(node.get("attrs", {})),
        )


@dataclass(frozen=True)
class Workout:
    name: Optional[str]
    author: Optional[str]
    sport_type: Optional[ZwoValue]
    tags: List[str]
    description: Optional[str]
    intervals: List[Interval]

    @property
    def total_duration(self) -> float:
        return sum(interval.duration for interval in self.intervals)

    @classmethod
    def from_parsed(cls, parsed: ZwoNode) -> "Workout":
        if not isinstance(parsed, dict):
            raise ValueError("Parsed workout data must be a dict")

        if parsed.get("type") is None:
            intervals = _intervals_from_list(parsed.get("intervals", [])) if isinstance(parsed.get("intervals"), list) else _extract_wod_intervals(parsed)
            if not intervals:
                raise ValueError("Parsed workout data contains no intervals")
            return cls(
                name=parsed.get("name"),
                author=parsed.get("author"),
                sport_type=parsed.get("sport_type") or parsed.get("sportType"),
                tags=list(parsed.get("tags", [])),
                description=parsed.get("description"),
                intervals=intervals,
            )

        if parsed.get("type") != "Workout":
            raise ValueError("Parsed data must represent a Workout node")

        return cls(
            name=parsed.get("name"),
            author=parsed.get("author"),
            sport_type=parsed.get("sport_type"),
            tags=list(parsed.get("tags", [])),
            description=parsed.get("description"),
            intervals=_extract_wod_intervals(parsed),
        )


def _intervals_from_list(intervals_data: List[ZwoNode]) -> List[Interval]:
    output: List[Interval] = []
    for item in intervals_data:
        if not isinstance(item, dict):
            continue
        duration = item.get("duration")
        if duration is None:
            continue
        output.append(
            Interval(
                duration=float(duration),
                power=_optional_float(item.get("power")),
                cadence=_optional_float(item.get("cadence")),
                type=item.get("type"),
                attrs=dict(item.get("attrs", {})),
            )
        )
    return output


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _repeat_count(value: Any) -> int:
    if value is None:
        return 1
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid repeat count: {value!r}") from exc
    if count < 0:
        raise ValueError("Repeat count cannot be negative")
    return count


def _extract_wod_intervals(node: ZwoNode) -> List[Interval]:
    if not isinstance(node, dict):
        return []

    attrs = node.get("attrs", {}) or {}
    repeat = _repeat_count(attrs.get("Repeat"))

    children = node.get("children") or []
    if children:
        output: List[Interval] = []
        for _ in range(repeat):
            for child in children:
                output.extend(_extract_wod_intervals(child))
        return output

    if node.get("type") == "IntervalsT":
        return _intervals_from_intervals_t(attrs)

    interval_info = node.get("interval")
    if interval_info is not None:
        interval = Interval.from_node(node)
        return [interval] * repeat

    return []


def _intervals_from_intervals_t(attrs: Dict[str, ZwoValue]) -> List[Interval]:
    repeat = _repeat_count(attrs.get("Repeat"))
    on_duration = attrs.get("OnDuration")
    off_duration = attrs.get("OffDuration")
    on_power = _optional_float(attrs.get("OnPower"))
    off_power = _optional_float(attrs.get("OffPower"))
    cadence = _optional_float(attrs.get("Cadence"))

    output: List[Interval] = []
    for _ in range(repeat):
        if on_duration is not None:
            output.append(
                Interval(
                    duration=float(on_duration),
                    power=on_power,
                    cadence=cadence,
                    type="IntervalsT",
                    attrs=dict(attrs),
                )
            )
        if off_duration is not None:
            output.append(
                Interval(
                    duration=float(off_duration),
                    power=off_power,
                    cadence=cadence,
                    type="IntervalsT",
                    attrs=dict(attrs),
                )
            )
    return output