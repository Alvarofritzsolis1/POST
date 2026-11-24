"""Galancito offline: private small model, allowed scope and fallback."""
import json
from pathlib import Path
import pytest

from app.config import settings
from app.facebook_ai import AD_INSTRUCTIONS, REPLY_INSTRUCTIONS
from app.facebook_chat_worker import process_chat_next
from app import facebook_ai, galancito_local
from test_facebook_crm import enable_messaging, incoming
from test_network import network


def test_ollama_private_endpoint_bounded_and_no_thinking(monkeypatch):
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, length):
            return json.dumps({"message": {
                "content": "<think>internal thoughts</think>Hola, ¿Qué trabajo haces?"
            }}).encode()

    def open_mock(req, timeout):
        calls.append((req, timeout))
        return Response()

    monkeypatch.setattr(galancito_local._opener, "open", open_mock)
    assert galancito_local.generate_local_text("System", "hola") == "Hola, ¿Qué trabajo haces?"
    req, timeout = calls[0]
    assert req.full_url == "http://galancito-ollama:11434/api/chat"
    assert timeout <= 25
    payload = json.loads(req.data)
    assert payload["model"] == "qwen3.5:2b-q4_K_M"
    assert payload["think"] is False and payload["stream"] is False
    assert payload["keep_alive"] == "2m"
    assert payload["options"]["num_ctx"] <= 2048
    assert payload["options"]["num_predict"] <= 140


def test_ollama_refuses_unclosed_private_reasoning(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, length): return b'{"message":{"content":"<think>secret"}}'
    monkeypatch.setattr(galancito_local._opener, "open", lambda *a, **kw: Response())
    with pytest.raises(RuntimeError):
        galancito_local.generate_local_text("System", "hola")
    with pytest.raises(ValueError):
        galancito_local.generate_local_text("System", "hola", max_chars=2000)


def test_local_provider_only_two_allowed_tasks(monkeypatch):
    for k, val in {
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "FACEBOOK_AI_ENABLED": "true",
        "GALANCITO_AI_ENABLED": "true",
        "FACEBOOK_AI_API_KEY": "",
        "GALANCITO_AI_API_KEY": "",
    }.items(): monkeypatch.setenv(k, val)
    settings.cache_clear()
    calls = []
    monkeypatch.setattr(facebook_ai, "generate_local_text", lambda *args:
                        calls.append(args) or "Soy Galancito. ¿Qué trabajo haces?")
    monkeypatch.setattr(facebook_ai, "_generate", lambda *a: (_ for _ in ()).throw(
        AssertionError("El modelo local no debe llamar a OpenAI")))
    assert facebook_ai.facebook_reply_ai_available()
    assert facebook_ai.galancito_red_ai_available()
    assert facebook_ai.generate_text(REPLY_INSTRUCTIONS, "gasfiter")
    assert facebook_ai.generate_internal_text("Red de Obras", "consulta")
    assert facebook_ai.generate_text(AD_INSTRUCTIONS, "anuncio") is None
    assert len(calls) == 2
    settings.cache_clear()


def test_facebook_uses_local_ollama_after_explicit_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    for k, v in {
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "FACEBOOK_AI_ENABLED": "true",
        "FACEBOOK_AI_AUTO_REPLY_ENABLED": "true",
        "FACEBOOK_AI_API_KEY": "",
    }.items(): monkeypatch.setenv(k, v)
    settings.cache_clear()
    assert incoming(n, text="ola soy gasfite", mid="local-1").status_code == 200
    center = n["admin"].get("/api/v1/network/facebook/center").json()
    lead = center["leads"][0]
    assert center["ai_provider"] == "ollama"
    assert lead["ai_consent_state"] == "requested"
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert messages[-1]["automated"] is True
    assert lead["specialty"] == "Gasfitería"
    assert "IA local" in messages[-1]["body"]
    sent, generated = [], []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda p, u, text, token: sent.append(text) or "mid-local-" + str(len(sent)))
    monkeypatch.setattr(facebook_ai, "generate_local_text",
                        lambda inst, ctx, limit: generated.append(ctx) or "¿En qué comuna trabajas?")
    monkeypatch.setattr(facebook_ai, "_generate", lambda *a: (_ for _ in ()).throw(
        AssertionError("No paid API")))
    assert process_chat_next(n["Session"])
    assert len(sent) == 1 and not generated
    assert incoming(n, text="sí", mid="local-2").status_code == 200
    assert process_chat_next(n["Session"])
    assert generated and len(sent) == 2
    assert "¿En qué comuna trabajas?" in sent[-1]
    assert "asistente virtual" not in sent[-1].lower()
    settings.cache_clear()


def test_red_de_obras_local_ai_without_external_api(network, monkeypatch):
    n = network
    for k,v in {"GALANCITO_AI_PROVIDER": "ollama", "GALANCITO_AI_ENABLED": "true",
                "GALANCITO_LOCAL_AI_ENABLED": "true", "GALANCITO_AI_API_KEY": ""}.items():
        monkeypatch.setenv(k, v)
    settings.cache_clear()
    calls = []
    monkeypatch.setattr("app.galancito_api.generate_internal_text",
                        lambda *args: calls.append(args) or "Soy Galancito. Revisa Red de Obras.")
    state = n["admin"].get("/api/v1/network/galancito/status").json()
    assert state["local_ai_available"] is True
    assert state["external_ai_available"] is False
    response = n["send"](n["admin"], "/galancito/chat",
        {"message": "Explica cómo organizar una coordinación de servicios", "area": "red_obras", "allow_external_ai": False})
    assert response.status_code == 200
    assert response.json()["source"] == "ai" and len(calls) == 1
    blocked = n["send"](n["admin"], "/galancito/chat",
        {"message": "ayúdame en trabajadores", "area": "galant"})
    assert blocked.status_code == 422
    settings.cache_clear()


def test_compose_optional_memory_cpu_and_no_published_port():
    file = Path(__file__).resolve().parents[3] / "docker-compose.preview.yml"
    text = file.read_text()
    section = text.split("  galancito-ollama:\n",1)[1].split("\n  galancito-trainer:",1)[0]
    for expected in ['profiles: [local-ai]', 'mem_limit: ${GALANCITO_OLLAMA_MEM_LIMIT:-3g}', 'cpus: ${GALANCITO_OLLAMA_CPUS:-1.5}',
                     'OLLAMA_NUM_PARALLEL: "1"', 'OLLAMA_MAX_QUEUE: "2"',
                     'OLLAMA_KEEP_ALIVE: ${GALANCITO_KEEP_ALIVE:-2m}', 'galancito_models:/root/.ollama']:
        assert expected in section
    assert "ports:" not in section


def test_qwen35_routes_live_and_practice_to_separate_servers(monkeypatch):
    from app.config import Settings
    cfg = Settings(galancito_local_model="qwen3.5:2b-q4_K_M", galancito_timeout_seconds=45)
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, length): return b'{"message":{"content":"Hola, maestro."}}'

    def fake_open(req, timeout):
        calls.append((req.full_url, json.loads(req.data), timeout))
        return Response()

    monkeypatch.setattr(galancito_local._opener, "open", fake_open)
    monkeypatch.setattr(galancito_local, "settings", lambda: cfg)
    monkeypatch.setattr(galancito_local, "available_memory_mb", lambda: 8192)
    assert galancito_local.generate_local_text("Responde breve", "hola") == "Hola, maestro."
    assert calls[0][0] == galancito_local.INTERNAL_URL
    assert calls[0][1]["model"] == "qwen3.5:2b-q4_K_M"
    assert calls[0][1]["think"] is False
    assert calls[0][2] == 45
    galancito_local.generate_training_text("Sistema", "hola", 42, cfg)
    assert calls[1][0] == galancito_local.TRAINING_OLLAMA + "/api/chat"
    assert calls[1][1]["model"] == "qwen3.5:2b-q4_K_M"
    legacy_cfg = cfg.model_copy(update={"galancito_local_model": "qwen3:1.7b"})
    with pytest.raises(ValueError, match="Qwen3.5 2B"):
        galancito_local.generate_training_text("Sistema", "hola", 42, legacy_cfg)
    for legacy_model in ("qwen3:1.7b", "qwen3.5:4b-q4_K_M"):
        assert Settings(galancito_local_model=legacy_model).galancito_local_model == "qwen3.5:2b-q4_K_M"
    with pytest.raises(ValueError):
        Settings(galancito_local_model="arbitrary-model")


def test_qwen35_without_db_policy_never_selects_external_team(monkeypatch):
    from app.config import Settings
    cfg = Settings(galancito_local_model="qwen3.5:2b-q4_K_M",
                   facebook_ai_enabled=True, facebook_ai_provider="ollama",
                   galancito_local_ai_enabled=True)
    def forbidden(*args):
        raise AssertionError("Do not select external team for local candidate")
    monkeypatch.setattr(facebook_ai, "orchestration_selected", forbidden)
    assert facebook_ai.messenger_ai_source(None, "org", cfg) == "ollama"
    assert facebook_ai.messenger_ai_source(None, "org", cfg.model_copy(update={"facebook_ai_provider": "openai"})) == "disabled"


def test_qwen35_upgrade_preflight_is_read_only(monkeypatch, tmp_path):
    import runpy
    import sys
    script = Path(__file__).resolve().parents[3] / "scripts/upgrade-galancito-qwen35.py"
    ns = runpy.run_path(str(script))
    entered = []
    monkeypatch.setitem(ns["main"].__globals__, "preflight", lambda: entered.append("check"))
    monkeypatch.setitem(ns["main"].__globals__, "activate",
                        lambda: pytest.fail("Default must not activate"))
    monkeypatch.setattr(sys, "argv", [str(script)])
    ns["main"]()
    assert entered == ["check"]


def test_qwen35_upgrade_restores_environment_bytes(monkeypatch, tmp_path):
    import runpy
    script = Path(__file__).resolve().parents[3] / "scripts/upgrade-galancito-qwen35.py"
    ns = runpy.run_path(str(script))
    target = tmp_path / ".env.preview"
    target.write_bytes(b"TEST=changed\n")
    g = ns["restore_env"].__globals__
    monkeypatch.setitem(g, "ENV", target)
    monkeypatch.setitem(g, "ROOT", tmp_path)
    original = b"# comment\nTEST=previous\n"
    ns["restore_env"](original)
    assert target.read_bytes() == original
    assert target.stat().st_mode & 0o777 == 0o600


def test_upgrade_preserves_javiera_compose_overlay():
    import runpy
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    ns = runpy.run_path(str(root / "scripts/upgrade-galancito-qwen35.py"))
    assert str(root / "docker-compose.preview.yml") in ns["COMPOSE"]
    assert str(root / "docker-compose.javiera20.yml") in ns["COMPOSE"]
    assert str(root / ".env.javiera20") in ns["COMPOSE"]


def test_qwen35_smoke_accepts_natural_paraphrases(monkeypatch, capsys):
    """Smoke validates that Ollama responds, not one exact Spanish synonym."""
    import runpy
    import urllib.request
    script = Path(__file__).resolve().parents[3] / "scripts/upgrade-galancito-qwen35.py"
    namespace = runpy.run_path(str(script))
    smoke = namespace["SMOKE"].replace("MODEL_TOKEN", repr(namespace["MODEL"]))
    compile(smoke, "<synthetic-ollama-smoke>", "exec")
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self): return self
        def read(self):
            return json.dumps({"model": namespace["MODEL"], "message": {
                "content": "Hola, que tal, maestro!"}, "eval_count": 20}).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append((json.loads(request.data), timeout))
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    exec(compile(smoke, "<synthetic-ollama-smoke>", "exec"), {})
    assert len(calls) == 2
    assert calls[0][0]["model"] == namespace["MODEL"]
    assert calls[0][1] == 180
    assert calls[1][1] == 45
    assert "SMOKE_OK stage=carga_inicial" in capsys.readouterr().out


def test_qwen35_smoke_reports_http_without_raw_private_output(monkeypatch, capsys):
    import runpy
    import urllib.request
    from urllib.error import HTTPError
    script = Path(__file__).resolve().parents[3] / "scripts/upgrade-galancito-qwen35.py"
    namespace = runpy.run_path(str(script))
    smoke = namespace["SMOKE"].replace("MODEL_TOKEN", repr(namespace["MODEL"]))

    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 400, "bad request", {}, None)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(SystemExit) as exc:
        exec(compile(smoke, "<synthetic-ollama-smoke>", "exec"), {})
    assert exc.value.code == 21
    assert "SMOKE_ERROR stage=carga_inicial http=400" in capsys.readouterr().err


def test_qwen35_install_reports_sanitized_diagnostic_only(monkeypatch):
    import runpy
    import subprocess
    script = Path(__file__).resolve().parents[3] / "scripts/upgrade-galancito-qwen35.py"
    namespace = runpy.run_path(str(script))
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(21, "safe-call",
             stderr="SMOKE_ERROR stage=carga_inicial http=400\nTOKEN=never-reveal\n")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as exc:
        namespace["run"](["docker", "compose", "exec"])
    assert "http=400" in str(exc.value)
    assert "never-reveal" not in str(exc.value)


def test_qwen35_diagnostic_filters_forged_smoke_lines(monkeypatch):
    import runpy
    import subprocess
    script = Path(__file__).resolve().parents[3] / "scripts/upgrade-galancito-qwen35.py"
    namespace = runpy.run_path(str(script))
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            21, "safe-call", stderr="SMOKE_ERROR stage=carga_inicial http=400 TOKEN=never-reveal")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as exc:
        namespace["run"](["docker", "compose", "exec"])
    assert "never-reveal" not in str(exc.value)
    assert "exit_code=21" in str(exc.value)


def test_ollama_installed_model_probe_uses_private_show_and_does_not_pull(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError, URLError

    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return b'{"details":{"family":"qwen3"}}'
    def available(request, timeout):
        calls.append((request, timeout))
        return Response()
    monkeypatch.setattr(galancito_local._opener, "open", available)
    assert galancito_local.installed_model_status("qwen3.5:2b-q4_K_M") is True
    request, timeout = calls[0]
    assert request.full_url == "http://galancito-ollama:11434/api/show"
    assert json.loads(request.data)["model"] == "qwen3.5:2b-q4_K_M"
    assert timeout <= 3
    assert len(calls) == 1

    def missing(request, timeout):
        raise HTTPError(request.full_url, 404, "not found", {}, BytesIO(b""))
    monkeypatch.setattr(galancito_local._opener, "open", missing)
    assert galancito_local.installed_model_status("qwen3.5:2b-q4_K_M") is False

    monkeypatch.setattr(galancito_local._opener, "open",
                        lambda *_args, **_kw: (_ for _ in ()).throw(URLError("offline")))
    assert galancito_local.installed_model_status("qwen3.5:2b-q4_K_M") is None


def test_training_thinking_budget_is_honored_without_changing_live_chat(monkeypatch):
    from types import SimpleNamespace
    cfg = SimpleNamespace(galancito_local_model="qwen3.5:2b-q4_K_M",
                          galancito_num_ctx=2048, galancito_num_predict=128,
                          galancito_num_thread=2, galancito_keep_alive="2m",
                          galancito_timeout_seconds=45)
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, length):
            return json.dumps({"message": {"content": "Resultado: 1\\nExplicación: Un registro."}},
                              ensure_ascii=False).encode("utf-8")

    def mocked_open(request, timeout):
        calls.append((json.loads(request.data), timeout))
        return Response()

    monkeypatch.setattr(galancito_local._opener, "open", mocked_open)
    text = galancito_local.generate_training_text("Sistema", "Caso", 23, cfg, thinking=True)
    assert text.startswith("Resultado: 1")
    assert calls[-1][0]["options"]["num_predict"] == 128
    assert calls[-1][0]["options"]["num_thread"] == 2
    assert calls[-1][0]["think"] is True

    galancito_local._generate("Sistema", "Caso", 500, cfg, thinking=True)
    assert calls[-1][0]["options"]["num_predict"] == 512
