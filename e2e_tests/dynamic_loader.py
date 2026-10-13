"""
Dynamic Loader and Progressive Testability Bridge for AeroPulse E2E Testing.

Provides safe discovery and unified access to AeroPulse core components,
REST API application, models, and static assets across milestone stages.
"""

import os
import sys
import importlib
from pathlib import Path
from typing import Optional, Any, Tuple, Type
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_module_safe(module_path: str) -> Optional[Any]:
    """Safely import a module by path, returning None if not found."""
    try:
        return importlib.import_module(module_path)
    except (ImportError, ModuleNotFoundError):
        return None
    except Exception as e:
        # If there is a syntax error or runtime initialization error, re-raise
        # so test runner can catch real defects
        raise e


# --- Component Loaders ---

def get_anomaly_components() -> Tuple[Optional[Type], Optional[Type], Optional[Type]]:
    """
    Returns (MechanicalAnomalyEngine, AnomalySeverity, AnomalyFlag/AnomalyEvent).
    Looks for standard classes in core.anomaly_engine and models.anomaly.
    """
    engine_mod = load_module_safe("core.anomaly_engine")
    model_mod = load_module_safe("models.anomaly")
    
    engine_cls = None
    if engine_mod:
        engine_cls = (
            getattr(engine_mod, "MechanicalAnomalyEngine", None) or
            getattr(engine_mod, "AnomalyEngine", None)
        )
        
    severity_cls = None
    event_cls = None
    if model_mod:
        severity_cls = getattr(model_mod, "AnomalySeverity", None)
        event_cls = (
            getattr(model_mod, "AnomalyFlag", None) or
            getattr(model_mod, "AnomalyEvent", None) or
            getattr(model_mod, "AnomalyRecord", None)
        )
    elif engine_mod:
        severity_cls = getattr(engine_mod, "AnomalySeverity", None)
        event_cls = (
            getattr(engine_mod, "AnomalyFlag", None) or
            getattr(engine_mod, "AnomalyEvent", None)
        )
        
    return engine_cls, severity_cls, event_cls


def get_cache_components() -> Tuple[Optional[Type], Optional[Type]]:
    """
    Returns (AircraftCache_or_FlightCache, FlightState_or_AircraftVector).
    """
    cache_mod = load_module_safe("core.cache")
    aircraft_mod = load_module_safe("models.aircraft")
    
    cache_cls = None
    if cache_mod:
        cache_cls = (
            getattr(cache_mod, "AircraftCache", None) or
            getattr(cache_mod, "FlightCache", None)
        )
        
    state_cls = None
    if aircraft_mod:
        state_cls = (
            getattr(aircraft_mod, "FlightState", None) or
            getattr(aircraft_mod, "AircraftVector", None)
        )
    elif cache_mod:
        state_cls = (
            getattr(cache_mod, "FlightState", None) or
            getattr(cache_mod, "AircraftVector", None)
        )
        
    return cache_cls, state_cls


def get_ingestion_components() -> Tuple[Optional[Any], Optional[Any]]:
    """
    Returns (IngestionWorker_or_OpenSkyPoller, TupleSanitizer_or_parse_func).
    """
    ingestion_mod = load_module_safe("core.ingestion")
    if not ingestion_mod:
        return None, None
        
    worker_cls = (
        getattr(ingestion_mod, "IngestionWorker", None) or
        getattr(ingestion_mod, "OpenSkyPoller", None)
    )
    sanitizer = (
        getattr(ingestion_mod, "sanitize_tuple", None) or
        getattr(ingestion_mod, "parse_state_vector", None) or
        getattr(ingestion_mod, "tuple_to_state", None) or
        getattr(ingestion_mod, "Sanitizer", None)
    )
    return worker_cls, sanitizer


def get_fastapi_app() -> Optional[Any]:
    """Returns the FastAPI application instance from main.py."""
    main_mod = load_module_safe("main")
    if main_mod and hasattr(main_mod, "app"):
        return getattr(main_mod, "app")
    return None


# --- Milestone Readiness Checks ---

def is_m1_ready() -> bool:
    """Checks if Milestone 1 (Ingestion & Caching) is implemented."""
    cache_cls, state_cls = get_cache_components()
    return cache_cls is not None and state_cls is not None


def is_m2_ready() -> bool:
    """Checks if Milestone 2 (Deterministic Anomaly Engine) is implemented."""
    engine_cls, _, _ = get_anomaly_components()
    return engine_cls is not None


def is_m3_ready() -> bool:
    """Checks if Milestone 3 (Backend REST & WebSocket API) is implemented."""
    return get_fastapi_app() is not None


def is_m4_ready() -> bool:
    """Checks if Milestone 4 (Static Military HUD Dashboard) is implemented."""
    static_index = PROJECT_ROOT / "static" / "index.html"
    return static_index.is_file() and static_index.stat().st_size > 50


def is_m5_launcher_ready() -> bool:
    """Checks if Milestone 5 launcher run.bat is present."""
    run_bat = PROJECT_ROOT / "run.bat"
    return run_bat.is_file() and run_bat.stat().st_size > 20


# --- Pytest Skip Markers ---

skip_unless_m1 = pytest.mark.skipif(
    not is_m1_ready(),
    reason="Milestone M1 (Ingestion & Caching) not yet implemented"
)

skip_unless_m2 = pytest.mark.skipif(
    not is_m2_ready(),
    reason="Milestone M2 (Deterministic Anomaly Engine) not yet implemented"
)

skip_unless_m3 = pytest.mark.skipif(
    not is_m3_ready(),
    reason="Milestone M3 (Backend REST & WebSocket Services) not yet implemented"
)

skip_unless_m4 = pytest.mark.skipif(
    not is_m4_ready(),
    reason="Milestone M4 (Military HUD Dashboard Static Assets) not yet implemented"
)

skip_unless_m5 = pytest.mark.skipif(
    not is_m5_launcher_ready(),
    reason="Milestone M5 (Windows Launcher run.bat) not yet created"
)
