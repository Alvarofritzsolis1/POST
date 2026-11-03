#!/usr/bin/env python3
"""Smoke test contra una instancia QA sintética y aislada; jamás producción."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request


class Account:
    def __init__(self,base):
        self.base=base.rstrip("/")
        self.cookies=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def call(self,path,body=None):
        payload=None if body is None else json.dumps(body).encode()
        headers={"Content-Type":"application/json"}
        csrf=next((cookie.value for cookie in self.cookies if cookie.name=="galant_post_csrf"),None)
        if body is not None and csrf:
            headers["X-CSRF-Token"]=csrf
        request=urllib.request.Request(self.base+"/api/v1"+path,data=payload,headers=headers)
        with self.opener.open(request,timeout=20) as response:
            return json.load(response)

    def login(self,email,password):
        return self.call("/auth/login",{"email":email,"password":password})


def verify(a,b):
    left=a.call("/auth/me")
    right=b.call("/auth/me")
    assert left["org_id"]==right["org_id"],"Usuarios aislados por org_id"
    sites=a.call("/ops/sites")
    assert len(sites)>=3
    site=next((s for s in sites if s["name"]=="Concepción"),sites[0])
    qs="?site_id="+site["id"]
    names=a.call("/ops/contractors"+qs)
    record=next((r for r in names if r["name"]=="QA CONTRACTOR TEST"),None)
    if record is None:
        record=a.call("/ops/contractors",{
            "site_id":site["id"],"name":"QA CONTRACTOR TEST",
            "nature":"with_workers","historical_code":"CT","frequency":"fixed"
        })
    assert any(r["id"]==record["id"] for r in b.call("/ops/contractors"+qs))
    a.call("/control/reviews",{
        "association_id":record["id"],"period":"2026-09",
        "kind":"cotizaciones","status":"approved",
        "notes":"Aprobación manual sintética sin PDF"
    })
    matrix=b.call("/control/matrix?site_id="+site["id"]+"&period=2026-09")
    company=next(c for c in matrix["contractors"] if c["association_id"]==record["id"])
    assert next(r for r in company["requirements"] if r["kind"]=="cotizaciones")["state"]=="approved"
    assert a.call("/control/reports/overview?period=2026-09")["totals"]["unique_companies"]>=1
    return record["id"],site["id"]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="http://127.0.0.1:18612")
    parser.add_argument("--password",default=os.environ.get("QA_SMOKE_PASSWORD"))
    parser.add_argument("--verify-only",action="store_true")
    args=parser.parse_args()
    if not args.password:
        parser.error("Configura QA_SMOKE_PASSWORD")
    if args.url not in ("http://127.0.0.1:18612","http://localhost:18612"):
        parser.error("Solo QA localhost:18612, nunca producción")
    a,b=Account(args.url),Account(args.url)
    for attempt in range(45):
        try:
            health=a.call("/health")
            if health["status"]=="ok":break
        except (urllib.error.URLError,TimeoutError):
            time.sleep(3)
    else:
        raise RuntimeError("QA no pasó healthcheck")
    a.login("qa-admin@example.test",args.password)
    b.login("qa-reviewer@example.test",args.password)
    if args.verify_only:
        left=a.call("/auth/me")
        right=b.call("/auth/me")
        assert left["org_id"]==right["org_id"]
        sites=a.call("/ops/sites")
        target=next((x for x in sites if x["name"]=="Concepción"),sites[0])
        result=b.call("/control/matrix?site_id="+target["id"]+"&period=2026-09")
        company=next(x for x in result["contractors"] if x["name"]=="QA CONTRACTOR TEST")
        assert next(x for x in company["requirements"] if x["kind"]=="cotizaciones")["state"]=="approved"
        # Todos los módulos operativos deben persistir, no solo documentos.
        controls=a.call("/control/contributions?period=2026-09&site_id="+target["id"])
        assert any(row["missing_days"]==1 and
                   float(row["retention_suggested"])==4950
                   for row in controls), "Días/retenciones no persistieron"
        assert any(row["subject_key"]=="independent" and row["payment_confirmed"]
                   for row in controls), "Pago manual CI no persistió"
        contracts=a.call("/control/admin/contracts?site_id="+target["id"])
        assert any(row["end_date"]=="2026-11-30" for row in contracts), "Anexo no persistió"
        tasks=a.call("/control/admin/tasks?site_id="+target["id"])
        assert any(row["kind"]=="review_continuity" for row in tasks), "Tarea administrativa no persistió"
        print("QA Docker restart persistence verified: documentos, CT/CI, anexos y tareas")
    else:
        verify(a,b)
        print("QA two-account shared state verified")


if __name__=="__main__":
    main()
