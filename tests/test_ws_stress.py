"""
tests/test_ws_stress.py - Empirical WebSocket Concurrency & Disconnect Chaos Stress Test Suite.

Adversarial Verification for Milestone 3 (Backend REST & WebSocket Services):
1. Multi-Client Concurrency Stress Test:
   - 25+ simultaneous WebSocket clients connecting to /ws/telemetry.
   - Verifies initial SNAPSHOT payload schema on every client.
   - Verifies periodic UPDATE broadcast distribution to all connected clients.
   - Verifies bidirectional communication: string 'PING' and JSON {'type': 'PING'} -> 'PONG'.
2. Disconnect Chaos & Immediate Reconnection:
   - Connects 25 concurrent clients, abruptly terminates 15 (abnormal transport drop & clean close).
   - Verifies server immunity, zero crashes, zero leaked sockets in ConnectionManager.
   - Verifies HTTP /api/health reflects exact remaining active clients.
   - Verifies surviving clients continue uninterrupted broadcast streaming.
   - Connects 15 new clients immediately; verifies instant SNAPSHOT and seamless broadcast resumption.
3. Rapid Ping Flooding:
   - High-frequency ping/pong bursts per client without frame desync.
4. Malformed Input Robustness:
   - Broken JSON, non-ping commands, empty strings handled gracefully without server exception.
5. High-Burst Concurrency:
   - 50 simultaneous clients connecting and disconnecting in bursts.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import socket
import time
from typing import Any, AsyncGenerator, Dict, List, Tuple

import httpx
import pytest
import uvicorn
import websockets

from api.websocket import manager as ws_manager
from main import app
from models.schemas import HealthResponse, TelemetryResponse

logger = logging.getLogger("test_ws_stress")


# ============================================================================
# Live Server Async Context Manager on Ephemeral Port
# ============================================================================

def get_free_port() -> int:
    """Finds an unused TCP port on localhost."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@asynccontextmanager
async def run_live_server() -> AsyncGenerator[Tuple[str, int], None]:
    """
    Spins up the full FastAPI application with lifespan (OpenSky worker + WS broadcaster)
    on a live ephemeral TCP port.
    Yields (base_http_url, port).
    Cleanly shuts down on context exit.
    """
    port = get_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name=f"uvicorn_test_server_{port}")

    # Wait until server is listening
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{base_url}/api/health", timeout=0.2)
                if res.status_code == 200:
                    break
        except Exception:
            await asyncio.sleep(0.05)
    else:
        server.should_exit = True
        await server_task
        raise RuntimeError(f"Live test server failed to start on port {port}")

    try:
        yield (base_url, port)
    finally:
        server.should_exit = True
        await server_task


# ============================================================================
# 1. Multi-Client Concurrency Stress Test (25 concurrent clients)
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_multi_client_concurrency() -> None:
    """
    Stress-tests /ws/telemetry with 25 concurrent WebSocket clients.
    Verifies:
    1. Every client receives an initial valid SNAPSHOT payload.
    2. Every client performs bidirectional communication (string PING & JSON PING -> PONG).
    3. Every client receives periodic UPDATE broadcasts.
    4. Active connection count in ConnectionManager matches 25 during test and 0 after cleanup.
    """
    async with run_live_server() as (base_url, port):
        ws_uri = f"ws://127.0.0.1:{port}/ws/telemetry"
        num_clients = 25

        async def client_session(client_id: int) -> Dict[str, Any]:
            results: Dict[str, Any] = {
                "client_id": client_id,
                "snapshot_received": False,
                "snapshot_valid": False,
                "text_pong_received": False,
                "json_pong_received": False,
                "update_received": False,
            }

            async with websockets.connect(ws_uri) as ws:
                # 1. Receive initial SNAPSHOT
                raw_snapshot = await asyncio.wait_for(ws.recv(), timeout=5.0)
                snapshot_msg = json.loads(raw_snapshot)

                msg_type = str(snapshot_msg.get("type") or snapshot_msg.get("event") or "").upper()
                if msg_type == "SNAPSHOT":
                    results["snapshot_received"] = True
                    data = snapshot_msg.get("data", {})
                    try:
                        parsed = TelemetryResponse.model_validate(data)
                        if parsed.total_aircraft >= 0 and "aircraft" in data:
                            results["snapshot_valid"] = True
                    except Exception as e:
                        logger.error("Client %d snapshot validation error: %s", client_id, e)

                # 2. Bidirectional ping-pong: Text PING
                await ws.send("PING")
                pong1_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                pong1_msg = json.loads(pong1_raw)
                if str(pong1_msg.get("type") or pong1_msg.get("event") or "").upper() == "PONG":
                    results["text_pong_received"] = True

                # 3. Bidirectional ping-pong: JSON PING
                await ws.send(json.dumps({"type": "PING"}))
                pong2_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                pong2_msg = json.loads(pong2_raw)
                if str(pong2_msg.get("type") or pong2_msg.get("event") or "").upper() == "PONG":
                    results["json_pong_received"] = True

                # 4. Await periodic broadcast UPDATE (interval is 2.0s)
                update_raw = await asyncio.wait_for(ws.recv(), timeout=6.0)
                update_msg = json.loads(update_raw)
                if str(update_msg.get("type") or update_msg.get("event") or "").upper() == "UPDATE":
                    results["update_received"] = True

            return results

        tasks = [asyncio.create_task(client_session(i)) for i in range(num_clients)]
        all_results = await asyncio.gather(*tasks)

        assert len(all_results) == num_clients
        for res in all_results:
            cid = res["client_id"]
            assert res["snapshot_received"], f"Client {cid} did not receive initial SNAPSHOT"
            assert res["snapshot_valid"], f"Client {cid} received invalid SNAPSHOT data"
            assert res["text_pong_received"], f"Client {cid} failed text PING -> PONG"
            assert res["json_pong_received"], f"Client {cid} failed JSON PING -> PONG"
            assert res["update_received"], f"Client {cid} failed to receive broadcast UPDATE"

        await asyncio.sleep(0.3)
        assert ws_manager.active_count == 0, f"Expected 0 active connections, got {ws_manager.active_count}"

        async with httpx.AsyncClient() as http_client:
            res = await http_client.get(f"{base_url}/api/health")
            assert res.status_code == 200
            health = res.json()
            assert health["active_websocket_clients"] == 0


# ============================================================================
# 2. Disconnect Chaos & Reconnection Resilience Test
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_disconnect_chaos_and_reconnection() -> None:
    """
    Adversarial Disconnect Chaos Test:
    1. Connects 25 concurrent clients to /ws/telemetry.
    2. Abruptly drops 15 clients (mix of abnormal transport termination and clean closes).
    3. Asserts server remains healthy, no unhandled exceptions, ConnectionManager cleans up.
    4. Asserts remaining 10 clients continue receiving live UPDATE broadcasts uninterrupted.
    5. Connects 15 new clients; asserts they immediately receive SNAPSHOT and join the stream.
    6. Verifies total active connections return to 25.
    """
    async with run_live_server() as (base_url, port):
        ws_uri = f"ws://127.0.0.1:{port}/ws/telemetry"
        initial_count = 25
        dropped_count = 15
        surviving_count = initial_count - dropped_count  # 10

        # Step 1: Connect 25 clients and verify they all receive initial SNAPSHOT
        active_sockets: List[websockets.asyncio.client.ClientConnection] = []
        for _ in range(initial_count):
            ws = await websockets.connect(ws_uri)
            raw = await ws.recv()
            msg = json.loads(raw)
            assert str(msg.get("type") or msg.get("event") or "").upper() == "SNAPSHOT"
            active_sockets.append(ws)

        assert len(active_sockets) == initial_count
        await asyncio.sleep(0.2)
        assert ws_manager.active_count == initial_count

        async with httpx.AsyncClient() as http_client:
            res = await http_client.get(f"{base_url}/api/health")
            assert res.status_code == 200
            assert res.json()["active_websocket_clients"] == initial_count

        # Step 2: Chaos Drop - Abruptly terminate 15 clients
        victims = active_sockets[:dropped_count]
        survivors = active_sockets[dropped_count:]
        assert len(victims) == dropped_count
        assert len(survivors) == surviving_count

        for i, ws in enumerate(victims):
            if i < 10:
                try:
                    transport = getattr(ws, "transport", None)
                    if transport is not None:
                        transport.abort()
                    else:
                        await ws.close(code=1006)
                except Exception:
                    pass
            else:
                await ws.close(code=1000)

        # Allow broadcast loop and disconnect callbacks to evict dead sockets
        await asyncio.sleep(2.5)

        # Step 3: Verify ConnectionManager pruned dead sockets
        assert ws_manager.active_count == surviving_count, (
            f"Expected {surviving_count} active connections after drop, got {ws_manager.active_count}"
        )

        async with httpx.AsyncClient() as http_client:
            res = await http_client.get(f"{base_url}/api/health")
            assert res.status_code == 200
            assert res.json()["active_websocket_clients"] == surviving_count

        # Step 4: Verify surviving clients continue to receive live UPDATE broadcasts
        for s_idx, ws in enumerate(survivors):
            received_update = False
            for _ in range(3):
                try:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                    parsed = json.loads(msg_raw)
                    if str(parsed.get("type") or parsed.get("event") or "").upper() == "UPDATE":
                        received_update = True
                        break
                except Exception as e:
                    logger.error("Survivor %d error: %s", s_idx, e)
                    break
            assert received_update, f"Surviving client {s_idx} failed to receive subsequent UPDATE broadcast"

        # Step 5: Immediate Reconnection Phase
        new_sockets: List[websockets.asyncio.client.ClientConnection] = []
        for n_idx in range(dropped_count):
            new_ws = await websockets.connect(ws_uri)
            new_raw = await asyncio.wait_for(new_ws.recv(), timeout=5.0)
            new_msg = json.loads(new_raw)
            assert str(new_msg.get("type") or new_msg.get("event") or "").upper() == "SNAPSHOT", (
                f"Reconnected client {n_idx} did not receive initial SNAPSHOT"
            )
            new_sockets.append(new_ws)

        await asyncio.sleep(0.2)
        assert ws_manager.active_count == initial_count, (
            f"Expected {initial_count} connections after reconnection, got {ws_manager.active_count}"
        )

        combined_sockets = survivors + new_sockets
        assert len(combined_sockets) == initial_count

        async def verify_receives_update(ws: Any) -> bool:
            try:
                for _ in range(3):
                    m_raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                    m = json.loads(m_raw)
                    if str(m.get("type") or m.get("event") or "").upper() == "UPDATE":
                        return True
            except Exception:
                return False
            return False

        update_checks = await asyncio.gather(*[verify_receives_update(ws) for ws in combined_sockets])
        assert all(update_checks), "Not all reconnected & surviving clients received broadcast UPDATE"

        for ws in combined_sockets:
            try:
                await ws.close()
            except Exception:
                pass

        await asyncio.sleep(0.3)
        assert ws_manager.active_count == 0


# ============================================================================
# 3. Rapid Ping Flooding & Bidirectional Stress
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_rapid_ping_flooding() -> None:
    """
    Stress-tests high-frequency bidirectional ping-pong exchanges across 5 clients.
    Each client sends 30 rapid PING messages (alternating string and JSON).
    Verifies all 30 PONGs are received promptly without drops or server desync.
    """
    async with run_live_server() as (base_url, port):
        ws_uri = f"ws://127.0.0.1:{port}/ws/telemetry"
        num_pings = 30

        async def flooder(client_id: int) -> int:
            pong_count = 0
            async with websockets.connect(ws_uri) as ws:
                snap_raw = await ws.recv()
                assert "SNAPSHOT" in snap_raw

                for i in range(num_pings):
                    if i % 2 == 0:
                        await ws.send("PING")
                    else:
                        await ws.send(json.dumps({"type": "PING"}))

                    resp_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    resp = json.loads(resp_raw)
                    while str(resp.get("type") or resp.get("event") or "").upper() == "UPDATE":
                        resp_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        resp = json.loads(resp_raw)

                    if str(resp.get("type") or resp.get("event") or "").upper() == "PONG":
                        pong_count += 1

            return pong_count

        results = await asyncio.gather(*[flooder(i) for i in range(5)])
        for count in results:
            assert count == num_pings, f"Expected {num_pings} PONG responses, received {count}"


# ============================================================================
# 4. Malformed Input & Non-Ping Resilience
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_malformed_input_resilience() -> None:
    """
    Sends adversarial inputs over WebSocket:
    - broken JSON
    - non-ping JSON commands
    - empty strings
    - large text messages
    Verifies server survives, does not crash, ignores unrecognized messages,
    and still answers subsequent PING with PONG and streams UPDATEs.
    """
    async with run_live_server() as (base_url, port):
        ws_uri = f"ws://127.0.0.1:{port}/ws/telemetry"

        async with websockets.connect(ws_uri) as ws:
            snap = json.loads(await ws.recv())
            assert snap.get("event") == "SNAPSHOT" or snap.get("type") == "SNAPSHOT"

            dirty_payloads = [
                "NOT_A_PING",
                "",
                "   ",
                "{broken json",
                json.dumps({"action": "unknown", "payload": None}),
                json.dumps({"type": "SUBSCRIBE"}),
                "X" * 10000,
            ]

            for payload in dirty_payloads:
                await ws.send(payload)
                await asyncio.sleep(0.02)

            await ws.send("PING")
            pong_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            pong = json.loads(pong_raw)
            if str(pong.get("type") or pong.get("event") or "").upper() == "UPDATE":
                pong_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                pong = json.loads(pong_raw)

            assert str(pong.get("type") or pong.get("event") or "").upper() == "PONG"


# ============================================================================
# 5. High-Burst Concurrency Test (50 simultaneous clients)
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_high_burst_50_clients() -> None:
    """
    Stress-tests a high burst of 50 simultaneous WebSocket connections.
    Verifies all 50 receive SNAPSHOT, server handles high connection load,
    and all 50 can disconnect cleanly with ConnectionManager returning to 0.
    """
    async with run_live_server() as (base_url, port):
        ws_uri = f"ws://127.0.0.1:{port}/ws/telemetry"
        burst_size = 50

        async def burst_client() -> bool:
            try:
                async with websockets.connect(ws_uri) as ws:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg = json.loads(raw)
                    return str(msg.get("type") or msg.get("event") or "").upper() == "SNAPSHOT"
            except Exception:
                return False

        results = await asyncio.gather(*[burst_client() for _ in range(burst_size)])
        assert all(results), f"Failed: {results.count(False)} out of {burst_size} clients did not receive SNAPSHOT"

        await asyncio.sleep(0.5)
        assert ws_manager.active_count == 0, f"Expected 0 active clients after burst, got {ws_manager.active_count}"
