"""
AeroPulse In-Memory Resilient Cache
Thread-safe, high-throughput flight cache with per-aircraft sliding-window ring buffer (maxlen=30),
sub-millisecond retrieval, TTL stale flight pruning, and aggregate statistics.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.anomaly_engine import MechanicalAnomalyEngine
from models.aircraft import AircraftDetail, FlightState, TrailPoint
from models.anomaly import AnomalyFlag, AnomalyRecord, AnomalySeverity


def _get_flag_category(flag: Any) -> str:
    """Safely extract anomaly category or type from flag or dict."""
    if isinstance(flag, dict):
        return str(flag.get("category") or flag.get("type") or "")
    return str(getattr(flag, "category", "") or getattr(flag, "type", ""))


@dataclass
class _CachedFlightRecord:
    """Internal cache entry storing raw state, FIFO ring buffer, and pre-materialized detail."""
    state: FlightState
    first_seen: float
    last_seen: float
    trail: collections.deque[TrailPoint] = field(default_factory=lambda: collections.deque(maxlen=30))
    status: str = "NOMINAL"
    anomalies: List[Any] = field(default_factory=list)
    detail: Optional[AircraftDetail] = None
    detail_dict: Optional[Dict[str, Any]] = None

    def refresh_detail(self) -> AircraftDetail:
        """Pre-materializes an AircraftDetail instance for instantaneous O(1) reads."""
        s = self.state
        has_anom = self.status != "NOMINAL" or len(self.anomalies) > 0
        self.detail = AircraftDetail(
            icao24=s.icao24,
            callsign=s.callsign,
            origin_country=s.origin_country,
            longitude=s.longitude,
            latitude=s.latitude,
            baro_altitude=s.baro_altitude,
            velocity=s.velocity,
            vertical_rate=s.vertical_rate,
            squawk=s.squawk,
            true_track=s.true_track,
            on_ground=s.on_ground,
            last_contact=s.last_contact,
            geo_altitude=s.geo_altitude,
            trail=list(self.trail),
            status=self.status,
            anomalies=self.anomalies,
            has_anomaly=has_anom,
        )
        self.detail_dict = self.detail.model_dump(mode="json")
        return self.detail


class AircraftCache:
    """
    Thread-safe, in-memory cache keyed by ICAO24 transponder address.
    Guarantees < 50ms retrieval SLA under 1,500 active flights.
    """

    def __init__(
        self,
        max_trail_len: int = 30,
        max_trail_points: Optional[int] = None,
        max_anomalies_buffer: int = 100,
    ) -> None:
        if max_trail_points is not None:
            max_trail_len = max_trail_points
        self._lock = threading.RLock()
        self._flights: Dict[str, _CachedFlightRecord] = {}
        self._recent_anomalies: collections.deque[AnomalyRecord] = collections.deque(maxlen=max_anomalies_buffer)
        self._anomaly_engine = MechanicalAnomalyEngine
        self._max_trail_len = max_trail_len
        self._pruned_count: int = 0
        self._total_updates: int = 0
        self._created_at: float = time.time()
        self._cached_stats: Optional[Dict[str, Any]] = None
        self._stats_dirty: bool = True

    def update_vector(
        self,
        state: FlightState,
        anomalies: Optional[List[Any]] = None,
        status: Optional[str] = None,
    ) -> AircraftDetail:
        """
        Atomically updates or creates an aircraft entry in the cache.
        Appends new valid coordinates to the sliding-window ring buffer.
        """
        if not isinstance(state, FlightState):
            state = FlightState(**state)

        with self._lock:
            self._total_updates += 1
            icao = state.icao24.strip().lower()
            now = time.time()

            is_new_flight = icao not in self._flights
            if is_new_flight:
                record = _CachedFlightRecord(
                    state=state,
                    first_seen=now,
                    last_seen=now,
                    trail=collections.deque(maxlen=self._max_trail_len),
                )
                self._flights[icao] = record
                prev_categories = set()
            else:
                record = self._flights[icao]
                record.state = state
                record.last_seen = now
                prev_categories = {
                    _get_flag_category(f) for f in record.anomalies
                }

            # Append coordinate to ring buffer if valid position fix exists
            if state.latitude is not None and state.longitude is not None:
                # Avoid duplicate timestamp appends from redundant polling ticks
                should_append = True
                if len(record.trail) > 0:
                    last_pt = record.trail[-1]
                    if last_pt.timestamp == state.last_contact:
                        should_append = False

                if should_append:
                    pt = TrailPoint(
                        lat=state.latitude,
                        lon=state.longitude,
                        altitude=state.baro_altitude,
                        velocity=state.velocity,
                        vertical_rate=state.vertical_rate,
                        heading=state.true_track,
                        timestamp=state.last_contact,
                    )
                    record.trail.append(pt)

            # Automated Mechanical Anomaly Evaluation (M2 Integration)
            if anomalies is None:
                detected_flags = self._anomaly_engine.evaluate(state)
                record.anomalies = detected_flags
                record.status = self._anomaly_engine.resolve_severity(detected_flags).value
            else:
                record.anomalies = anomalies
                if status is not None:
                    record.status = status
                elif anomalies:
                    record.status = self._anomaly_engine.resolve_severity(anomalies).value
                else:
                    record.status = "NOMINAL"

            if status is not None:
                record.status = status

            # Log new state transitions to the historical recent_anomalies feed
            for flag in record.anomalies:
                cat = _get_flag_category(flag)
                if cat and cat not in prev_categories:
                    rec = AnomalyRecord.from_flag(
                        flag,
                        icao24=state.icao24,
                        callsign=state.callsign,
                    )
                    self._recent_anomalies.append(rec)

            # Pre-materialize detail snapshot
            self._stats_dirty = True
            return record.refresh_detail()

    # Alias for update_vector
    def update(
        self,
        state: FlightState,
        anomalies: Optional[List[Any]] = None,
        status: Optional[str] = None,
    ) -> AircraftDetail:
        return self.update_vector(state, anomalies=anomalies, status=status)

    def set_anomalies(self, icao24: str, anomalies: List[Any], status: str) -> bool:
        """Updates anomaly evaluation results for an existing aircraft."""
        with self._lock:
            icao = icao24.strip().lower()
            record = self._flights.get(icao)
            if not record:
                return False
            prev_categories = {
                _get_flag_category(f) for f in record.anomalies
            }
            record.anomalies = anomalies
            record.status = status
            for flag in anomalies:
                cat = _get_flag_category(flag)
                if cat and cat not in prev_categories:
                    rec = AnomalyRecord.from_flag(
                        flag,
                        icao24=record.state.icao24,
                        callsign=record.state.callsign,
                    )
                    self._recent_anomalies.append(rec)
            self._stats_dirty = True
            record.refresh_detail()
            return True

    def get_flight(self, icao24: str) -> Optional[AircraftDetail]:
        """
        O(1) single-flight lookup by ICAO24 hex address.
        Returns pre-materialized AircraftDetail or None.
        """
        with self._lock:
            icao = icao24.strip().lower()
            record = self._flights.get(icao)
            if not record:
                return None
            return record.detail

    def get_all_active(self, airborne_only: bool = False) -> List[AircraftDetail]:
        """
        Returns a snapshot list of active aircraft with their full 30-point kinematic trails.
        Guaranteed to execute in < 50ms (typically < 0.1ms).
        """
        with self._lock:
            if not airborne_only:
                return [
                    r.detail for r in self._flights.values() if r.detail is not None
                ]
            return [
                r.detail
                for r in self._flights.values()
                if r.detail is not None and not r.state.on_ground
            ]

    # Alias for get_all_active
    def get_active_telemetry(self, airborne_only: bool = False) -> List[AircraftDetail]:
        return self.get_all_active(airborne_only=airborne_only)

    def get_all_active_dicts(self, airborne_only: bool = False) -> List[Dict[str, Any]]:
        """
        Returns pre-serialized dictionary snapshots for ultra-fast JSON serialization (< 1ms).
        """
        with self._lock:
            if not airborne_only:
                return [
                    r.detail_dict if r.detail_dict is not None else r.detail.model_dump(mode="json")
                    for r in self._flights.values() if r.detail is not None
                ]
            return [
                r.detail_dict if r.detail_dict is not None else r.detail.model_dump(mode="json")
                for r in self._flights.values()
                if r.detail is not None and not r.state.on_ground
            ]

    def prune_stale(
        self,
        ttl_seconds: float = 120.0,
        now: Optional[float] = None,
        current_time: Optional[float] = None,
    ) -> int:
        """
        Prunes inactive aircraft that have landed or departed coverage area.
        Returns the number of aircraft pruned during this cycle.
        """
        with self._lock:
            ref_time = now if now is not None else (current_time if current_time is not None else time.time())
            stale_keys: List[str] = []

            for icao, r in self._flights.items():
                # Compare against last_contact (transponder epoch) or last_seen (system epoch)
                flight_time = r.state.last_contact if r.state.last_contact is not None else r.last_seen
                age_flight = ref_time - flight_time
                age_system = ref_time - r.last_seen

                if age_flight > ttl_seconds or age_system > ttl_seconds:
                    stale_keys.append(icao)

            for icao in stale_keys:
                del self._flights[icao]

            if stale_keys:
                self._stats_dirty = True
            self._pruned_count += len(stale_keys)
            return len(stale_keys)

    # Alias for prune_stale
    def evict_stale(
        self,
        ttl_seconds: float = 120.0,
        now: Optional[float] = None,
        current_time: Optional[float] = None,
    ) -> int:
        return self.prune_stale(ttl_seconds=ttl_seconds, now=now, current_time=current_time)

    def get_recent_anomalies(self, limit: Optional[int] = None) -> List[AnomalyRecord]:
        """Returns recent anomaly events in reverse-chronological order (newest first)."""
        with self._lock:
            records = list(self._recent_anomalies)
            records.reverse()
            if limit is not None and limit > 0:
                return records[:limit]
            return records

    def add_anomaly_record(self, record: AnomalyRecord) -> None:
        """Manually append an anomaly event record to the sliding buffer."""
        with self._lock:
            self._recent_anomalies.append(record)

    def get_stats(self) -> Dict[str, Any]:
        """Calculates real-time aggregate statistics for telemetry headers and /api/stats."""
        with self._lock:
            now = time.time()
            if not self._stats_dirty and self._cached_stats is not None:
                res = dict(self._cached_stats)
                res["uptime_seconds"] = round(now - self._created_at, 2)
                return res

            total = len(self._flights)
            airborne = 0
            on_ground = 0
            anomalous = 0
            severity_counts: Dict[str, int] = {
                "NOMINAL": 0,
                "WARNING": 0,
                "SEVERE": 0,
                "CRITICAL": 0,
            }
            anomalies_by_cat: Dict[str, int] = {
                "SQUAWK_EMERGENCY": 0,
                "SEVERE_DESCENT": 0,
                "OVERSPEED_OUTLIER": 0,
            }
            oldest_age = 0.0

            for r in self._flights.values():
                if r.state.on_ground:
                    on_ground += 1
                else:
                    airborne += 1

                sev = r.status if r.status in severity_counts else "NOMINAL"
                severity_counts[sev] += 1
                if sev != "NOMINAL":
                    anomalous += 1

                for anom in r.anomalies:
                    cat = _get_flag_category(anom).upper()
                    if cat in anomalies_by_cat:
                        anomalies_by_cat[cat] += 1
                    elif cat:
                        anomalies_by_cat[cat] = anomalies_by_cat.get(cat, 0) + 1

                flight_time = r.state.last_contact if r.state.last_contact is not None else r.last_seen
                age = now - flight_time
                if age > oldest_age:
                    oldest_age = age

            self._cached_stats = {
                "total_tracked": total,
                "active_airborne": airborne,
                "active_count": airborne,
                "active_on_ground": on_ground,
                "anomalous_count": anomalous,
                "anomalies_by_severity": severity_counts,
                "anomalies_by_category": anomalies_by_cat,
                "recent_anomalies_count": len(self._recent_anomalies),
                "stale_pruned_total": self._pruned_count,
                "total_updates": self._total_updates,
                "cache_size": total,
                "oldest_entry_age_seconds": round(oldest_age, 2),
                "uptime_seconds": round(now - self._created_at, 2),
            }
            self._stats_dirty = False
            return dict(self._cached_stats)

    def clear(self) -> None:
        """Clears all entries from the cache (for testing and resets)."""
        with self._lock:
            self._flights.clear()
            self._recent_anomalies.clear()
            self._pruned_count = 0
            self._total_updates = 0
            self._cached_stats = None
            self._stats_dirty = True
