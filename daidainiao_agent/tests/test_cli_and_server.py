import io

from fastapi.testclient import TestClient

from daidainiao_agent.cli import emit_json
from daidainiao_agent import fastapi_server
from daidainiao_agent.server import parse_multipart_file


def test_emit_json_writes_utf8_bytes(monkeypatch) -> None:
    class BinaryStdout:
        def __init__(self) -> None:
            self.buffer = io.BytesIO()

    stream = BinaryStdout()
    monkeypatch.setattr("sys.stdout", stream)

    emit_json({"copyright": "©"})

    assert stream.buffer.getvalue().decode("utf-8").strip() == '{\n  "copyright": "©"\n}'


def test_parse_multipart_file_extracts_upload() -> None:
    boundary = "----daidainiao-agent-test"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="paper.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "hello paper\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    filename, file_bytes = parse_multipart_file(f"multipart/form-data; boundary={boundary}", body)

    assert filename == "paper.txt"
    assert file_bytes == b"hello paper"


def test_get_missing_session_returns_404() -> None:
    fastapi_server._rate_limits.clear()
    client = TestClient(fastapi_server.app)
    try:
        response = client.get("/sessions/does-not-exist")
    finally:
        fastapi_server._rate_limits.clear()
    assert response.status_code == 404


def test_static_assets_do_not_count_against_rate_limit() -> None:
    fastapi_server._rate_limits.clear()
    client = TestClient(fastapi_server.app)

    try:
        for _ in range(31):
            assert client.get("/static/app.js").status_code == 200

        assert fastapi_server._rate_limits == {}

        for _ in range(30):
            assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 429
    finally:
        fastapi_server._rate_limits.clear()


def test_update_model_settings_can_reuse_existing_api_key(monkeypatch, tmp_path) -> None:
    class DummyLLM:
        api_key = "existing-key"

    class DummyAgent:
        llm = DummyLLM()

        def reconfigure_llm(self, api_key: str, base_url: str = "", model: str = "") -> dict:
            return {
                "provider": "openai_compatible",
                "chat_enabled": True,
                "model": model,
                "embedding_enabled": False,
                "rerank_enabled": False,
                "api_key": api_key,
            }

    class DummyApp:
        agent = DummyAgent()

    monkeypatch.setattr(fastapi_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fastapi_server, "MODEL_PROFILES_PATH", tmp_path / "data" / "model_profiles.json")
    monkeypatch.setattr(fastapi_server, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(fastapi_server, "get_app", lambda: DummyApp())

    fastapi_server._rate_limits.clear()
    client = TestClient(fastapi_server.app)
    try:
        response = client.post(
            "/settings/model",
            json={
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "model": "custom-model",
            },
        )
    finally:
        fastapi_server._rate_limits.clear()

    assert response.status_code == 200
    assert response.json()["model"] == "custom-model"
    assert response.json()["base_url"] == "https://example.test/v1"
    assert response.json()["profiles"][0]["model"] == "custom-model"
    assert "api_key" not in response.json()["profiles"][0]
    assert "DASHSCOPE_API_KEY=existing-key" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DASHSCOPE_MODEL=custom-model" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_update_model_settings_can_switch_saved_profile(monkeypatch, tmp_path) -> None:
    calls = []

    class DummyLLM:
        api_key = "current-key"

    class DummyAgent:
        llm = DummyLLM()

        def reconfigure_llm(self, api_key: str, base_url: str = "", model: str = "") -> dict:
            calls.append({"api_key": api_key, "base_url": base_url, "model": model})
            return {
                "provider": "openai_compatible",
                "chat_enabled": True,
                "model": model,
                "embedding_enabled": False,
                "rerank_enabled": False,
            }

    class DummyApp:
        agent = DummyAgent()

    monkeypatch.setattr(fastapi_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fastapi_server, "MODEL_PROFILES_PATH", tmp_path / "data" / "model_profiles.json")
    monkeypatch.setattr(fastapi_server, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(fastapi_server, "get_app", lambda: DummyApp())

    fastapi_server._rate_limits.clear()
    client = TestClient(fastapi_server.app)
    try:
        created = client.post(
            "/settings/model",
            json={
                "provider": "openai_compatible",
                "api_key": "saved-key",
                "base_url": "https://saved.example/v1",
                "model": "saved-model",
                "name": "Saved Model",
            },
        )
        profile_id = created.json()["profile"]["id"]
        switched = client.post("/settings/model", json={"profile_id": profile_id})
    finally:
        fastapi_server._rate_limits.clear()

    assert switched.status_code == 200
    assert switched.json()["model"] == "saved-model"
    assert switched.json()["active_profile_id"] == profile_id
    assert calls[-1] == {
        "api_key": "saved-key",
        "base_url": "https://saved.example/v1",
        "model": "saved-model",
    }
    assert len(switched.json()["profiles"]) == 1


def test_update_model_settings_keeps_each_saved_profile(monkeypatch, tmp_path) -> None:
    class DummyLLM:
        api_key = "current-key"

    class DummyAgent:
        llm = DummyLLM()

        def reconfigure_llm(self, api_key: str, base_url: str = "", model: str = "") -> dict:
            return {
                "provider": "openai_compatible",
                "chat_enabled": True,
                "model": model,
                "embedding_enabled": False,
                "rerank_enabled": False,
            }

    class DummyApp:
        agent = DummyAgent()

    monkeypatch.setattr(fastapi_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fastapi_server, "MODEL_PROFILES_PATH", tmp_path / "data" / "model_profiles.json")
    monkeypatch.setattr(fastapi_server, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(fastapi_server, "get_app", lambda: DummyApp())

    payload = {
        "provider": "openai_compatible",
        "api_key": "saved-key",
        "base_url": "https://saved.example/v1",
        "model": "saved-model",
    }

    fastapi_server._rate_limits.clear()
    client = TestClient(fastapi_server.app)
    try:
        first = client.post("/settings/model", json={**payload, "name": "First"})
        second = client.post("/settings/model", json={**payload, "name": "Second"})
    finally:
        fastapi_server._rate_limits.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    profiles = second.json()["profiles"]
    assert [profile["name"] for profile in profiles[:2]] == ["Second", "First"]
    assert profiles[0]["id"] != profiles[1]["id"]
    assert second.json()["active_profile_id"] == profiles[0]["id"]
    assert "api_key" not in profiles[0]
