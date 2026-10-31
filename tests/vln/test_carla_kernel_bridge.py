"""Unit tests for the authorized CARLA execution bridge.

These tests use a fake execution handler (no CARLA, no Kernel) and prove the
bridge's fail-closed rules:

* a request without the token never reaches the handler;
* a request without a matching single-use permit never reaches the handler;
* a second request for the same permit never reaches the handler twice;
* only an authorized callback result is returned, with displacement computed
  from the real pre/post states;
* the transaction evidence distinguishes authorized, started and finished.

They do not prove that a vehicle moved; that requires the real CARLA run.
"""

from __future__ import annotations

import json
import socket

import pytest

from vln.carla.kernel_bridge import CarlaExecutionBridge


def _intent(intent_id: str = "i-1", x: float = 1.0, y: float = 2.0) -> dict:
    return {
        "contract_version": "1",
        "intent_id": intent_id,
        "action": "parking.move",
        "target": {"x": x, "y": y, "heading": 0.0},
    }


def _request(
    *,
    request_id: str = "r-1",
    intent: dict | None = None,
    token: str = "t",
) -> dict:
    intent = _intent() if intent is None else intent
    return {
        "protocol_version": "1",
        "request_id": request_id,
        "intent_id": intent["intent_id"],
        "capability_id": "parking.move",
        "token": token,
        "payload": intent,
    }


def _send(
    bridge: CarlaExecutionBridge, request: dict, *, token: str | None = None
) -> dict:
    request = dict(request)
    if token is not None:
        request["token"] = token
    with socket.create_connection(tuple(bridge.endpoint.split(":"))) as sock:
        sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
        received = b""
        while b"\n" not in received:
            chunk = sock.recv(65536)
            if not chunk:
                break
            received += chunk
    return json.loads(received.split(b"\n", 1)[0])


def _result(status: str = "completed", **overrides) -> dict:
    result = {
        "status": status,
        "stop_reason": "success",
        "pre_state": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 0.0},
        "post_state": {"x": 1.5, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 0.0},
        "stopped": True,
        "segment_success": status == "completed",
        "steps": 4,
        "records": [],
    }
    result.update(overrides)
    return result


def _register(bridge: CarlaExecutionBridge, request: dict, context=None) -> None:
    intent = request["payload"]
    bridge.register_permit(
        request_id=request["request_id"],
        intent_id=request["intent_id"],
        target=intent["target"],
        payload=json.dumps(intent),
        context=context,
    )


def test_authorized_request_runs_handler_once_and_returns_real_displacement() -> None:
    calls = []

    def handler(permit):
        calls.append(permit)
        return _result()

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        response = _send(bridge, request)
        transaction = bridge.get_transaction("r-1")

    assert response["status"] == "completed"
    assert response["execution_mode"] == "carla"
    assert response["request_id"] == "r-1"
    assert response["intent_id"] == "i-1"
    assert response["vehicle"]["moved_m"] == pytest.approx(1.5)
    assert response["vehicle"]["stopped"] is True
    assert len(calls) == 1
    assert transaction is not None
    assert transaction["authorized"] is True
    assert transaction["handler_started"] is True
    assert transaction["handler_finished"] is True

    # A second request for the same id has no permit and cannot move anything.
    with CarlaExecutionBridge(handler, token="t") as second:
        assert _send(second, request)["status"] == "rejected"
    assert len(calls) == 1


def test_token_mismatch_never_reaches_the_handler() -> None:
    calls = []

    def handler(permit):
        calls.append(permit)
        return _result()

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        response = _send(bridge, request, token="wrong")
        transaction = bridge.get_transaction("r-1")

    assert response["status"] == "rejected"
    assert "token" in response["reason"]
    assert calls == []
    assert transaction["authorized"] is False
    assert transaction["handler_started"] is False


def test_request_without_permit_never_reaches_the_handler() -> None:
    calls = []

    def handler(permit):
        calls.append(permit)
        return _result()

    with CarlaExecutionBridge(handler, token="t") as bridge:
        response = _send(bridge, _request())

    assert response["status"] == "rejected"
    assert "permit" in response["reason"]
    assert calls == []


def test_intent_identity_or_target_mismatch_is_rejected() -> None:
    calls = []

    def handler(permit):
        calls.append(permit)
        return _result()

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        forged = json.loads(json.dumps(request))
        forged["payload"]["target"] = {"x": 9.0, "y": 2.0, "heading": 0.0}
        forged["payload"]["intent_id"] = "i-other"
        forged["intent_id"] = "i-other"
        response = _send(bridge, forged)
        transaction = bridge.get_transaction("r-1")

    assert response["status"] == "rejected"
    assert calls == []
    assert transaction["authorized"] is False


def test_second_execution_with_same_request_id_does_not_reach_handler() -> None:
    calls = []

    def handler(permit):
        calls.append(permit)
        return _result()

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        first = _send(bridge, request)
        second = _send(bridge, request)

    assert first["status"] == "completed"
    assert second["status"] == "rejected"
    assert len(calls) == 1


def test_failed_handler_result_is_returned_without_claiming_completion() -> None:
    def handler(permit):
        return _result(
            status="failed",
            stop_reason="controller_exception",
            stopped=False,
            segment_success=False,
            error={"type": "RuntimeError", "message": "boom"},
        )

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        response = _send(bridge, request)
        transaction = bridge.get_transaction("r-1")

    assert response["status"] == "failed"
    assert response["vehicle"]["stopped"] is False
    assert response["error"]["type"] == "RuntimeError"
    assert transaction["authorized"] is True


def test_stop_diagnostics_are_preserved_in_vehicle_and_transaction() -> None:
    diagnostics = {
        "schema_version": "1",
        "stop_reason": "obstacle",
        "stop_detail": "ground_bad_inside_ego",
        "ground_inside_ego": True,
        "safety": {"ground_probes": [{"inside_ego_footprint": True}]},
    }

    def handler(permit):
        return _result(
            status="stopped",
            stop_reason="obstacle",
            segment_success=False,
            stop_diagnostics=diagnostics,
            stop_detail=diagnostics["stop_detail"],
        )

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        response = _send(bridge, request)
        transaction = bridge.get_transaction("r-1")

    assert response["vehicle"]["stop_diagnostics"] == diagnostics
    assert response["vehicle"]["stop_detail"] == "ground_bad_inside_ego"
    assert transaction["vehicle"]["stop_diagnostics"] == diagnostics


def test_completed_result_without_confirmed_stop_is_rejected() -> None:
    def handler(permit):
        return _result(stopped=False)

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        response = _send(bridge, request)

    assert response["status"] == "rejected"
    assert "stopped" in response["reason"]


def test_handler_exception_is_contained_and_recorded() -> None:
    def handler(permit):
        raise RuntimeError("controller exploded")

    request = _request()
    with CarlaExecutionBridge(handler, token="t") as bridge:
        _register(bridge, request)
        response = _send(bridge, request)
        transaction = bridge.get_transaction("r-1")

    assert response["status"] == "rejected"
    assert transaction["authorized"] is True
    assert transaction["handler_started"] is True
    assert transaction["handler_finished"] is False
    assert transaction["error"]["type"] == "RuntimeError"


def test_registering_the_same_permit_twice_is_refused() -> None:
    request = _request()
    with CarlaExecutionBridge(lambda permit: _result(), token="t") as bridge:
        _register(bridge, request)
        with pytest.raises(Exception):
            _register(bridge, request)


def test_handler_can_be_switched_between_stages() -> None:
    calls = []

    def first(permit):
        calls.append("first")
        return _result()

    def second(permit):
        calls.append("second")
        return _result()

    request1 = _request(request_id="r-1")
    request2 = _request(
        request_id="r-2", intent=_intent(intent_id="i-2")
    )
    with CarlaExecutionBridge(first, token="t") as bridge:
        _register(bridge, request1)
        response1 = _send(bridge, request1)
        bridge.set_handler(second)
        _register(bridge, request2)
        response2 = _send(bridge, request2)

    assert response1["status"] == "completed"
    assert response2["status"] == "completed"
    assert calls == ["first", "second"]
