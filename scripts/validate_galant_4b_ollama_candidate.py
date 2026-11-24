#!/usr/bin/env python3
"""Exercise immutable candidate application and rollback on isolated Ollama only.

The separately converted/imported GGUF candidate must be present with an exact
signed provenance manifest. Never overwrite a production or base tag. This tool
does not import unverified weights, publish a model or enable production.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from time import monotonic
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from galancito_4b_validation import evaluate_conversations, paired_report
from max_power_4b_slot import CONTROL, acquire_slot, release_slot, read_json
from time import time

URL = "http://galancito-training-ollama:11434"
BASE = "qwen3.5:4b-q4_K_M"
SHADOW = "galant-4b-shadow:current"

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError("Unexpected isolated Ollama redirect")

OPENER = build_opener(ProxyHandler({}),NoRedirect())


def api(path, payload=None):
    request = Request(URL+path,data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type":"application/json"})
    with OPENER.open(request,timeout=240) as response:
        raw = response.read(2_000_001)
        if len(raw)>2_000_000:
            raise RuntimeError("Unexpected Ollama response size")
        return json.loads(raw) if raw else {}


def validate_manifest(manifest, report_bytes, public_key):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    fields = {"base_revision","base_digest","candidate_tag","candidate_digest",
              "adapter_sha256","gguf_sha256","pilot_report_sha256","signature_ed25519"}
    if set(manifest)!=fields:
        raise ValueError("Incomplete conversion provenance")
    statement = dict(manifest)
    signature = statement.pop("signature_ed25519")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(bytes.fromhex(signature),
            json.dumps(statement,sort_keys=True,separators=(",",":")).encode())
    except (ValueError,TypeError,InvalidSignature) as exc:
        raise ValueError("Untrusted conversion provenance") from exc
    for key in ("base_digest","candidate_digest","adapter_sha256","gguf_sha256","pilot_report_sha256"):
        if not isinstance(statement[key],str) or not re.fullmatch(r"[0-9a-f]{64}",statement[key]):
            raise ValueError("Invalid exact SHA-256 digest")
    if not re.fullmatch(r"galant-4b-candidate:[0-9a-f]{12,64}",statement["candidate_tag"]):
        raise ValueError("Candidate tag is not immutable/allowlisted")
    if statement["base_digest"]==statement["candidate_digest"]:
        raise ValueError("Candidate is identical to base manifest")
    if hashlib.sha256(report_bytes).hexdigest()!=statement["pilot_report_sha256"]:
        raise ValueError("Pilot report digest mismatch")
    report = json.loads(report_bytes)
    if (report.get("model")!="Qwen/Qwen3.5-4B" or report.get("status")!="completed"
            or report.get("candidate_status")!="lab_candidate"
            or report.get("base_revision")!=statement["base_revision"]
            or report.get("latest_adapter_sha256")!=statement["adapter_sha256"]
            or not (report.get("conversation_validation") or {}).get("rollback_output_equal")):
        raise ValueError("No matching validated 4B laboratory candidate")
    return statement


def tag_digest(name):
    rows = api("/api/tags").get("models",[])
    return next((r.get("digest","").removeprefix("sha256:") for r in rows if r.get("name")==name),None)


def switch(source, expected):
    if source==SHADOW or tag_digest(source)!=expected:
        raise RuntimeError("Immutable source digest mismatch")
    if tag_digest(SHADOW):
        api("/api/generate",{"model":SHADOW,"keep_alive":0,"stream":False})
    api("/api/copy",{"source":source,"destination":SHADOW})
    if tag_digest(SHADOW)!=expected:
        raise RuntimeError("Shadow switch not confirmed")


def generate(history):
    started = monotonic()
    result = api("/api/chat",{"model":SHADOW,"messages":history,"stream":False,
        "think":False,"keep_alive":"2m","options":{"num_ctx":2048,"num_predict":96,"temperature":0,"seed":42}})
    if result.get("model")!=SHADOW or not result.get("done"):
        raise RuntimeError("Unexpected shadow runtime")
    answer = result.get("message",{}).get("content")
    if not isinstance(answer,str) or not answer.strip():
        raise RuntimeError("Empty shadow response")
    return answer,monotonic()-started


def run():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--pilot-report",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args = p.parse_args()
    manifest = validate_manifest(json.loads(args.manifest.read_text()),args.pilot_report.read_bytes(),
                                 os.environ.get("GALANT_4B_RELEASE_PUBLIC_KEY",""))
    # Must run as an isolated maintenance test with MAX POWER stopped.
    # The base and immutable candidate tags are never written.
    if tag_digest(BASE)!=manifest["base_digest"] or tag_digest(manifest["candidate_tag"])!=manifest["candidate_digest"]:
        raise SystemExit("Isolated model digests not confirmed")
    result = {"production_verified":False,"production_promoted":False,"shadow_validated":False}
    baseline_probe = None
    try:
        switch(BASE,manifest["base_digest"])
        baseline = evaluate_conversations(generate)
        baseline_probe, _ = generate([{"role":"user","content":"¿Qué significa cuadrilla?"}])
        switch(manifest["candidate_tag"],manifest["candidate_digest"])
        candidate = evaluate_conversations(generate)
        result["comparison"] = paired_report(baseline,candidate)
    finally:
        try:
            switch(BASE,manifest["base_digest"])
            result["rollback_digest_verified"] = tag_digest(SHADOW)==manifest["base_digest"]
            result["base_unchanged"] = tag_digest(BASE)==manifest["base_digest"]
            restored, _ = generate([{"role":"user","content":"¿Qué significa cuadrilla?"}])
            result["rollback_output_equal"] = baseline_probe is not None and restored == baseline_probe
        except Exception as exc:
            result["rollback_error_type"] = type(exc).__name__
        result["shadow_validated"] = bool(result.get("comparison",{}).get("lab_pass")
            and result.get("rollback_digest_verified") and result.get("base_unchanged")
            and result.get("rollback_output_equal"))
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result,indent=2,allow_nan=False))
        temporary.replace(args.output)
    return 0 if result["shadow_validated"] else 1


def main():
    fd = acquire_slot()
    if fd is None:
        raise SystemExit("4B engine busy; isolated maintenance unavailable")
    try:
        intent = read_json(CONTROL / "intent.json")
        if (intent.get("enabled") is not False or type(intent.get("at")) not in (int,float)
                or not 0 <= time()-intent["at"] <= 20):
            raise SystemExit("MAX POWER OFF must be confirmed by the live controller")
        return run()
    finally:
        release_slot(fd)


if __name__=="__main__":
    raise SystemExit(main())
