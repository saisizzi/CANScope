from __future__ import annotations

import random
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.database import record_event, record_frame


@dataclass
class SignalSpec:
    name: str
    start_bit: int
    length: int
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    signed: bool = False
    min_value: float | None = None
    max_value: float | None = None


@dataclass
class ECUProfile:
    name: str
    ecu_id: str
    can_id: int
    interval_ms: int
    enabled: bool = True
    state: dict[str, float] = field(default_factory=dict)
    signals: list[SignalSpec] = field(default_factory=list)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def encode_bits(value: int, start_bit: int, length: int, payload: bytearray) -> None:
    for bit_index in range(length):
        bit_position = start_bit + bit_index
        byte_index = bit_position // 8
        bit_offset = bit_position % 8
        if byte_index >= len(payload):
            raise ValueError(f"Bit position {bit_position} exceeds payload length")
        if (value >> bit_index) & 1:
            payload[byte_index] |= 1 << bit_offset


def decode_bits(payload: bytes, start_bit: int, length: int, signed: bool = False) -> int:
    value = 0
    for bit_index in range(length):
        bit_position = start_bit + bit_index
        byte_index = bit_position // 8
        bit_offset = bit_position % 8
        if byte_index >= len(payload):
            break
        if (payload[byte_index] >> bit_offset) & 1:
            value |= 1 << bit_index
    if signed and value & (1 << (length - 1)):
        value -= 1 << length
    return value


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


ECU_LIBRARY = {
    "engine": ECUProfile(
        name="Engine Control Unit",
        ecu_id="engine",
        can_id=0x100,
        interval_ms=200,
        enabled=True,
        state={"rpm": 1200.0, "coolant_temp": 86.0, "engine_load": 34.0, "throttle": 28.0},
        signals=[
            SignalSpec("rpm", 0, 16, scale=1.0, offset=0.0, unit="rpm", min_value=500.0, max_value=9000.0),
            SignalSpec("coolant_temp", 16, 8, scale=1.0, offset=0.0, unit="°C", min_value=60.0, max_value=120.0),
            SignalSpec("engine_load", 24, 8, scale=1.0, offset=0.0, unit="%", min_value=0.0, max_value=100.0),
            SignalSpec("throttle", 32, 8, scale=1.0, offset=0.0, unit="%", min_value=0.0, max_value=100.0),
        ],
    ),
    "abs": ECUProfile(
        name="ABS Control Unit",
        ecu_id="abs",
        can_id=0x200,
        interval_ms=150,
        enabled=True,
        state={"wheel_speed_fl": 48.0, "wheel_speed_fr": 49.0, "wheel_speed_rl": 46.0, "wheel_speed_rr": 47.0, "brake": 0.0},
        signals=[
            SignalSpec("wheel_speed_fl", 0, 12, scale=1.0, offset=0.0, unit="km/h", min_value=0.0, max_value=220.0),
            SignalSpec("wheel_speed_fr", 12, 12, scale=1.0, offset=0.0, unit="km/h", min_value=0.0, max_value=220.0),
            SignalSpec("wheel_speed_rl", 24, 12, scale=1.0, offset=0.0, unit="km/h", min_value=0.0, max_value=220.0),
            SignalSpec("wheel_speed_rr", 36, 12, scale=1.0, offset=0.0, unit="km/h", min_value=0.0, max_value=220.0),
            SignalSpec("brake", 48, 8, scale=1.0, offset=0.0, unit="state", min_value=0.0, max_value=1.0),
        ],
    ),
    "bms": ECUProfile(
        name="Battery Management System",
        ecu_id="bms",
        can_id=0x300,
        interval_ms=300,
        enabled=True,
        state={"battery_voltage": 13.6, "battery_temp": 34.0, "soc": 76.0, "charging": 0.0},
        signals=[
            SignalSpec("battery_voltage", 0, 12, scale=10.0, offset=0.0, unit="V", min_value=10.0, max_value=15.5),
            SignalSpec("battery_temp", 12, 8, scale=1.0, offset=0.0, unit="°C", min_value=0.0, max_value=90.0),
            SignalSpec("soc", 20, 8, scale=1.0, offset=0.0, unit="%", min_value=0.0, max_value=100.0),
            SignalSpec("charging", 28, 8, scale=1.0, offset=0.0, unit="state", min_value=0.0, max_value=1.0),
        ],
    ),
    "cluster": ECUProfile(
        name="Instrument Cluster",
        ecu_id="cluster",
        can_id=0x400,
        interval_ms=250,
        enabled=True,
        state={"vehicle_speed": 58.0, "warning_flags": 0.0, "gear": 3.0, "dashboard_status": 1.0},
        signals=[
            SignalSpec("vehicle_speed", 0, 12, scale=1.0, offset=0.0, unit="km/h", min_value=0.0, max_value=220.0),
            SignalSpec("warning_flags", 12, 8, scale=1.0, offset=0.0, unit="code", min_value=0.0, max_value=255.0),
            SignalSpec("gear", 20, 8, scale=1.0, offset=0.0, unit="gear", min_value=0.0, max_value=8.0),
            SignalSpec("dashboard_status", 28, 8, scale=1.0, offset=0.0, unit="state", min_value=0.0, max_value=1.0),
        ],
    ),
}


class CANScopeSimulator:
    def __init__(self) -> None:
        self.ecus: dict[str, ECUProfile] = {key: profile for key, profile in ECU_LIBRARY.items()}
        self.frames: list[dict[str, Any]] = []
        self.anomalies: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._last_ticks: dict[str, float] = {}

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _advance_state(self, profile: ECUProfile) -> None:
        state = profile.state
        if profile.ecu_id == "engine":
            state["rpm"] = clamp(state["rpm"] + random.uniform(-100.0, 220.0), 600.0, 9000.0)
            state["coolant_temp"] = clamp(state["coolant_temp"] + random.uniform(-0.4, 0.8), 70.0, 120.0)
            state["engine_load"] = clamp(state["engine_load"] + random.uniform(-8.0, 12.0), 15.0, 96.0)
            state["throttle"] = clamp(state["throttle"] + random.uniform(-10.0, 12.0), 0.0, 100.0)
        elif profile.ecu_id == "abs":
            for key in ["wheel_speed_fl", "wheel_speed_fr", "wheel_speed_rl", "wheel_speed_rr"]:
                state[key] = clamp(state[key] + random.uniform(-4.0, 6.0), 0.0, 220.0)
            state["brake"] = 1.0 if random.random() < 0.18 else 0.0
        elif profile.ecu_id == "bms":
            state["battery_voltage"] = clamp(state["battery_voltage"] + random.uniform(-0.12, 0.18), 11.5, 15.2)
            state["battery_temp"] = clamp(state["battery_temp"] + random.uniform(-0.4, 0.7), 20.0, 90.0)
            state["soc"] = clamp(state["soc"] + random.uniform(-0.7, 0.9), 15.0, 100.0)
            state["charging"] = 1.0 if random.random() < 0.25 else 0.0
        elif profile.ecu_id == "cluster":
            state["vehicle_speed"] = clamp(state["vehicle_speed"] + random.uniform(-5.0, 8.0), 0.0, 200.0)
            state["warning_flags"] = round(random.uniform(0.0, 6.0))
            state["gear"] = round(random.uniform(1.0, 6.0))
            state["dashboard_status"] = 1.0 if random.random() < 0.95 else 0.0

    def _build_payload(self, profile: ECUProfile) -> bytes:
        payload = bytearray(8)
        for signal in profile.signals:
            raw_value = profile.state.get(signal.name, 0.0)
            if signal.name in {"battery_voltage"}:
                raw_value *= 10.0
            raw = int(round(raw_value / signal.scale))
            if signal.min_value is not None and signal.max_value is not None:
                raw = int(round(clamp(raw_value, signal.min_value, signal.max_value)))
            if signal.name in {"rpm"}:
                raw = int(round(raw_value))
            # pack values into the 64-bit payload window
            for bit_index in range(signal.length):
                bit_position = signal.start_bit + bit_index
                byte_index = bit_position // 8
                bit_offset = bit_position % 8
                if byte_index >= len(payload):
                    continue
                bit = (raw >> bit_index) & 1
                if bit:
                    payload[byte_index] |= 1 << bit_offset
        return bytes(payload)

    def _decode_payload(self, payload: bytes, profile: ECUProfile) -> dict[str, float]:
        decoded: dict[str, float] = {}
        for signal in profile.signals:
            integer_value = decode_bits(payload, signal.start_bit, signal.length, signed=signal.signed)
            value = integer_value * signal.scale + signal.offset
            if signal.name == "battery_voltage":
                value = integer_value / 10.0
            decoded[signal.name] = round(float(value), 2)
        return decoded

    def _generate_frame_for_ecu(self, profile: ECUProfile) -> dict[str, Any]:
        self._advance_state(profile)
        payload = self._build_payload(profile)
        decoded = self._decode_payload(payload, profile)
        timestamp = _iso_now()
        frame = {
            "timestamp": timestamp,
            "can_id": profile.can_id,
            "sender": profile.name,
            "dlc": len(payload),
            "payload_hex": payload.hex(),
            "decoded": decoded,
        }
        return frame

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                for profile in self.ecus.values():
                    if not profile.enabled:
                        continue
                    if time.monotonic() - self._last_ticks.get(profile.ecu_id, 0.0) >= profile.interval_ms / 1000:
                        frame = self._generate_frame_for_ecu(profile)
                        self.frames.append(frame)
                        self.frames = self.frames[-250:]
                        record_frame(frame)
                        self._last_ticks[profile.ecu_id] = time.monotonic()
                        self._check_for_anomalies(frame)
            time.sleep(0.05)

    def _check_for_anomalies(self, frame: dict[str, Any]) -> None:
        decoded = frame["decoded"]
        if frame["can_id"] == 0x100 and decoded.get("rpm", 0) > 7500:
            anomaly = self._make_anomaly("high", "engine", frame["can_id"], "RPM above safe threshold", {"rpm": decoded["rpm"]})
            self.anomalies.append(anomaly)
        if frame["can_id"] == 0x300 and decoded.get("battery_temp", 0) > 70:
            anomaly = self._make_anomaly("medium", "bms", frame["can_id"], "Battery temperature elevated", {"battery_temp": decoded["battery_temp"]})
            self.anomalies.append(anomaly)
        if frame["can_id"] == 0x200 and decoded.get("wheel_speed_fl", 0) > 180:
            anomaly = self._make_anomaly("medium", "abs", frame["can_id"], "Wheel speed anomaly detected", {"wheel_speed_fl": decoded["wheel_speed_fl"]})
            self.anomalies.append(anomaly)
        self.anomalies = self.anomalies[-25:]

    def _make_anomaly(self, severity: str, source: str, can_id: int, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "timestamp": _iso_now(),
            "severity": severity,
            "source": source,
            "kind": "signal_anomaly",
            "can_id": can_id,
            "message": message,
            "details": details,
        }

    def get_dashboard_snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = self.frames[-50:]
            now = datetime.now(timezone.utc)
            metrics = {
                "total_frames": len(self.frames),
                "active_ecus": sum(1 for ecu in self.ecus.values() if ecu.enabled),
                "messages_per_second": round(len(recent) / max(len(recent), 1), 2),
                "bus_utilization": round(min(100.0, (len(recent) / 180.0) * 100.0), 2),
                "last_update": now.isoformat(),
            }
            summary = {
                "frame_count": len(self.frames),
                "latest_messages": recent[-10:],
                "anomalies": self.anomalies[-10:],
                "ecus": [
                    {"ecu_id": ecu.ecu_id, "name": ecu.name, "can_id": ecu.can_id, "enabled": ecu.enabled, "interval_ms": ecu.interval_ms}
                    for ecu in self.ecus.values()
                ],
                "signals": self._collect_signal_summary(recent),
                "stats": metrics,
            }
        return summary

    def _collect_signal_summary(self, recent: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for frame in recent:
            sender = frame["sender"]
            entry = result.setdefault(sender, {})
            for key, value in frame["decoded"].items():
                current = entry.setdefault(key, [])
                current.append(value)
        aggregate: dict[str, Any] = {}
        for sender, signals in result.items():
            aggregate[sender] = {}
            for name, values in signals.items():
                if values:
                    aggregate[sender][name] = {
                        "latest": values[-1],
                        "average": round(sum(values) / len(values), 2),
                        "min": min(values),
                        "max": max(values),
                    }
        return aggregate

    def toggle_ecu(self, ecu_id: str) -> dict[str, Any]:
        with self._lock:
            if ecu_id not in self.ecus:
                raise KeyError(f"Unknown ECU: {ecu_id}")
            profile = self.ecus[ecu_id]
            profile.enabled = not profile.enabled
            event = {
                "timestamp": _iso_now(),
                "severity": "info",
                "kind": "ecu_toggle",
                "message": f"{profile.name} {'enabled' if profile.enabled else 'disabled'}",
                "can_id": profile.can_id,
                "details": {"ecu_id": ecu_id, "enabled": profile.enabled},
            }
            record_event(event)
            return {"ecu_id": ecu_id, "enabled": profile.enabled}

    def inject_fault(self, ecu_id: str, fault_kind: str = "drop") -> dict[str, Any]:
        with self._lock:
            if ecu_id not in self.ecus:
                raise KeyError(f"Unknown ECU: {ecu_id}")
            profile = self.ecus[ecu_id]
            if fault_kind == "drop":
                profile.enabled = False
                message = f"Fault injected: {profile.name} transmission disabled"
            else:
                message = f"Fault injected: {profile.name} abnormal traffic detected"
            event = {
                "timestamp": _iso_now(),
                "severity": "warning",
                "kind": "fault_injection",
                "message": message,
                "can_id": profile.can_id,
                "details": {"fault_kind": fault_kind, "ecu_id": ecu_id},
            }
            record_event(event)
            self.anomalies.append({
                "timestamp": _iso_now(),
                "severity": "warning",
                "source": profile.name,
                "kind": "fault_injection",
                "can_id": profile.can_id,
                "message": message,
                "details": {"fault_kind": fault_kind},
            })
            return {"status": "ok", "message": message}


simulator = CANScopeSimulator()
