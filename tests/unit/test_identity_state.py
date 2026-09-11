import pytest

from core.identity_state import IdentityStateStore


def test_identity_state_roundtrip_and_event_chain(tmp_path):
    with IdentityStateStore(tmp_path / "identity.sqlite3") as store:
        snapshot = store.upsert("chat-1", display_name="Danilo", preferences={"language": "pt-BR"}, commitments=["confirmar ações sensíveis"], current_state="ready")
        assert snapshot.version == 0
        assert store.get("chat-1").display_name == "Danilo"
        store.append_event("chat-1", "message_processed", {"task": "status"})
        store.append_event("chat-1", "preference_updated", {"language": "pt-BR"})
        assert store.verify_events("chat-1")


def test_identity_optimistic_version_blocks_stale_writer(tmp_path):
    with IdentityStateStore(tmp_path / "identity.sqlite3") as store:
        snapshot = store.upsert("chat-1", current_state="idle")
        store.upsert("chat-1", current_state="active", expected_version=snapshot.version)
        with pytest.raises(RuntimeError, match="conflito"):
            store.upsert("chat-1", current_state="stale", expected_version=snapshot.version)


def test_tampered_identity_is_rejected(tmp_path):
    path = tmp_path / "identity.sqlite3"
    with IdentityStateStore(path) as store:
        store.upsert("chat-1", display_name="Danilo")
        store.connection.execute("UPDATE identity_state SET display_name='tampered' WHERE identity_id='chat-1'")
        store.connection.commit()
        with pytest.raises(ValueError, match="hash"):
            store.get("chat-1")
