#!/usr/bin/env python3
"""Read-only, two-account soak test. Default: 24 continuous hours.

Run ONLY against an authorized staging environment with synthetic data.
Credentials are read from environment variables; no PII is printed or persisted.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Account:
    def __init__(self, base: str, email: str, password: str):
        self.base = base.rstrip("/")
        self.email = email
        self.password = password
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path: str, data: dict | None = None) -> dict:
        url = self.base + "/api/v1" + path
        body = None if data is None else json.dumps(data).encode("utf-8")
        headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Una sesión normal dura varias horas. Renovar solo si expiró,
            # para no disparar el limitador de inicios de sesión.
            if exc.code != 401 or path == "/auth/login":
                raise
            self.login()
            with self.opener.open(req, timeout=20) as response:
                return json.load(response)

    def login(self):
        return self.request("/auth/login", {"email": self.email, "password": self.password})


def snapshot(account: Account, period: str) -> dict:
    profile = account.request("/auth/me")
    sites = account.request("/ops/sites")
    matrix = {}
    for site in sites:
        params = urllib.parse.urlencode({"site_id": site["id"], "period": period})
        result = account.request("/control/matrix?" + params)
        matrix[site["id"]] = sorted(
            (row["association_id"],
             sorted((r["kind"], r["state"], r["applicable"]) for r in row["requirements"]))
            for row in result["contractors"])
    return {"org_id": profile["org_id"], "sites": sorted(s["id"] for s in sites),
            "matrix": matrix}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Authorized staging HTTPS base URL")
    parser.add_argument("--period", default="2026-09")
    parser.add_argument("--duration-seconds", type=int, default=86400)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--output", default="soak-24h-summary.json")
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.interval_seconds <= 0:
        parser.error("Duración e intervalo deben ser positivos")
    secrets = [os.getenv(k, "") for k in
               ("GALANT_SOAK_EMAIL_A", "GALANT_SOAK_PASSWORD_A",
                "GALANT_SOAK_EMAIL_B", "GALANT_SOAK_PASSWORD_B")]
    if not all(secrets):
        parser.error("Configura GALANT_SOAK_EMAIL_A/PASSWORD_A y GALANT_SOAK_EMAIL_B/PASSWORD_B")
    if not args.url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        parser.error("Usa HTTPS o un túnel privado al localhost")
    first = Account(args.url, secrets[0], secrets[1])
    second = Account(args.url, secrets[2], secrets[3])
    os.umask(0o077)
    started_at = utc_now()
    start = time.monotonic()
    samples, failures, mismatches = 0, [], 0
    destination = Path(args.output).expanduser()

    def checkpoint(result: str) -> dict:
        now = utc_now()
        report = {
            "started_at": started_at, "last_checked_at": now,
            "completed_at": now if result != "RUNNING" else None,
            "requested_duration_seconds": args.duration_seconds,
            "elapsed_seconds": round(time.monotonic() - start),
            "period": args.period, "successful_samples": samples,
            "failure_count": len(failures), "mismatches": mismatches,
            "failures": failures[-60:], "result": result,
        }
        # Actualización atómica; un corte nunca deja un JSON parcial.
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        return report

    checkpoint("RUNNING")
    try:
        first.login()
        second.login()
    except Exception as exc:
        failures.append({"time": utc_now(), "error_type": type(exc).__name__,
                         "detail": str(exc)[:160]})
        checkpoint("FAIL")
        return 1
    while True:
        try:
            health = first.request("/health")
            a = snapshot(first, args.period)
            b = snapshot(second, args.period)
            if health.get("status") != "ok" or a["org_id"] != b["org_id"]:
                raise RuntimeError("La salud o el org_id de las cuentas no coincide")
            if a["sites"] != b["sites"] or a["matrix"] != b["matrix"]:
                # Releer evita falso positivo por una edición concurrente.
                a = snapshot(first, args.period)
                b = snapshot(second, args.period)
                if a["matrix"] != b["matrix"]:
                    mismatches += 1
                    raise RuntimeError("Inconsistencia entre los dos usuarios")
            samples += 1
        except Exception as exc:
            failures.append({"time": utc_now(), "error_type": type(exc).__name__,
                             "detail": str(exc)[:160]})
        checkpoint("RUNNING")
        if time.monotonic() - start >= args.duration_seconds:
            break
        time.sleep(min(args.interval_seconds, max(
            0, args.duration_seconds - (time.monotonic() - start)
        )))
    report = checkpoint("PASS" if samples > 0 and not failures else "FAIL")
    print(f"QA soak result: {report['result']}, elapsed={report['elapsed_seconds']}s, "
          f"samples={samples}, failures={len(failures)}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
