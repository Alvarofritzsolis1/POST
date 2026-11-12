"""Private warm Calc service. Run with Debian /usr/bin/python3 (python3-uno).

One office process, one conversion at a time, no public ingress. Masters never
pass through storeAsURL: only disposable copies are recalculated/exported.
"""
import base64
import hmac
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import uno
from com.sun.star.beans import PropertyValue

SECRET = os.environ.get("JAVIERA_CALC_SECRET", "")
if len(SECRET) < 32:
    raise SystemExit("JAVIERA_CALC_SECRET must contain at least 32 characters")
LOCK = threading.Lock()
PROCESS = None
DESKTOP = None
PROFILE = tempfile.TemporaryDirectory(prefix="galant-calc-profile-")


def prop(name, value):
    p = PropertyValue(); p.Name = name; p.Value = value; return p


def desktop():
    global PROCESS, DESKTOP
    if PROCESS is not None and PROCESS.poll() is None and DESKTOP is not None:
        return DESKTOP
    PROCESS = subprocess.Popen([shutil.which("soffice"),
        "-env:UserInstallation=" + Path(PROFILE.name).as_uri(), "--headless", "--norestore", "--nodefault",
        "--accept=socket,host=127.0.0.1,port=2002;urp;StarOffice.ServiceManager"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    context = uno.getComponentContext()
    resolver = context.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", context)
    deadline = time.monotonic() + 25
    while True:
        try:
            remote = resolver.resolve("uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext")
            DESKTOP = remote.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", remote)
            return DESKTOP
        except Exception:
            if time.monotonic() >= deadline: raise RuntimeError("Calc no está disponible") from None
            time.sleep(0.15)


def convert(data):
    started = time.perf_counter(); raw = base64.b64decode(data["xlsx"], validate=True)
    if len(raw) > 12 * 1024 * 1024: raise ValueError("XLSX demasiado grande")
    with tempfile.TemporaryDirectory(prefix="galant-calc-job-") as tmp:
        folder = Path(tmp); source = folder / "source.xlsx"; source.write_bytes(raw)
        doc = desktop().loadComponentFromURL(source.as_uri(), "_blank", 0, (
            prop("Hidden", True), prop("ReadOnly", False), prop("MacroExecutionMode", 0),
            prop("UpdateDocMode", 0), prop("AskDocInfoOnSave", False)))
        if doc is None: raise RuntimeError("Calc no pudo abrir el libro")
        try:
            doc.enableAutomaticCalculation(True); doc.calculateAll()
            calculated = folder / "calculated.xlsx"
            doc.storeToURL(calculated.as_uri(), (prop("FilterName", "Calc MS Excel 2007 XML"), prop("Overwrite", True)))
            sheets = doc.getSheets(); wanted = data.get("sheets", [])
            names = {n.strip().casefold(): n for n in sheets.getElementNames()}
            if any(n.strip().casefold() not in names for n in wanted): raise ValueError("Hoja no encontrada")
            if wanted:
                chosen = {names[n.strip().casefold()] for n in wanted}
                for n in chosen: sheets.getByName(n).IsVisible = True
                for n in sheets.getElementNames():
                    if n not in chosen:
                        sheets.getByName(n).IsVisible = False
                        sheets.getByName(n).setPrintAreas(())
                doc.getCurrentController().setActiveSheet(sheets.getByName(next(iter(chosen))))
                selection = doc.createInstance('com.sun.star.sheet.SheetCellRanges')
                areas = []
                for n in chosen:
                    sheet = sheets.getByName(n); ranges = sheet.getPrintAreas()
                    if ranges: areas.extend(ranges)
                    else:
                        cursor = sheet.createCursor(); cursor.gotoEndOfUsedArea(True)
                        areas.append(cursor.getRangeAddress())
                selection.addRangeAddresses(tuple(areas), True)
                doc.getCurrentController().select(selection)
            result = {"calculated": base64.b64encode(calculated.read_bytes()).decode()}
            if wanted:
                pdf = folder / "document.pdf"
                doc.storeToURL(pdf.as_uri(), (prop("FilterName", "calc_pdf_Export"), prop("Overwrite", True),
                    prop('Selection', selection), prop('FilterData', (prop('Selection', selection),))))
                if pdf.stat().st_size > 18 * 1024 * 1024: raise ValueError("PDF demasiado grande")
                result["pdf"] = base64.b64encode(pdf.read_bytes()).decode()
            result["engine_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return result
        finally:
            doc.close(True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log names, workbook bytes, tokens or request bodies.

    def do_GET(self):
        if self.path != "/health": self.send_error(404); return
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"engine":"LibreOffice Calc","ready":true}')

    def do_POST(self):
        if self.path != "/convert": self.send_error(404); return
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + SECRET):
            self.send_error(403); return
        try:size = int(self.headers.get("Content-Length", "0"))
        except ValueError:self.send_error(400);return
        if not 0 < size <= 17 * 1024 * 1024: self.send_error(413); return
        if not LOCK.acquire(timeout=15): self.send_error(503, "Motor ocupado"); return
        def cancel_job():
            global DESKTOP
            if PROCESS is not None and PROCESS.poll() is None:
                try:os.killpg(PROCESS.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            DESKTOP = None
        deadline = threading.Timer(70,cancel_job);deadline.daemon=True;deadline.start()
        try:
            data = json.loads(self.rfile.read(size)); result = convert(data)
            body = json.dumps(result).encode(); self.send_response(200)
        except Exception:
            body = b'{"error":"Calc no pudo completar la conversion"}'; self.send_response(422)
        finally:
            deadline.cancel()
            LOCK.release()
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    desktop()
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
