#!/usr/bin/env python3
"""Run the same synthetic reference checks on this release or a checkout before the intake update."""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / "apps" / "backend"


def load_evaluator_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def adapt_reference():
    from app import galancito_intake, galancito_memory, galancito_contact_profile
    from app.galancito_contact_email import remember_shared_email, redact_email_for_intake
    from app.galancito_phone import remember_shared_phone, redact_mobile_for_intake

    # The question rubric is identical in both versions. The old reply still
    # receives exactly the arguments it received before this release.
    source = BACKEND / "app" / "galancito_intake.py"
    parser = next(node for node in ast.parse(source.read_text()).body
                  if isinstance(node, ast.FunctionDef) and node.name == "intake_question_fields")
    exec(compile(ast.Module(body=[parser], type_ignores=[]), str(source), "exec"), vars(galancito_intake))
    previous_reply = galancito_intake.small_talk_reply
    galancito_intake.small_talk_reply = lambda message, prior: previous_reply(message)

    def capture(db, lead, message, prior, *, at, remote_id):
        # Same calls and order as the 20.9.30 webhook.
        saved_phone = remember_shared_phone(lead, message, prior, at=at)
        saved_email = remember_shared_email(lead, message, prior, at=at)
        fields = [name for name, saved in (("contact_phone", saved_phone), ("contact_email", saved_email)) if saved]
        galancito_memory.note_profile_sources(lead, fields, source="message", at=at, remote_id=remote_id)
        return saved_phone, saved_email

    galancito_memory.capture_voluntary_contact = capture
    galancito_memory.professional_message = lambda body: redact_email_for_intake(redact_mobile_for_intake(body))

    previous_profile = galancito_contact_profile.contact_profile

    def profile(lead):
        return {**previous_profile(lead), "contact_state": (
            "canal_voluntario" if lead.contact_phone or lead.contact_email else "solo_messenger")}

    galancito_contact_profile.contact_profile = profile
    app_dir = BACKEND / "app"
    evaluator = load_evaluator_module("app.max_power_practice", app_dir / "max_power_practice.py")
    load_evaluator_module("app.max_power_messenger", app_dir / "max_power_messenger.py")
    return evaluator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, help="Path to a checkout of GALANT 20.9.30 or 20.9.31")
    parser.add_argument("--output", type=Path, help="Write evaluation metadata to this JSON file")
    args = parser.parse_args()
    sys.path.insert(0, str(args.reference / "apps" / "backend" if args.reference else BACKEND))
    import app.main  # registers ORM models
    if args.reference:
        from app.version import VERSION
        if VERSION not in {"20.9.30-rc1", "20.9.31-rc1"}:
            parser.error("--reference debe apuntar a GALANT 20.9.30-rc1 o 20.9.31-rc1")
        evaluator = adapt_reference()
    else:
        from app import max_power_practice as evaluator
    result = json.dumps(evaluator.run_practice(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + "\n")
    else:
        print(result)


if __name__ == "__main__":
    main()
