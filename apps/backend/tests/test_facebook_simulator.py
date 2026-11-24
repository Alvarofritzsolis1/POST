"""Interactive simulation must use the Messenger flow without touching its live stores."""
from sqlalchemy import func, select

from app.config import settings
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_knowledge_models import AssistantRun
from test_ai_control_center import ai_env, signin

BASE = "/api/v1/admin/ai/messenger-simulator"


def test_simulator_is_admin_scoped_and_retains_only_its_test_profile(ai_env, monkeypatch):
    client = ai_env["client"]
    admin = signin(client)
    def unexpected(*args, **kwargs):
        raise AssertionError("A simulation must never contact Meta")
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.graph_sender_action", unexpected)

    def send(message, state=None):
        response = client.post(BASE + "/turn", headers=admin, json={"message": message, "state": state})
        assert response.status_code == 200, response.text
        return response.json()

    first = send("Vi una postulacion de trabajo")
    assert first["reply"].startswith("Claro, te ayudo.")
    assert first["source"] == "local" and first["intent"] == "apply"
    assert first["checks"]["safe"] and not first["profile"]["specialty"]

    # Start a separate conversation and exercise real memory/normalization.
    declared = send("Soy carpintero y trabajo en Coronel. Puedo ir con dos maestros.")
    assert declared["profile"]["specialty"] == "Carpintería"
    assert declared["profile"]["workers"] == 3
    correction = send("Corrijo: puedo ir con cuatro maestros.", declared["state"])
    assert correction["profile"]["specialty"] == "Carpintería"
    assert correction["profile"]["workers"] == 5
    assert correction["field_states"]["workers"] == "corregido"
    assert "workers" in correction["changed_fields"]

    with ai_env["sessions"]() as db:
        for model in (FacebookLead, FacebookChatMessage, AssistantRun):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    other = signin(client, "outside")
    assert client.post(BASE + "/turn", headers=other, json={
        "message": "hola", "state": correction["state"],
    }).status_code == 403
    resident = signin(client, "resident")
    assert client.get(BASE, headers=resident).status_code == 403


def test_simulator_local_mode_checks_consent_and_never_calls_external_services(ai_env, monkeypatch):
    client = ai_env["client"]
    admin = signin(client)
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "openai")
    settings.cache_clear()
    calls = []
    def local(instructions, context, limit):
        calls.append(context)
        return "Los requisitos los confirma el equipo de cada obra."
    def unexpected(*args, **kwargs):
        raise AssertionError("Only the configured local model can receive a test message")
    monkeypatch.setattr("app.facebook_chat_worker.generate_local_text", local)
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.orchestrated_text", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    first = client.post(BASE + "/turn", headers=admin, json={
        "mode": "local", "message": "¿Cuáles son los requisitos para postular?",
    })
    assert first.status_code == 200, first.text
    assert first.json()["source"] == "consent" and not calls
    assert "IA local" in first.json()["reply"]
    second = client.post(BASE + "/turn", headers=admin, json={
        "mode": "local", "message": "Sí, autorizo", "state": first.json()["state"],
    })
    assert second.status_code == 200, second.text
    assert second.json()["source"] == "ai"
    assert calls and "requisitos para postular" in calls[0]


def test_simulator_short_application_answers_do_not_loop_or_invent_trade(ai_env, monkeypatch):
    from app.galancito_triage import ASK_APPLICATION_OWN, ASK_APPLICATION_ROLE_CLARIFY
    client = ai_env["client"]
    admin = signin(client)
    def unexpected(*args, **kwargs):
        raise AssertionError("Rules simulation must not call Meta or a model")
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.generate_local_text", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", unexpected)
    def send(message, state=None):
        response = client.post(BASE + "/turn", headers=admin, json={
            "mode": "rules", "message": message, "state": state})
        assert response.status_code == 200, response.text
        return response.json()
    first = send("Vi una postulación de trabajo")
    advert = send("de gasfiter", first["state"])
    assert not advert["profile"]["specialty"]
    ambiguous = send("solo", advert["state"])
    assert ambiguous["reply"].endswith(ASK_APPLICATION_ROLE_CLARIFY)
    assert ambiguous["profile"]["interest_type"] == "unknown"
    assert not ambiguous["profile"]["specialty"]
    personal = send("para mi", ambiguous["state"])
    assert personal["profile"]["interest_type"] == "employment"
    assert personal["reply"] == ASK_APPLICATION_OWN + "gasfitería?"
    assert not personal["profile"]["specialty"]
    confirmed = send("si", personal["state"])
    assert confirmed["profile"]["specialty"] == "Gasfitería"
    assert "comuna" in confirmed["reply"].lower()
    repeated = send("solo", ambiguous["state"])
    assert repeated["reply"] != ambiguous["reply"]
    assert repeated["profile"]["interest_type"] == "unknown"


def test_direct_qwen_uses_model_once_per_turn_and_keeps_semantic_facts(ai_env, monkeypatch):
    import json
    from app.galancito_local import last_timings
    from app.messenger_qwen_lab import MODEL
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED","true")
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL",MODEL)
    settings.cache_clear()
    client=ai_env["client"]
    admin=signin(client)
    calls=[]
    answers=[
        ("¿De qué oficio era el aviso?",[]),
        ("¿Quieres ofrecer servicios de gasfitería o buscar empleo?",[]),
        ("¿Tú haces trabajos de gasfitería?",[{"field":"interest_type","value":"service_offer","quote":"quiero ofrecer"}]),
        ("¿Trabajas solo o con más gente?",[{"field":"specialty","value":"Gasfitería","quote":"si"}]),
        ("¿Cuántas personas son en total?",[{"field":"team_available","value":True,"quote":"mas personas"}]),
        ("Te pregunto cuántos maestros trabajan contigo, incluyéndote. ¿Cuántos serían?",[]),
    ]
    def local(instructions,context,limit,**kw):
        assert kw["thinking"] is False and kw["output_tokens"]==220 and kw["json_schema"]
        calls.append(json.loads(context))
        last_timings.set({"response_model":MODEL,"local_model_calls":1,"eval_count":40,"ollama_total_ms":500})
        reply,updates=answers[len(calls)-1]
        return json.dumps({"reply":reply,"updates":updates},ensure_ascii=False)
    monkeypatch.setattr("app.messenger_qwen_lab.generate_local_text",local)
    state=None
    for message in ("vi una postulacion de instagram","gasfiter","quiero ofrecer","si","mas personas","no entiendio"):
        response=client.post(BASE+"/turn",headers=admin,json={"mode":"qwen","message":message,"state":state})
        assert response.status_code==200,response.text
        result=response.json()
        assert result["source"]=="qwen_direct" and result["model_evidence"]["calls"]==1
        state=result["state"]
    assert len(calls)==6
    assert calls[-1]["ficha_confirmada"]["team_available"] is True
    assert calls[-1]["ficha_confirmada"]["interest_type"]=="service_offer"
    assert result["profile"]["specialty"]=="Gasfitería"
    assert result["profile"].get("workers") is None
    assert "cuántos" in result["reply"]
    with ai_env["sessions"]() as db:
        assert db.scalar(select(func.count()).select_from(FacebookLead))==0


def test_direct_qwen_refuses_missing_or_unverified_model(ai_env,monkeypatch):
    from app.galancito_local import last_timings
    from app.messenger_qwen_lab import MODEL
    client=ai_env["client"]
    admin=signin(client)
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED","true")
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL","qwen3:1.7b")
    settings.cache_clear()
    assert client.post(BASE+"/turn",headers=admin,json={"mode":"qwen","message":"hola"}).status_code==409
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL",MODEL)
    settings.cache_clear()
    def wrong(*args,**kwargs):
        last_timings.set({"response_model":"qwen3:1.7b","local_model_calls":1,"eval_count":10})
        return '{"reply":"Hola","updates":[]}'
    monkeypatch.setattr("app.messenger_qwen_lab.generate_local_text",wrong)
    assert client.post(BASE+"/turn",headers=admin,json={"mode":"qwen","message":"hola"}).status_code==503


def test_direct_qwen_drops_unsubstantiated_fields():
    from app.messenger_qwen_lab import apply_updates
    result,changed=apply_updates({},[
        {"field":"workers","value":12,"quote":"somos doce"},
        {"field":"team_available","value":True,"quote":"mas personas"},
        {"field":"contact_phone","value":"555","quote":"mas personas"}],"mas personas")
    assert result=={"team_available":True}
    assert changed==["team_available"]


def test_qwen_diagnostics_show_rejections_without_claiming_learning():
    from app.messenger_qwen_lab import apply_updates
    evidence=[]
    result,changed=apply_updates({},[
        {"field":"workers","value":12,"quote":"somos doce"},
        {"field":"team_available","value":True,"quote":"mas personas"},
        {"field":"workers","value":1,"quote":"mas personas"}
    ],"mas personas",diagnostics=evidence)
    assert evidence[0]["reason"]=="missing_literal_evidence_or_invalid_field"
    assert any(x["status"]=="reverted" for x in evidence)
    assert result=={} and changed==[]


def test_qwen_exportable_diagnosis_includes_context_and_fixed_error(ai_env,monkeypatch):
    from app.messenger_qwen_lab import MODEL
    from app.galancito_local import last_timings
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED","true")
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL",MODEL)
    settings.cache_clear()
    client=ai_env["client"]
    admin=signin(client)
    def local(*args,**kwargs):
        last_timings.set({"response_model":MODEL,"local_model_calls":1,"eval_count":30})
        return '{"reply":"¿Qué oficio realizas?","updates":[]}'
    monkeypatch.setattr("app.messenger_qwen_lab.generate_local_text",local)
    first=client.post(BASE+"/turn",headers=admin,json={"mode":"qwen","message":"hola"}).json()
    second=client.post(BASE+"/turn",headers=admin,json={"mode":"qwen","message":"no entendi","state":first["state"]}).json()
    assert second["diagnostics"]["same_as_previous_reply"]
    assert second["diagnostics"]["history_included"]==2
    assert second["diagnostics"]["semantic_correctness"]=="not_independently_verified"
    def broken(*args,**kwargs):
        last_timings.set({"response_model":MODEL,"local_model_calls":1,"eval_count":220})
        return '{"reply":'
    monkeypatch.setattr("app.messenger_qwen_lab.generate_local_text",broken)
    failed=client.post(BASE+"/turn",headers=admin,json={"mode":"qwen","message":"hola"})
    assert failed.status_code==503 and failed.json()["detail"].startswith("invalid_or_truncated_json:")
