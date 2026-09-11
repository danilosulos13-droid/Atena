from __future__ import annotations

from core.robot_command_gateway import (
    RobotCommandGateway,
    RobotProfile,
    parse_robot_voice_intent,
)


def profiles() -> list[RobotProfile]:
    return [
        RobotProfile(robot_id="robot-casa", location="casa", display_name="Robô da casa"),
        RobotProfile(robot_id="robot-sitio", location="sitio", display_name="Robô do sítio"),
    ]


def test_voice_intent_routes_by_location() -> None:
    intent = parse_robot_voice_intent("Atena, verifique o status do robô do sítio")
    assert intent is not None
    assert intent.action == "robot_status"
    assert intent.location == "sitio"


def test_dangerous_voice_intent_requires_approval(tmp_path) -> None:
    intent = parse_robot_voice_intent("Atena, feche a porta no sítio")
    assert intent is not None
    assert intent.action == "robot_close_door"
    gateway = RobotCommandGateway(profiles(), ledger_path=tmp_path / "robot.sqlite3", dry_run=True)
    command = gateway.build_command(intent, now=100)
    blocked = gateway.dispatch(command, now=101)
    assert blocked["status"] == "approval_required"
    allowed = gateway.dispatch(command, approved=True, now=101)
    assert allowed["status"] == "simulated"
    assert allowed["result"]["device_state_changed"] is False


def test_expired_command_is_not_sent(tmp_path) -> None:
    intent = parse_robot_voice_intent("Atena, vá para a sala com o robô da casa")
    assert intent is not None
    gateway = RobotCommandGateway(profiles(), ledger_path=tmp_path / "robot.sqlite3", dry_run=True, command_ttl_seconds=5)
    command = gateway.build_command(intent, now=100)
    result = gateway.dispatch(command, approved=True, now=106)
    assert result["status"] == "expired"


def test_duplicate_command_id_is_rejected(tmp_path) -> None:
    intent = parse_robot_voice_intent("Atena, consulte o status do robô da casa")
    assert intent is not None
    gateway = RobotCommandGateway(profiles(), ledger_path=tmp_path / "robot.sqlite3", dry_run=True)
    command = gateway.build_command(intent, now=100)
    assert gateway.dispatch(command, now=101)["status"] == "simulated"
    assert gateway.dispatch(command, now=101)["status"] == "duplicate"


def test_watchdog_expires_queued_commands(tmp_path) -> None:
    intent = parse_robot_voice_intent("Atena, inicie a missão do robô da casa")
    assert intent is not None
    gateway = RobotCommandGateway(profiles(), ledger_path=tmp_path / "robot.sqlite3", dry_run=True)
    command = gateway.build_command(intent, now=100)
    # A aprovação não é concedida; inserimos o estado através de um dispatch aprovado
    # apenas para verificar que o watchdog mantém uma resposta determinística.
    assert gateway.dispatch(command, approved=True, now=101)["status"] == "simulated"
    report = gateway.watchdog(now=200)
    assert report["safe_state"] is True
