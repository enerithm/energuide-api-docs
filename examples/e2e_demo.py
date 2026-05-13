"""
EnerGuide API — End-to-End-Demo
================================

Spielt den kompletten Workflow gegen die Staging-Sandbox durch:

  1. Auth-Check (GET /health, GET /building-passes)
  2. Anforderungskatalog laden
  3. Pass + Projekt anlegen (One-Shot mit Beispielgebäude)
  4. Iteratives Patchen (Heizung nachreichen)
  5. Aktuellen Stand inspizieren (Step-Anzahl, LoD2-Quellen, polling auf bodatenLodLoaded)
  5b. LoD2-Boden-Elemente mit konkretem Typ versehen
  5c. Gebäude- und Typenschild-Foto hochladen
  6. Vollständigkeit prüfen — danach STOPP.
     Vorschau erstellen + Checkout dann manuell in der UI.

NICHT ausgeführt (per Default):
  - /certificates/drafts (Vorschau — aktivierbar via EG_RUN_DRAFT=1)
  - /final/checkout (Stripe-URL — aktivierbar via EG_RUN_CHECKOUT=1)
  - /final/submit (würde unechtes Zertifikat erzeugen)
  - PDF-Download (gibt es nur nach Submit)

Voraussetzungen:
  - Python 3.10+
  - pip install requests
  - export EG_TOKEN='egapi_...'
  - Optional: export EG_BASE='https://api.staging.enerithm.com/api/core/v1'
  - Optional: export EG_RUN_DRAFT=1      # Vorschau im Skript erstellen (kann lange dauern)
  - Optional: export EG_RUN_CHECKOUT=1   # zusätzlich Stripe-Checkout-URL erzeugen

Aufruf:
  python3 e2e_demo.py                                  # nur befüllen, Rest in der UI
  EG_RUN_DRAFT=1 python3 e2e_demo.py                   # mit Skript-Vorschau
  EG_RUN_DRAFT=1 EG_RUN_CHECKOUT=1 python3 e2e_demo.py # mit Vorschau + Stripe-URL
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("Bitte zuerst 'requests' installieren: pip install requests")


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

BASE = os.environ.get("EG_BASE", "https://api.staging.enerithm.com/api/core/v1")
TOKEN = os.environ.get("EG_TOKEN")

# Pfade zu den hochzuladenden Fotos. Default: neben diesem Skript.
# Override via EG_BUILDING_PIC und EG_NAMEPLATE_PIC.
_HERE = os.path.dirname(os.path.abspath(__file__))
BUILDING_PIC_PATH = os.environ.get(
    "EG_BUILDING_PIC", os.path.join(_HERE, "foto_gebaeude.png"))
NAMEPLATE_PIC_PATH = os.environ.get(
    "EG_NAMEPLATE_PIC", os.path.join(_HERE, "foto_typenschild.jpg"))

if not TOKEN:
    sys.exit("EG_TOKEN env-variable fehlt. Token im EnerGuide-Portal erzeugen.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eg-demo")


# ---------------------------------------------------------------------------
# Beispielgebäude — diese Adresse liegt in der LoD2-Datenbank, der Server
# ergänzt Bauteilflächen automatisch.
# ---------------------------------------------------------------------------

SAMPLE_STEPS: dict[str, Any] = {
    "reason_for_issue": {"value": "Vermietung-Verkauf"},
    "building_address": {
        "street": "Haydnstraße 59",
        "postalCode": "01309",
        "city": "Dresden",
        "federalState": "Sachsen",
        "country": "Deutschland",
    },
    "year_of_construction_building": {"value": "1995"},
    "renovation_after_construction": {"value": True},
    "renovation_measures": {
        "windows_done": True,
        "windows_year": "2025",
        "externalWall_done": True,
        "externalWall_year": "2025",
        "roof_done": True,
        "roof_year": "2025",
        "ceiling_done": False,
        "basementCeiling_done": False,
    },
    "number_of_residential_units": {"value": "1"},
    "part_of_residential_building": {"value": "Ganzes Gebäude"},
    "degree_of_attachment_residential_building": {"value": "freistehend"},
    "living_area": {"value": "199"},
    "number_of_heated_storeys": {"value": "2"},
    "mean_zone_height": {"value": "2.50"},
    "simplified_opaque_element": {
        "elements": [
            {"flaechenbezeichnung": "Tür", "flaeche": "2.00", "ausrichtung": "South"},
        ]
    },
    "construction_opaque_elements": {
        "typeOfExternalWall": "OtherSolidWallsOver20cm",
        "basementAvailable": False,
        "typeOfFloorToGround": "FloorToGroundBrick",
    },
    "simplified_roof": {"topFloorConverted": True},
    "simplified_roof_details": {
        "elements": [
            {"flaechenbezeichnung": "Steildach", "flaeche": "134.19",
             "ausrichtung": "SouthWest", "neigung": "Incline_30"}
        ]
    },
    "roof_construction": {"roofIsMassiveConstruction": False},
    "transparent_share": {"percentage": 0.25, "allowCustom": True},
    "simplified_transparent_element": {
        "elements": [
            {"flaechenbezeichnung": "Dachfenster", "ausrichtung": "SouthWest",
             "neigung": "Incline_30", "flaeche": 5},
        ]
    },
    "construction_transparent_element": {
        "windowType1": "TripleGlazing",
        "hasAdditionalWindows": False,
    },
    "heating_emission_type": {"heatingEmission1": "Radiators"},
    "heating_generator_details_step": {
        "hydraulicBalance": False,
        "separatedHeatingCircuits": False,
        "heatingDistributionIsDoublePipeNetwork": True,
        "heatingDistributionIsInsideThermalHull": True,
        "temperaturesKnown": False,
        "insideThermalHull": True,
    },
    "dhw_supply_demand": {"distributionType": "zentral"},
    "dhw_generator_available": {"value": False, "DHWStorage": False, "hasCirculation": False},
    "cooling_system_basic": {"isBuildingCooled": False},
    "ventilation_system_basic": {"isWindowVentilationOnly": True},
    "renewable_energy_basic": {"usesRenewableEnergy": False},
    # building_pictures wird NICHT hier vorbelegt — die Bilder werden in
    # Schritt 5c per Upload-Endpoint gesetzt (siehe _upload_picture).
}

# Heizung wird absichtlich erst per PATCH nachgereicht, um den iterativen
# Editier-Workflow zu zeigen.
HEATING_PATCH: dict[str, Any] = {
    "heating_generator_data_step": {
        "heatingGenerators": [
            {"type": "Condensing_Boiler", "energyCarrier": "Gas",
             "coverage": "1", "yearOfConstruction": "2020"}
        ],
        "hasHeatingStorage": False,
    }
}


# ---------------------------------------------------------------------------
# HTTP-Helfer
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
})


class ApiError(Exception):
    def __init__(self, method: str, path: str, status: int, body: Any) -> None:
        self.method, self.path, self.status, self.body = method, path, status, body
        message = f"{method} {path} -> {status}"
        if isinstance(body, dict) and "error" in body:
            err = body["error"]
            message += f": {err.get('code')} — {err.get('message')}"
            for d in err.get("details", []) or []:
                message += f"\n    {d.get('path')}: {d.get('message')}"
        super().__init__(message)


def call(method: str, path: str, *, json_body: Any = None, params: dict | None = None) -> Any:
    """API-Call. Wirft ApiError bei 4xx/5xx. Gibt das JSON-Body-Dict zurück."""
    url = BASE + path
    log.info("→ %s %s", method, path + (f"?{params}" if params else ""))
    r = session.request(method, url, json=json_body, params=params, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = {"_raw_status": r.status_code, "_raw_text": r.text[:200]}
    if not (200 <= r.status_code < 300):
        raise ApiError(method, path, r.status_code, body)
    log.info("    %s %s", r.status_code, _short(body))
    return body


def _short(obj: Any, limit: int = 120) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "…"


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def step_1_auth_check() -> None:
    log.info("=== Schritt 1: Auth-Check ===")
    health = call("GET", "/health")
    assert health.get("status") == "ok", "Health-Check fehlgeschlagen"
    passes = call("GET", "/building-passes")
    log.info("    %d existierende Pässe sichtbar", len(passes["data"]))


def step_2_load_catalog(cert_type: str = "demand") -> dict:
    log.info("=== Schritt 2: Anforderungskatalog laden (%s) ===", cert_type)
    body = call("GET", "/requirements/catalog", params={"type": cert_type})
    catalog = body["data"]
    log.info("    %d Anforderungen, %d Kategorien",
             catalog["totalRequirements"], len(catalog["categories"]))
    return catalog


def step_3_create_pass(cert_type: str = "demand") -> tuple[int, int]:
    log.info("=== Schritt 3: Pass + Projekt anlegen ===")
    payload = {
        "passName": f"E2E-Demo Haydnstr 59 ({cert_type})",
        "name": f"Energieausweis {cert_type}",
        "certificateTypeSelection": cert_type,
        "data": {"steps": SAMPLE_STEPS},
    }
    body = call("POST", "/building-passes/projects", json_body=payload)
    pass_id = body["data"]["passId"]
    project_id = body["data"]["projectId"]
    log.info("    angelegt: passId=%s  projectId=%s", pass_id, project_id)
    return pass_id, project_id


def step_4_patch_heating(pass_id: int) -> None:
    log.info("=== Schritt 4: Heizung per PATCH nachreichen ===")
    call("PATCH", f"/building-passes/{pass_id}/projects",
         json_body={"data": {"steps": HEATING_PATCH}})


def step_5_inspect_state(pass_id: int, wait_for_lod2: bool = True,
                         max_wait_seconds: int = 30) -> None:
    log.info("=== Schritt 5: Aktuellen Projekt-Stand abrufen ===")

    # LoD2-Loading läuft asynchron im Backend. Wir pollen, bis das Flag
    # bodatenLodLoaded=true wird (oder Timeout).
    if wait_for_lod2:
        deadline = time.time() + max_wait_seconds
        attempt = 0
        while True:
            attempt += 1
            body = call("GET", f"/building-passes/{pass_id}/projects")
            steps = body["data"]["data"]["steps"]
            opaque = steps.get("simplified_opaque_element", {}) or {}
            loaded = opaque.get("bodatenLodLoaded")
            elements = opaque.get("elements", []) or []
            lod2_count = sum(1 for el in elements if el.get("source") == "lod2")
            log.info("    LoD2-Status (Versuch %d): bodatenLodLoaded=%s, "
                     "lod2-Elemente=%d", attempt, loaded, lod2_count)
            if loaded is True or time.time() > deadline:
                break
            time.sleep(2)
    else:
        body = call("GET", f"/building-passes/{pass_id}/projects")
        steps = body["data"]["data"]["steps"]

    log.info("    %d Steps im Projekt", len(steps))

    opaque = steps.get("simplified_opaque_element", {}) or {}
    elements = opaque.get("elements", []) or []
    by_source: dict[str, int] = {}
    for el in elements:
        by_source[el.get("source", "?")] = by_source.get(el.get("source", "?"), 0) + 1
    log.info("    Bauteile: %d gesamt — Quellen: %s", len(elements), by_source)


def step_5b_fix_lod2_floor_type(pass_id: int) -> None:
    """LoD2 lädt Bauteile mit typ='NotSet'. Für Außenwände/Decken ist das
    unkritisch, weil ihr Konstruktionstyp ohnehin global aus
    construction_opaque_elements (typeOfExternalWall, typeOfBasementCeiling)
    übernommen wird. Für Boden-Elemente greift dieser globale Mechanismus
    aber nicht — typ='NotSet' bleibt undefiniert und die Validierung lehnt ab.
    Pattern: GET → mutieren → komplettes elements-Array zurück-PATCHen
    (Array-PATCH = Replace, kein Merge)."""
    log.info("=== Schritt 5b: LoD2-Boden-Typen korrigieren ===")
    body = call("GET", f"/building-passes/{pass_id}/projects")
    opaque = body["data"]["data"]["steps"].get("simplified_opaque_element", {})
    elements = opaque.get("elements", [])

    floor_typ = "BE_LowerCompletionToSoil"   # "Floor to Ground" / Bodenplatte
    changed = 0
    for el in elements:
        # LoD2 liefert Boden-Elemente als "Boden", "Boden 9", "Boden 10", …
        bezeichnung = el.get("flaechenbezeichnung") or ""
        if bezeichnung.startswith("Boden") and el.get("typ") in (None, "NotSet"):
            el["typ"] = floor_typ
            changed += 1
            log.info("    %s (source=%s, %sm²) → typ=%s",
                     bezeichnung, el.get("source", "?"), el.get("flaeche"), floor_typ)

    if not changed:
        log.info("    Kein Boden-Element ohne typ — nichts zu tun")
        # Verifikation auch dann, damit wir den finalen Stand klar sehen.
        _log_floor_state(pass_id, "Verifikation (kein Patch nötig)")
        return

    # Komplettes Elements-Array zurück patchen (Array-PATCH = Replace)
    call("PATCH", f"/building-passes/{pass_id}/projects",
         json_body={"data": {"steps": {
             "simplified_opaque_element": {"elements": elements}
         }}})
    log.info("    %d Boden-Element(e) aktualisiert", changed)

    # Verifikation: nochmal lesen und alle Boden-Elemente loggen
    _log_floor_state(pass_id, "Verifikation NACH dem Patch")


def _log_floor_state(pass_id: int, label: str) -> None:
    """Liest den aktuellen Pass und loggt jedes Boden-Element samt typ."""
    body = call("GET", f"/building-passes/{pass_id}/projects")
    elements = (body["data"]["data"]["steps"]
                .get("simplified_opaque_element", {}).get("elements", []))
    boden = [el for el in elements
             if (el.get("flaechenbezeichnung") or "").startswith("Boden")]
    log.info("    [%s] %d Boden-Element(e):", label, len(boden))
    for el in boden:
        log.info("      • %s | source=%s | flaeche=%s | typ=%s",
                 el.get("flaechenbezeichnung"),
                 el.get("source"),
                 el.get("flaeche"),
                 el.get("typ"))


def _upload_picture(pass_id: int, field_key: str, file_path: str) -> dict:
    """Upload eines Fotos via multipart/form-data. Form-Feld heißt 'file'.
    Der Server validiert den MIME-Type strikt auf image/* — wir setzen ihn
    explizit aus der Dateiendung. Der Server mappt das Bild automatisch ins
    building_pictures-Step; ein nachträglicher PATCH ist nicht nötig."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Foto nicht gefunden: {file_path}")
    filename = os.path.basename(file_path)
    mime, _ = mimetypes.guess_type(filename)
    if not mime or not mime.startswith("image/"):
        # Fallback: an der Endung hochziehen
        ext = os.path.splitext(filename)[1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp",
                "heic": "image/heic"}.get(ext.lstrip("."), "image/jpeg")

    url = f"{BASE}/building-passes/{pass_id}/projects/steps/building_pictures/{field_key}/upload"
    log.info("→ POST .../%s/upload  (file=%s, %s, %.0f KB)",
             field_key, filename, mime, os.path.getsize(file_path) / 1024)
    with open(file_path, "rb") as fh:
        # 3-Tupel (filename, fileobj, content_type) — ohne Content-Type sendet
        # requests bei Binärdaten oft application/octet-stream und der Server
        # antwortet 400 INVALID_UPLOAD_MIME_TYPE.
        # KEIN expliziter Content-Type-Header — requests berechnet die
        # multipart-boundary selbst.
        headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
        r = requests.post(url,
                          files={"file": (filename, fh, mime)},
                          headers=headers, timeout=120)
    try:
        body = r.json()
    except Exception:
        body = {"_raw_status": r.status_code, "_raw_text": r.text[:200]}
    if not (200 <= r.status_code < 300):
        raise ApiError("POST", url, r.status_code, body)
    log.info("    %s %s", r.status_code, _short(body))
    return body["data"]


def step_5c_upload_pictures(pass_id: int) -> None:
    """Lädt Gebäude- und Typenschild-Foto hoch und PATCHt die zurückgegebenen
    URLs explizit in building_pictures (entspricht dem 'Abschließen'-Klick
    in der UI: ohne diesen abschließenden PATCH bleibt der Step im Backend
    'unberührt' und der Draft-Workflow timeoutet beim Init)."""
    log.info("=== Schritt 5c: Gebäude-Fotos hochladen ===")
    targets = [
        ("buildingPic", BUILDING_PIC_PATH),
        ("nameplatePic", NAMEPLATE_PIC_PATH),
    ]
    uploaded: dict[str, str] = {}
    for field_key, path in targets:
        if not os.path.isfile(path):
            log.warning("    %s übersprungen — Datei fehlt: %s", field_key, path)
            continue
        info = _upload_picture(pass_id, field_key, path)
        log.info("    %s gespeichert: %s (%s, %d B)",
                 field_key, info.get("fileName"),
                 info.get("mimeType"), info.get("size", 0))
        if info.get("url"):
            uploaded[field_key] = info["url"]

    # Step explizit "abschließen" — entspricht dem 'Abschließen'-Klick in der UI.
    if uploaded:
        log.info("    PATCH building_pictures mit hochgeladenen URLs (Step abschließen)")
        call("PATCH", f"/building-passes/{pass_id}/projects",
             json_body={"data": {"steps": {"building_pictures": uploaded}}})


def step_6_completeness(pass_id: int, cert_type: str = "demand") -> None:
    log.info("=== Schritt 6: Vollständigkeit prüfen ===")
    try:
        body = call("GET", f"/building-passes/{pass_id}/projects/completeness",
                    params={"type": cert_type})
        log.info("    %s", _short(body.get("data")))
    except ApiError as e:
        log.warning("    Completeness-Endpoint: %s", e)


def step_7_draft(pass_id: int, cert_type: str = "demand",
                 max_wait_seconds: int = 600,
                 poll_interval: int = 5) -> dict | None:
    """Erzeugt einen Draft-Energieausweis. Der Backend-Job läuft asynchron
    und kann mehrere Minuten dauern. Der POST kann mit 500 'Timeout waiting
    for workflow ... to get initialized' zurückkommen — das heißt nicht, dass
    der Workflow weg ist, nur, dass die HTTP-Antwort timeoutet. Wir pollen
    anschließend den Status (Default: bis zu 10 Min, alle 5 Sekunden)."""
    log.info("=== Schritt 7: Draft erzeugen (kostenlose Vorschau) ===")

    # 1) Workflow auslösen
    try:
        body = call("POST",
                    f"/building-passes/{pass_id}/projects/certificates/drafts",
                    json_body={"type": cert_type})
        log.info("    Draft-Workflow gestartet: workflowId=%s",
                 body["data"].get("workflowId"))
    except ApiError as e:
        msg = str(e)
        if "Timeout waiting" in msg or "already started" in msg:
            log.warning("    POST timeoutet/läuft schon — wechsle in Polling-Modus.")
        else:
            log.error("    Draft fehlgeschlagen — Pflichtfelder fehlen?")
            log.error("    %s", e)
            return None

    # 2) Status pollen, bis Draft bereitsteht oder Timeout
    log.info("    Polling auf Draft-Status (Timeout %ds, alle %ds) — kann "
             "in der Sandbox mehrere Minuten dauern.",
             max_wait_seconds, poll_interval)
    started = time.time()
    deadline = started + max_wait_seconds
    attempt = 0
    last_status: Any = None
    while time.time() < deadline:
        attempt += 1
        try:
            body = call("GET",
                        f"/building-passes/{pass_id}/projects/certificates/status",
                        params={"type": cert_type})
            last_status = body.get("data")
            elapsed = int(time.time() - started)
            log.info("    Draft-Status (Versuch %d, %ds): %s",
                     attempt, elapsed, _short(last_status))
            if _draft_is_ready(last_status):
                log.info("    Draft fertig nach %ds.", elapsed)
                return last_status
        except ApiError as e:
            log.warning("    Status-Check fehlgeschlagen: %s", e)
        time.sleep(poll_interval)

    log.warning("    Draft-Polling-Timeout nach %ds. Letzter Stand: %s",
                max_wait_seconds, _short(last_status))
    log.warning("    Tipp: prüfe in der UI, ob der Draft inzwischen erstellt "
                "wurde — der Backend-Workflow läuft auch nach unserem Timeout "
                "weiter.")
    return last_status


def _draft_is_ready(status: Any) -> bool:
    """Akzeptiert verschiedene Schreibweisen, weil das Spec-Schema offen ist."""
    if not isinstance(status, dict):
        return False
    # Direkt im Top-Level
    s = (status.get("status") or status.get("state") or "").lower()
    if s in ("completed", "ready", "done", "succeeded", "success"):
        return True
    # Verschachtelt unter 'draft'
    draft = status.get("draft")
    if isinstance(draft, dict):
        s = (draft.get("status") or draft.get("state") or "").lower()
        if s in ("completed", "ready", "done", "succeeded", "success"):
            return True
        if draft.get("ready") is True or draft.get("url"):
            return True
    return False


# ---------------------------------------------------------------------------
# Bauteil-Management
# ---------------------------------------------------------------------------

def remove_elements_by_label(pass_id: int, label_pattern: str) -> int:
    """Entfernt alle Bauteile aus simplified_opaque_element.elements, deren
    flaechenbezeichnung den angegebenen String enthält (case-insensitiv).

    Hintergrund: Es gibt keinen DELETE-Endpoint für einzelne Bauteile.
    Der Weg ist: GET → Array filtern → PATCH mit dem vollständigen gefilterten
    Array (PATCH auf Array-Ebene = Replace, kein Merge).

    Typischer Anwendungsfall: Anbauwand einer Doppelhaushälfte entfernen, die
    LoD2 fälschlicherweise als Außenwand mitliefert.

        entfernt = remove_elements_by_label(pass_id, "Außenwand 3")
        # oder nach Muster, z.B. alle Elemente mit "Anbau" im Namen:
        entfernt = remove_elements_by_label(pass_id, "Anbau")

    Gibt die Anzahl der entfernten Elemente zurück.
    """
    body = call("GET", f"/building-passes/{pass_id}/projects")
    opaque = body["data"]["data"]["steps"].get("simplified_opaque_element", {}) or {}
    elements = opaque.get("elements", []) or []

    original_count = len(elements)
    filtered = [
        el for el in elements
        if label_pattern.lower() not in (el.get("flaechenbezeichnung") or "").lower()
    ]
    removed_count = original_count - len(filtered)

    if removed_count == 0:
        log.info("    Kein Element mit Label '%s' gefunden — nichts entfernt", label_pattern)
        return 0

    call("PATCH", f"/building-passes/{pass_id}/projects",
         json_body={"data": {"steps": {"simplified_opaque_element": {"elements": filtered}}}})
    log.info("    %d Element(e) mit Label '%s' entfernt (%d → %d Elemente gesamt)",
             removed_count, label_pattern, original_count, len(filtered))
    return removed_count


def replace_lod2_walls_with_user_values(pass_id: int,
                                         user_elements: list[dict]) -> None:
    """Ersetzt alle LoD2-Außenwände durch eigene Messwerte (source='user').

    Workflow für Anbau-Situationen (z.B. Doppelhaushälfte): LoD2 liefert auch
    die Wand zum Nachbargebäude mit → Wandfläche zu hoch → Energieklasse zu
    schlecht. Lösung: LoD2-Außenwände entfernen, eigene Werte einfügen.

    Nicht-Außenwand-Elemente (Boden, Tür, Dachflächen im opaque-Step) aus
    LoD2 werden beibehalten — nur Elemente mit 'Außenwand' im Namen werden
    ersetzt.

    Beispiel:
        replace_lod2_walls_with_user_values(pass_id, [
            {"flaechenbezeichnung": "Außenwand Nord",  "flaeche": "32.10",
             "ausrichtung": "North"},
            {"flaechenbezeichnung": "Außenwand Süd",   "flaeche": "32.10",
             "ausrichtung": "South"},
            {"flaechenbezeichnung": "Außenwand West",  "flaeche": "24.50",
             "ausrichtung": "West"},
            # Anbauwand zum Nachbarn wird NICHT angegeben → entfällt
        ])
    """
    body = call("GET", f"/building-passes/{pass_id}/projects")
    opaque = body["data"]["data"]["steps"].get("simplified_opaque_element", {}) or {}
    elements = opaque.get("elements", []) or []

    # Alle LoD2-Außenwände herausfiltern, Rest (Boden, Tür, …) behalten
    kept = [
        el for el in elements
        if not (el.get("source") == "lod2"
                and "außenwand" in (el.get("flaechenbezeichnung") or "").lower())
    ]
    lod2_wall_count = len(elements) - len(kept)

    # Eigene Wände mit source='user' einfügen
    for el in user_elements:
        el.setdefault("source", "user")
    merged = kept + user_elements

    call("PATCH", f"/building-passes/{pass_id}/projects",
         json_body={"data": {"steps": {"simplified_opaque_element": {"elements": merged}}}})
    log.info("    %d LoD2-Außenwand/-Wände entfernt, %d eigene eingefügt "
             "(%d Elemente gesamt)", lod2_wall_count, len(user_elements), len(merged))


def add_user_elements(pass_id: int, new_elements: list[dict]) -> None:
    """Fügt eigene Bauteile (source='user') zu simplified_opaque_element.elements
    hinzu, ohne vorhandene Elemente zu entfernen.

    Holt den aktuellen Stand per GET, hängt die neuen Elemente an und schickt
    das vollständige Array per PATCH zurück (Array-PATCH = Replace).

    Beispiel:
        add_user_elements(pass_id, [
            {"flaechenbezeichnung": "Erweiterungsbau Süd", "flaeche": "18.00",
             "ausrichtung": "South", "source": "user"},
        ])
    """
    body = call("GET", f"/building-passes/{pass_id}/projects")
    opaque = body["data"]["data"]["steps"].get("simplified_opaque_element", {}) or {}
    elements = opaque.get("elements", []) or []

    for el in new_elements:
        el.setdefault("source", "user")

    merged = elements + new_elements
    call("PATCH", f"/building-passes/{pass_id}/projects",
         json_body={"data": {"steps": {"simplified_opaque_element": {"elements": merged}}}})
    log.info("    %d eigene(s) Bauteil(e) hinzugefügt (%d Elemente gesamt)",
             len(new_elements), len(merged))


def log_all_elements(pass_id: int) -> None:
    """Gibt alle Bauteile des Passes tabellarisch aus — nützlich zur Inspektion
    vor dem manuellen Bereinigen von LoD2-Geometrien."""
    body = call("GET", f"/building-passes/{pass_id}/projects")
    elements = (body["data"]["data"]["steps"]
                .get("simplified_opaque_element", {}).get("elements", []) or [])
    log.info("    Alle Bauteile (%d):", len(elements))
    for i, el in enumerate(elements, 1):
        log.info("      %2d. %-30s | source=%-4s | %s m² | %s",
                 i,
                 el.get("flaechenbezeichnung", "?"),
                 el.get("source", "?"),
                 el.get("flaeche", "?"),
                 el.get("ausrichtung", "–"))


def step_8_checkout(pass_id: int, cert_type: str = "demand") -> None:
    log.info("=== Schritt 8: Stripe-Checkout-Session erzeugen ===")
    try:
        body = call("POST",
                    f"/building-passes/{pass_id}/projects/certificates/final/checkout",
                    json_body={"type": cert_type})
        url = body["data"]["checkoutUrl"]
        log.info("    Bezahlung erforderlich. Stripe-URL:")
        log.info("      %s", url)
        log.info("    [Bezahlung NICHT automatisiert — manuell im Browser durchführen,")
        log.info("     dann erst /final/submit aufrufen.]")
    except ApiError as e:
        log.error("    Checkout fehlgeschlagen: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cert_type = "demand"
    # Default: Pass nur befüllen — Vorschau und Checkout dann manuell in der UI.
    # Per ENV-Flag aktivierbar:
    #   EG_RUN_DRAFT=1     → step_7_draft ausführen (Polling kann mehrere Min dauern)
    #   EG_RUN_CHECKOUT=1  → zusätzlich step_8_checkout (Stripe-URL erzeugen)
    run_draft = os.environ.get("EG_RUN_DRAFT") == "1"
    run_checkout = os.environ.get("EG_RUN_CHECKOUT") == "1"
    try:
        step_1_auth_check()
        step_2_load_catalog(cert_type)
        pass_id, project_id = step_3_create_pass(cert_type)
        step_4_patch_heating(pass_id)
        step_5_inspect_state(pass_id)
        step_5b_fix_lod2_floor_type(pass_id)
        step_5c_upload_pictures(pass_id)
        step_6_completeness(pass_id, cert_type)

        if not run_draft:
            log.info("=== Pass befüllt — passId=%s ===", pass_id)
            log.info("Nächste Schritte manuell in der UI:")
            log.info("  1. Pass öffnen → Vorschau erstellen")
            log.info("  2. Vorschau prüfen → Checkout/Kauf abschließen")
            log.info("Oder per Skript: EG_RUN_DRAFT=1 [EG_RUN_CHECKOUT=1] python3 e2e_demo.py")
            return 0

        draft = step_7_draft(pass_id, cert_type)
        if draft is not None and run_checkout:
            step_8_checkout(pass_id, cert_type)
        elif draft is not None:
            log.info("Checkout übersprungen (Vorschau erstellt, Pass bleibt unbezahlt).")
            log.info("Zum Skript-Checkout: EG_RUN_CHECKOUT=1 python3 e2e_demo.py")
        log.info("=== Fertig. Test-Pass-ID = %s (in der UI ggf. löschen) ===", pass_id)
        return 0
    except ApiError as e:
        log.error("Abbruch: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
