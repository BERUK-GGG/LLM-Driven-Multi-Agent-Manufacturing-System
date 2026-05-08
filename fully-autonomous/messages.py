from dataclasses import dataclass, field
import time


@dataclass
class Event:
    source: str
    timestamp: float = field(default_factory=time.time)


# ── Sensor ────────────────────────────────────────────────────────────────────

@dataclass
class PartDetected(Event):
    """Rising-edge detection: a part appeared at a source station."""
    source_id: int = 0
    position_x: int = 0


@dataclass
class SensorUpdate(Event):
    """Full sensor snapshot published every poll cycle."""
    source1: bool = False
    source2: bool = False
    process1_running: bool = False
    process2_running: bool = False
    crane_x: int = 0
    crane_y: int = 0


# ── Crane work orders ─────────────────────────────────────────────────────────

@dataclass
class WorkOrder(Event):
    """OversightAgent → CraneAgent: execute a pick-and-place."""
    order_id: int = 0
    part_id: int = 0
    part_type: int = 0
    pick_x: int = 0
    place_x: int = 0


@dataclass
class WorkOrderComplete(Event):
    """CraneAgent → all: a WorkOrder finished."""
    order_id: int = 0
    part_id: int = 0
    part_type: int = 0
    pick_x: int = 0
    place_x: int = 0


@dataclass
class CraneAcquiredLock(Event):
    order_id: int = 0


@dataclass
class CraneReleasedLock(Event):
    order_id: int = 0


# ── Process machine ───────────────────────────────────────────────────────────

@dataclass
class StartProcess(Event):
    """OversightAgent → ProcessAgent: start a machine cycle."""
    process_id: int = 0
    part_id: int = 0
    part_type: int = 0


@dataclass
class ProcessComplete(Event):
    """ProcessAgent → all: machine cycle finished, part ready for pickup."""
    process_id: int = 0
    part_id: int = 0
    part_type: int = 0


# ── Oversight ─────────────────────────────────────────────────────────────────

@dataclass
class FactoryIdle(Event):
    """OversightAgent publishes when nothing is queued or active."""
    pass
