# EnerGuide API — Schritt-für-Schritt-Anleitung für Integratoren

**Version:** 1.0 · **Stand:** 2026-05-05 · **Zielgruppe:** Entwickler & Integratoren

Diese Anleitung führt dich vom ersten API-Call bis zum bezahlten und heruntergeladenen Energieausweis. Code-Beispiele in Python, ergänzt durch cURL für Quick-Tests.

---

## Inhaltsverzeichnis

1. [Was die API tut](#1-was-die-api-tut)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Authentifizierung](#3-authentifizierung)
4. [Workflow-Überblick](#4-workflow-überblick)
5. [Schritt 1 — Anforderungskatalog abrufen](#schritt-1--anforderungskatalog-abrufen)
6. [Schritt 2 — Gebäudepass + Projekt anlegen](#schritt-2--gebäudepass--projekt-anlegen)
7. [Schritt 3 — Daten editieren](#schritt-3--daten-editieren-patch)
8. [Schritt 4 — Vollständigkeit prüfen](#schritt-4--vollständigkeit-prüfen)
9. [Schritt 5 — Gebäudefotos hochladen](#schritt-5--gebäudefotos-hochladen-optional)
10. [Schritt 6 — Vorschau erzeugen (Draft)](#schritt-6--vorschau-erzeugen-draft)
11. [Schritt 7 — Bezahlen via Stripe-Checkout](#schritt-7--bezahlen-via-stripe-checkout)
12. [Schritt 8 — Einreichen (Submit)](#schritt-8--einreichen-submit)
13. [Schritt 9 — Energieausweis abholen](#schritt-9--energieausweis-abholen-pdf)
14. [Fehlerbehandlung](#fehlerbehandlung)
15. [Troubleshooting & häufige Fallstricke](#troubleshooting--häufige-fallstricke)
16. [End-to-End-Python-Skript](#end-to-end-python-skript)
17. [Anhang A — Endpoint-Referenz](#anhang-a--endpoint-referenz)
18. [Anhang B — Wichtige Step-IDs](#anhang-b--wichtige-step-ids)
19. [Anhang C — Diskrepanzen OpenAPI ↔ Realität](#anhang-c--diskrepanzen-openapi--realität)
20. [Anhang D — Glossar](#anhang-d--glossar)

---

## 1. Was die API tut

Die EnerGuide External API erzeugt **digitale Gebäudepässe** und daraus **Energieausweise** (GEG-konform, Bedarfs- oder Verbrauchsausweis). Der Lebenszyklus eines Vorgangs ist:

1. Du legst einen **Gebäudepass** an (Container für ein Gebäude).
2. Im Pass entstehen ein oder mehrere **Projekte** — typisch eins pro Energieausweis-Variante.
3. Im Projekt füllst du **Steps** mit Gebäudedaten (Adresse, Geometrie, Heizung, Hülle, …).
4. Du erzeugst eine **Draft-Vorschau** (kostenlos) und kannst weiter editieren.
5. Wenn der Draft passt: **Checkout via Stripe** → Bezahlung → **Submit** → geprüfter, signierter Energieausweis als PDF.

Die API ist eine REST-JSON-API mit Bearer-Token-Authentifizierung. Es gibt eine Staging-Umgebung (`api.staging.enerithm.com`) und eine Produktiv-Umgebung; diese Anleitung verwendet Staging.

---

## 2. Voraussetzungen

| | |
|---|---|
| **Account** | Auf [energuide.de](https://energuide.de) mit einem Tier, der API-Zugriff einschließt. |
| **API-Token** | In der EnerGuide-UI generieren. Format: `egapi_<id>.<secret>`. |
| **Staging-Host** | `https://api.staging.enerithm.com/api/core/v1` |
| **Produktiv-Host** | (über Account / Support; gleiche Pfade, anderes Token erforderlich) |
| **Python** | 3.10+ (für die Code-Beispiele in dieser Anleitung). Empfohlen: `httpx` oder `requests`. Beispiele hier mit der Standard-Lib `urllib`, damit keine Dependencies nötig sind. |

Als Integrator solltest du dich kurz mit den drei wichtigsten Domänenbegriffen vertraut machen:

- **Pass** — der Container für ein konkretes Gebäude (eine Adresse). Hat eine `id`.
- **Projekt** — eine Datenfassung des Gebäudes für genau einen Energieausweis-Anlass. Hat eine `id` und gehört zu einem Pass. Ein Pass kann mehrere Projekte haben (z. B. Bedarf + Verbrauch nebeneinander).
- **Step** — eine logische Datengruppe innerhalb eines Projekts (z. B. `building_address`, `living_area`, `heating_generator_data_step`). Steps sind das Edit-Granulat.

Speichere dein Token sicher als Umgebungsvariable, **niemals im Repo**:

```bash
export EG_TOKEN='egapi_d1794358a214c66b.gWkTETFwFKn1LAMfYI1-XZC7ohkIP_zB'
```

---

## 3. Authentifizierung

Jeder authentifizierte Endpoint erwartet das Token als Bearer-Header:

```
Authorization: Bearer <EG_TOKEN>
```

`GET /health` ist der einzige Endpoint, der **kein** Token benötigt — ideal als Smoke-Test.

```python
import os, json, urllib.request

TOKEN = os.environ["EG_TOKEN"]
BASE  = "https://api.staging.enerithm.com/api/core/v1"

def call(method, path, body=None):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# Smoke-Test
print(call("GET", "/health"))
# -> (200, {'status': 'ok', 'timestamp': '2026-05-05T06:40:19.179Z'})
```

cURL-Äquivalent:

```bash
curl -s "$EG_BASE/health"
curl -sH "Authorization: Bearer $EG_TOKEN" "$EG_BASE/building-passes"
```

> **Tipp:** Wenn `GET /building-passes` mit `401` antwortet, ist dein Token ungültig oder abgelaufen — neu im UI generieren. Wenn es mit `200` und `{"data": [...]}` zurückkommt, ist alles bereit.

---

## 4. Workflow-Überblick

```
                 ┌──────────────────────────┐
   Vorbereitung  │ GET /requirements/catalog │  ← Quelle der Wahrheit für Pflichtfelder
                 └──────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────────┐
   Schritt 2  │ POST /building-passes/projects   │  → passId, projectId
              │ (oder zweistufig: Pass + Projekt) │
              └──────────────────────────────────┘
                              │
                              ▼ (iterativ, Merge-Semantik)
              ┌──────────────────────────────────┐
   Schritt 3  │ PATCH /building-passes/{id}/      │
              │       projects                    │
              └──────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────────┐
   Schritt 4  │ GET .../requirements?type=…       │  ← was fehlt noch?
              │ GET .../completeness?type=…       │
              └──────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────────┐
   Schritt 6  │ POST .../certificates/drafts      │  → kostenlose Vorschau
              └──────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────────┐
   Schritt 7  │ POST .../certificates/final/      │  → checkoutUrl
              │      checkout                     │     (Stripe)
              └──────────────────────────────────┘
                              │
                              ▼ (nach Bezahlung)
              ┌──────────────────────────────────┐
   Schritt 8  │ POST .../certificates/final/      │
              │      submit                       │
              └──────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────────┐
   Schritt 9  │ GET /building-passes/{id}/        │
              │     certificates                  │
              │ GET /certificates/{id}/download   │  → PDF
              └──────────────────────────────────┘
```

---

## Schritt 1 — Anforderungskatalog abrufen

`GET /requirements/catalog?type=demand|consumption` ist **der wichtigste Endpoint der API**. Er liefert für den gewählten Ausweistyp:

- alle Pflicht- und Optional-Felder (134 Anforderungen für `demand`),
- die `allowedValues` aller Enums (Bundesland, Heizsystem, Energieträger, Wandtypen, …),
- bedingte Anforderungen (z. B. *„Sanierungsjahr Fenster nur, wenn `windows_done = true`"*),
- eine `examplePayload` als Referenz-Struktur.

> **Wichtig:** Behandle `/requirements/catalog` als die kanonische Quelle für Pflichtfelder. Die OpenAPI-Spec der API ist an mehreren Stellen veraltet/intern; der Catalog ist immer aktuell. Siehe [Anhang C](#anhang-c--diskrepanzen-openapi--realität).

```python
status, body = call("GET", "/requirements/catalog?type=demand")
catalog = body["data"]

print(f"Total Anforderungen: {catalog['totalRequirements']}")  # 134
print(f"Kategorien: {catalog['categories']}")
# ['Ausstellungsanlass', 'Gebäudeinformationen', 'Thermische Gebäudehülle', ...]

# Nur Pflichtfelder filtern
required = [r for r in catalog["requirements"] if r.get("required")]
print(f"Davon Pflicht: {len(required)}")

# Bedingte Anforderungen erkennen
conditional = [r for r in required if r.get("conditions")]
print(f"Davon bedingt: {len(conditional)}")

# allowedValues für ein bestimmtes Feld (z. B. Bundesland)
states = next(
    r for r in catalog["requirements"]
    if r["stepId"] == "building_address" and r["fieldKey"] == "federalState"
)
print(states["validation"]["allowedValues"])
# ['Baden-Württemberg', 'Bayern', 'Berlin', 'Brandenburg', ...]

# Hinweis: Der Catalog beschreibt Felder noch in der internen GEG-Form
# (z. B. heating_generator_data_step.HeatingGenerator1). Beim Senden
# verwendest du die Wire-Form heatingGenerators[] (siehe Schritt 3).
```

cURL:

```bash
curl -sH "Authorization: Bearer $EG_TOKEN" \
  "$EG_BASE/requirements/catalog?type=demand" | jq '.data | {totalRequirements, categories}'
```

### Catalog-Felder verstehen

Jede Anforderung sieht so aus:

```json
{
  "stepId": "building_address",
  "fieldKey": "postalCode",
  "path": "GDaten.Gebaeudeadresse_Postleitzahl",
  "category": "Gebäudeinformationen",
  "description": "Postleitzahl",
  "required": true,
  "validation": {"type": "zod_validation", "pattern": "^[0-9]{5}$"}
}
```

- `stepId` + `fieldKey` ist die Adresse, an der du das Feld in deinem Payload setzt: `data.steps.<stepId>.<fieldKey>`.
- `path` ist der **interne** GEG-Datenpfad — du brauchst ihn beim Senden **nicht**.
- `validation` enthält je nach Feld `pattern`, `min`/`max`, `allowedValues` oder `minLength` für Arrays.
- `conditions` (falls vorhanden) macht die Anforderung bedingt: nur Pflicht, wenn der referenzierte Pfad einen bestimmten Wert hat.

---

## Schritt 2 — Gebäudepass + Projekt anlegen

Es gibt zwei Wege, einen Pass zu starten:

### Empfohlen: One-Shot-Endpoint

`POST /building-passes/projects` erzeugt **Pass und Projekt in einem Call** und akzeptiert direkt initiale Step-Daten:

```python
create_payload = {
    "passName": "Haydnstr 59 — Bedarfsausweis",
    "name": "Bedarfsausweis 2026",
    "certificateTypeSelection": "demand",   # oder "consumption"
    "data": {
        "steps": {
            "reason_for_issue": {"value": "Vermietung-Verkauf"},
            "building_address": {
                "street": "Haydnstraße 59",
                "postalCode": "01309",
                "city": "Dresden",
                "federalState": "Sachsen",
                "country": "Deutschland"
            }
        }
    }
}

status, body = call("POST", "/building-passes/projects", body=create_payload)
# status = 201
# body = {"data": {"passId": 91, "projectId": 71,
#                  "name": "Bedarfsausweis 2026",
#                  "certificateTypeSelection": "demand"}}

pass_id    = body["data"]["passId"]
project_id = body["data"]["projectId"]
```

> **Beachte:** Die Create-Response enthält bewusst nur die gerade angelegten IDs und Metadaten — *nicht* die persistierten Step-Daten. Wenn du den vollständigen Stand inkl. aller Steps brauchst, hol ihn explizit per `GET /building-passes/{passId}/projects` (siehe Schritt 3, Hinweis zur Verschachtelung). Der Server reichert dabei die Adresse stillschweigend mit `latitude`/`longitude` an — das ist normal.

### Alternative: zweistufig

Wenn du einen Pass *ohne* Projekt anlegen willst (z. B. weil du erst später entscheidest, welcher Ausweistyp), nutze:

```
POST /building-passes                       → erstellt nur den Pass
POST /building-passes/{passId}/projects     → erstellt das Projekt darin
```

### Adressformat — die häufigste Stolperfalle

Im `building_address`-Step gibt es **kein** separates `houseNumber`-Feld; die Hausnummer wird Teil von `street`. Außerdem sind `federalState` und `country` Pflichtfelder:

```json
"building_address": {
  "street": "Haydnstraße 59",
  "postalCode": "01309",
  "city": "Dresden",
  "federalState": "Sachsen",
  "country": "Deutschland"
}
```

`federalState` muss eines der 16 deutschen Bundesländer sein (Liste über `/requirements/catalog`). Ein eigenes `houseNumber`-Feld führt zu:

```
HTTP 400  UNKNOWN_FIELD_KEY
"Unknown field 'houseNumber' for step 'building_address'"
```

### LoD2-Auto-Befüllung der Bauteilflächen

Für Adressen, die in der **LoD2-Datenbank** enthalten sind (große Teile Deutschlands), ergänzt der Server automatisch die Außenwand-, Dach- und ggf. weiteren Bauteilflächen aus dem Geometriemodell. Du erkennst das nach dem Create am `source`-Feld der Bauteile:

```json
"simplified_opaque_element": {
  "elements": [
    {"flaechenbezeichnung": "Außenwand 3", "ausrichtung": "SouthWest",
     "flaeche": 55.98, "source": "lod2"}
  ]
}
```

Du kannst eigene Bauteile mit `source: "user"` ergänzen oder ersetzen — beide Quellen koexistieren. Adressen außerhalb der LoD2-Abdeckung (häufig kleine Gemeinden) erfordern, dass du `simplified_opaque_element.elements` und ggf. `simplified_roof_details.elements` selbst füllst.

> **Achtung — LoD2-Loading ist asynchron.** Ein direkter `GET /building-passes/{passId}/projects` unmittelbar nach dem Create gibt häufig noch keine oder nur einen Teil der LoD2-Bauteile zurück. Beobachte das Flag `simplified_opaque_element.bodatenLodLoaded`:
>
> | Wert | Bedeutung |
> |---|---|
> | `null` / `false` | LoD2-Job läuft noch — Bauteilliste ist unvollständig. |
> | `true` | LoD2 abgeschlossen, alle Geometrie-Bauteile sind in `elements`. |
>
> Polling-Pattern (siehe `step_5_inspect_state` in `e2e_demo.py`):
>
> ```python
> import time
> while True:
>     body = call("GET", f"/building-passes/{pass_id}/projects")
>     opaque = body["data"]["data"]["steps"].get("simplified_opaque_element", {}) or {}
>     if opaque.get("bodatenLodLoaded") is True:
>         break
>     time.sleep(2)
> ```
>
> **Erst nach dem Polling** den Boden-Typ-Patch (s.u.) anwenden — sonst patcht du gegen einen leeren oder unvollständigen Stand.

> **Wichtig — LoD2-Folgeaufgabe für Boden-Elemente:**
>
> Wie der Server den `typ` eines Bauteils auflöst, hängt davon ab, **ob das Element selbst einen `typ` trägt**:
>
> | Zustand des Elements | Verhalten |
> |---|---|
> | `typ` ist leer / `null` / fehlt | Server zieht den **globalen** Konstruktionstyp aus `construction_opaque_elements` (`typeOfExternalWall`, `typeOfBasementCeiling`, `typeOfFloorToGround`) — kein manueller Patch nötig. |
> | `typ` enthält einen konkreten Wert (z.B. `BE_LowerCompletionToSoil`) | Wird verwendet wie angegeben. |
> | `typ` enthält den Sentinel `"NotSet"` | Bleibt undefiniert — der globale Mechanismus greift **nicht**. Validierung lehnt den Ausweis ab. |
>
> LoD2 liefert seine Bauteile mit `typ: "NotSet"` aus. Für **Außenwände und Decken** ist das in der Praxis unkritisch, weil ihre Werte ohnehin in `construction_opaque_elements` global definiert werden und der Server beim Berechnen darauf zurückgreift. Für **Boden-Elemente** musst du den `typ` jedoch explizit setzen — entweder den Sentinel auf einen konkreten Wert ändern oder ihn entfernen, damit der globale Mechanismus übernimmt.
>
> Beispiel-Pattern (GET → Array mutieren → komplettes Array zurück-PATCHen, weil PATCH auf Array-Ebene Replace ist):
>
> ```python
> body = call("GET", f"/building-passes/{pass_id}/projects")
> elements = body["data"]["data"]["steps"]["simplified_opaque_element"]["elements"]
> for el in elements:
>     if el.get("flaechenbezeichnung", "").startswith("Boden") and el.get("typ") in (None, "NotSet"):
>         el["typ"] = "BE_LowerCompletionToSoil"   # Bodenplatte gegen Erdreich
> call("PATCH", f"/building-passes/{pass_id}/projects",
>      json_body={"data": {"steps": {"simplified_opaque_element": {"elements": elements}}}})
> ```
>
> `e2e_demo.py` enthält das als `step_5b_fix_lod2_floor_type` als Vorlage.

---

## Schritt 3 — Daten editieren (PATCH)

`PATCH /building-passes/{passId}/projects` aktualisiert das aktive Projekt des Passes. Wichtig:

> **PATCH ist Merge — auf Step- und Feld-Ebene.** Nur die mitgesendeten Felder/Steps werden überschrieben; alle anderen Steps bleiben unangetastet. Du kannst und solltest iterativ patchen — Step für Step.
>
> **Aber Achtung bei Array-Feldern:** Innerhalb eines Step-Felds, das eine Liste enthält (`simplified_opaque_element.elements`, `heatingGenerators`, …), ersetzt PATCH das *gesamte Array*. Wenn du nur ein Element ändern willst, lies die aktuelle Liste per GET, mutiere sie und sende sie *vollständig* zurück. Sonst gehen die anderen Einträge verloren.

```python
# Wohnfläche von 199 auf 200 ändern, sonst nichts berühren:
status, body = call("PATCH", f"/building-passes/{pass_id}/projects", body={
    "data": {"steps": {"living_area": {"value": "200"}}}
})

# Heizung später nachreichen:
status, body = call("PATCH", f"/building-passes/{pass_id}/projects", body={
    "data": {"steps": {
        "heating_generator_data_step": {
            "heatingGenerators": [
                {"type": "Standard_Boiler", "energyCarrier": "Gas",
                 "coverage": "1", "yearOfConstruction": "1998"}
            ],
            "hasHeatingStorage": False
        }
    }
})
```

### Aktuellen Stand abrufen

Wenn du das volle Projekt mit allen Steps lesen willst:

```python
status, body = call("GET", f"/building-passes/{pass_id}/projects")
project_meta = body["data"]                 # id, name, certificateTypeSelection, …
steps        = body["data"]["data"]["steps"]   # ← doppelte data-Verschachtelung!
```

> **Achtung — doppelte `data`-Verschachtelung:** Der äußere Wrapper `body["data"]` enthält die Projekt-Metadaten; die Step-Inhalte selbst liegen *darunter* in `body["data"]["data"]["steps"]`. Wer aus Gewohnheit nur `body["data"]["steps"]` schreibt, sieht keine Steps und denkt versehentlich an Replace-Verhalten.

### Datentyp-Konvention

Der Server normalisiert großzügig:

- Zahlen können als String *oder* Number gesendet werden — intern werden sie zu Numbers.
- Beispiel: `"value": "199"` wird zu `"value": 199` in der Response.
- Konvention im Catalog-Beispielpayload: numerische Felder als String, `transparent_share.percentage` als echte Zahl.

### Heizsystem — Array-Form

Das Step `heating_generator_data_step` akzeptiert zwei Formen — **verwende die Array-Form**:

```json
"heating_generator_data_step": {
  "heatingGenerators": [
    {"type": "Standard_Boiler", "energyCarrier": "Gas",
     "coverage": "1", "yearOfConstruction": "1998"}
  ],
  "hasHeatingStorage": false
}
```

Bis zu drei Erzeuger sind erlaubt; die Summe von `coverage` muss 1.0 (bzw. 100%) ergeben. Die OpenAPI-Spec zeigt eine alte Form (`HeatingGenerator1`, `EnergyCarrier_HeatingGenerator1`, …); die ist intern noch sichtbar, aber nicht die empfohlene Eingabe.

### Step-Aliase — du musst sie nicht alle kennen

Der Server pflegt mehrere Step-Namen, die das gleiche Feld zeigen (z. B. `cooling_system_basic` ↔ `type_of_cooling`, `dhw_supply_demand` ↔ `dhw_supply`). **Beim Senden reicht eine Form** — der Server propagiert in die anderen. Beim Lesen bekommst du oft beide.

In der `examplePayload` aus `/requirements/catalog` und in dieser Anleitung verwenden wir durchgehend die kanonischen Namen:

| Verwende | Nicht (alt/intern) |
|----------|--------------------|
| `cooling_system_basic` | `type_of_cooling` |
| `ventilation_system_basic` | `type_of_ventilation` |
| `renewable_energy_basic` | `renewable_energy` |
| `dhw_supply_demand` | `dhw_supply` |
| `heatingGenerators` (Array) | `HeatingGenerator1`, `HeatingGenerator2`, … |

---

## Schritt 4 — Vollständigkeit prüfen

Bevor du den Draft erzeugst, kannst du gegen den Server prüfen, was noch fehlt. **Beide Endpoints brauchen den Query-Parameter `type=demand|consumption`** — das ist in der OpenAPI-Spec nicht dokumentiert, ohne den Parameter bekommst du `400 VALIDATION_ERROR: type Required`.

```python
# Was fehlt noch?
status, body = call("GET", f"/building-passes/{pass_id}/projects/requirements?type=demand")
missing = [r for r in body["data"] if r.get("required") and not r.get("fulfilled")]
print(f"{len(missing)} Pflichtfelder noch offen")

# Globale Vollständigkeitsanzeige
status, body = call("GET", f"/building-passes/{pass_id}/projects/completeness?type=demand")
print(body["data"])  # z. B. {'totalFields': 134, 'fulfilledFields': 130, 'percentage': 0.97}
```

Pattern: patchen → `requirements` abfragen → patchen → bis nichts mehr kritisch fehlt.

---

## Schritt 5 — Gebäudefotos hochladen (optional)

Pflicht für den fertigen Energieausweis sind laut Catalog:
- `building_pictures.buildingPic` — Foto des Gebäudes
- `building_pictures.nameplatePic` — Foto des Heizungs-Typenschilds

Optional: `windowPic`, `atticPic`, `basementPic`, `heatingRoomPic` (per PATCH als URL).

Es gibt zwei Wege, Fotos zu hinterlegen:

### A) Direkter File-Upload via Multipart (empfohlen)

```
POST /building-passes/{passId}/projects/steps/building_pictures/{fieldKey}/upload
Content-Type: multipart/form-data
```

| Detail | Wert |
|---|---|
| Pfad-Parameter `fieldKey` | `buildingPic` oder `nameplatePic` (Spec-Enum) |
| Form-Feldname | `file` |
| Auth | wie sonst: `Authorization: Bearer …` |
| Antwort | `{ data: { stepId, fieldKey, url, mimeType, size, fileName } }` |

Der Server speichert das Bild in einem privaten Bucket und mappt das Step-Feld automatisch auf die finale URL — ein nachträglicher PATCH ist **nicht** nötig.

```python
import mimetypes, os, requests

def upload_picture(pass_id, field_key, file_path):
    filename = os.path.basename(file_path)
    mime, _ = mimetypes.guess_type(filename)        # → "image/png" / "image/jpeg" / …
    with open(file_path, "rb") as fh:
        r = requests.post(
            f"{BASE}/building-passes/{pass_id}/projects/steps/building_pictures/{field_key}/upload",
            headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
            files={"file": (filename, fh, mime)},   # 3-Tupel mit MIME-Type!
            timeout=120,
        )
    r.raise_for_status()
    return r.json()["data"]   # → { stepId, fieldKey, url, mimeType, size, fileName }

upload_picture(pass_id, "buildingPic",  "foto_gebaeude.png")
upload_picture(pass_id, "nameplatePic", "foto_typenschild.jpg")
```

Wichtig:
- Der Server validiert den MIME-Type strikt — übergib das **3-Tupel `(filename, fileobj, mime)`** an `files=`. Ohne explizites MIME schickt `requests` bei Binärdaten oft `application/octet-stream` und du bekommst:
  ```
  400  INVALID_UPLOAD_MIME_TYPE — Invalid MIME type for upload field
       file.type: Allowed type: image/*
  ```
- Beim multipart-Request **kein** expliziter `Content-Type`-Header auf der Request — `requests` errechnet die multipart-Boundary selbst.
- Das `fieldKey`-Pfad-Enum ist auf `buildingPic` und `nameplatePic` beschränkt. Andere Felder (`windowPic`, …) hinterlegst du per Variante B als URL.

### B) URL per PATCH setzen

Für den Fall, dass du eigenes Bild-Hosting hast oder nur eine Demo brauchst:

```python
call("PATCH", f"/building-passes/{pass_id}/projects", body={
    "data": {"steps": {"building_pictures": {
        "buildingPic":   "https://example.com/haus.jpg",
        "nameplatePic":  "https://example.com/typenschild.jpg"
    }}}
})
```

Der Server lädt die Bilder herunter und ersetzt deine Original-URL durch eine signierte S3-URL — beim nächsten GET siehst du `…?X-Amz-Signature=…`.

---

## Schritt 6 — Vorschau erzeugen (Draft)

Wenn dein Projekt vollständig oder annähernd vollständig ist, kannst du einen **Draft** erzeugen — eine kostenlose Vorschau des Energieausweises, die du vor dem Bezahlen prüfen kannst.

```python
call("POST", f"/building-passes/{pass_id}/projects/certificates/drafts",
     body={"type": "demand"})

# 201 Created
# body = {"data": {"workflowId": "create-draft-demand-project-71",
#                  "projectId": 71, "type": "demand", "variant": "draft"}}
```

> **Asynchroner Workflow.** Der Draft wird im Backend von einer Workflow-Engine erzeugt. Du wirst hierbei in der Praxis zwei Verhaltensweisen sehen:
>
> | Antwort | Bedeutung |
> |---|---|
> | `201 Created` mit `workflowId` | Der Draft-Job ist gestartet — aber noch nicht fertig. Status pollen. |
> | `500 INTERNAL_ERROR — Timeout waiting for workflow … to get initialized` | Die HTTP-Antwort ist getimeoutet, der Job läuft im Hintergrund trotzdem weiter. **Nicht** erneut POSTen (der zweite Aufruf scheitert mit `Workflow execution already started`). Stattdessen pollen. |
> | `500 INTERNAL_ERROR — Workflow execution already started` | Es läuft schon ein Draft-Job für diesen Pass. Pollen. |
>
> Polling-Pattern (siehe `step_7_draft` in `e2e_demo.py`):
>
> ```python
> import time
> deadline = time.time() + 600        # bis zu 10 Min — Draft-Generierung
> while time.time() < deadline:       # läuft serverseitig asynchron
>     body = call("GET",
>                 f"/building-passes/{pass_id}/projects/certificates/status",
>                 params={"type": "demand"})
>     status = body.get("data", {})
>     if status.get("status") in ("completed", "ready", "done"):
>         break
>     time.sleep(5)
> ```
>
> **Realistische Dauer in der Demo-Sandbox:** mehrere Minuten, gelegentlich auch >5 min. Wenn dein Polling vorher abbricht, ist der Draft trotzdem nicht verloren — der Workflow läuft im Backend weiter, und du kannst denselben Status-Endpoint später erneut abfragen oder den Draft direkt in der UI sehen.

**Wichtig zur Sichtbarkeit:** Drafts erscheinen **nicht** in der `/building-passes/{passId}/certificates`-Liste — diese ist nur für Final-Zertifikate. Der Status eines Drafts ist über `/projects/certificates/status?type=demand` abrufbar.

Wenn der Draft-Call mit `400 VALIDATION_ERROR` antwortet, fehlen Pflichtfelder — die `details`-Liste im Fehler nennt dir die genauen Pfade. Patche die fehlenden Felder und versuche es erneut.

---

## Schritt 7 — Bezahlen via Stripe-Checkout

> **Achtung — wichtige Information:** `final/checkout` ist **kein** technischer Validierungsschritt, sondern startet eine **Stripe-Bezahlsession**. Energieausweise sind kostenpflichtig.

```python
status, body = call("POST",
    f"/building-passes/{pass_id}/projects/certificates/final/checkout",
    body={"type": "demand"})

# 201 Created
# body = {
#   "data": {
#     "orderId": 35,
#     "workflowId": "create-order-project-71-product-2",
#     "stripeSessionId": "cs_test_b1Sh...",
#     "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_test_b1Sh...",
#     "productId": 2
#   }
# }

checkout_url = body["data"]["checkoutUrl"]
print(f"Bitte Bezahlung abschließen: {checkout_url}")
```

Was tun mit `checkoutUrl`?

- **In einer Web-Integration:** Leite den Endkunden auf die URL um. Stripe nimmt die Bezahlung entgegen und ruft anschließend den von dir konfigurierten Success-Redirect auf.
- **Im Demo/Headless-Test:** Öffne die URL im Browser (`cs_test_*` ist eine Stripe-Test-Session, die mit Test-Kreditkarten wie `4242 4242 4242 4242` durchgespielt werden kann).
- **Programmatisch ohne UI:** nicht vorgesehen — die Bezahlung erfolgt zwingend bei Stripe.

Nachdem die Bezahlung durch ist (Webhook von Stripe an EnerGuide), darfst du den Submit-Endpoint aufrufen.

---

## Schritt 8 — Einreichen (Submit)

```python
status, body = call("POST",
    f"/building-passes/{pass_id}/projects/certificates/final/submit",
    body={"type": "demand"})
```

> **Nach erfolgreichem Submit ist das Projekt nicht mehr editierbar.** Die DIBt-Registrierungsnummer wird vergeben, der Energieausweis wird offiziell ausgestellt.

Hinweis: Der Submit-Endpoint wurde in der Sandbox nicht durchgespielt (keine echte Bezahlung), das genaue Response-Format der erfolgreichen Submission ist daher in dieser Anleitung nicht verifiziert. Erwartet wird nach dem Muster der anderen Endpoints `{"data": {certificateId, workflowId, status, issueDate, …}}`.

---

## Schritt 9 — Energieausweis abholen (PDF)

Drei Endpoints in dieser Reihenfolge:

```python
# 9.1 Liste aller Final-Zertifikate des Passes
status, body = call("GET", f"/building-passes/{pass_id}/certificates")
# body = {"data": [{"id": 111, "passId": 91, "projectId": 71,
#                   "type": "demand", "variant": "final",
#                   "issueDate": "2026-05-05", "pdf": {...}, ...}, ...]}

cert_id = body["data"][0]["id"]

# 9.2 Detailinfo zu einem bestimmten Zertifikat
status, body = call("GET", f"/certificates/{cert_id}")

# 9.3 PDF herunterladen — Antwort ist application/pdf, nicht JSON
import urllib.request
req = urllib.request.Request(
    f"{BASE}/certificates/{cert_id}/download",
    headers={"Authorization": f"Bearer {TOKEN}"}
)
with urllib.request.urlopen(req) as r, open(f"energieausweis_{cert_id}.pdf", "wb") as f:
    f.write(r.read())
```

cURL für den Download:

```bash
curl -sH "Authorization: Bearer $EG_TOKEN" \
  "$EG_BASE/certificates/$CERT_ID/download" \
  -o energieausweis.pdf
```

---

## Fehlerbehandlung

Alle Fehler kommen in diesem Format zurück:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "status": 400,
    "details": [
      {"path": "data.steps.building_address.houseNumber",
       "message": "Unknown field 'houseNumber' for step 'building_address'"}
    ]
  }
}
```

Wichtig: `details` ist ein **Array** von Feld-Fehlern, nicht ein Objekt.

### Bekannte Error-Codes

| Code | Bedeutung | Typische Auslöser |
|------|-----------|-------------------|
| `VALIDATION_ERROR` | Eingabe-Validierung schlug fehl | Pflichtfeld fehlt, falscher Enum-Wert, falscher Typ, fehlender Query-Parameter |
| `UNKNOWN_FIELD_KEY` | Unbekanntes Feld in einem Step | Schreibfehler, veralteter Feldname (z. B. `houseNumber`) |

`401`/`403` werden ohne `ExternalApiError`-Body geliefert (Token fehlt/falsch bzw. kein Recht).

### Retry-Strategie

- `5xx` → exponentieller Backoff, 3 Versuche.
- `4xx` → **nicht** retryen — die Fehlermeldung verstehen und fixen.
- `429` (falls jemals beobachtet — aktuell kein dokumentiertes Rate-Limiting) → `Retry-After`-Header respektieren.

```python
import time

def call_with_retry(method, path, body=None, max_retries=3):
    for attempt in range(max_retries):
        status, response = call(method, path, body=body)
        if status and 200 <= status < 300:
            return status, response
        if status and 400 <= status < 500:
            # Fachfehler — nicht retryen
            return status, response
        # 5xx oder Netzfehler
        time.sleep(2 ** attempt)
    return status, response
```

---

## Troubleshooting & häufige Fallstricke

| Symptom | Ursache | Lösung |
|---------|---------|--------|
| `400 UNKNOWN_FIELD_KEY: 'houseNumber'` | `houseNumber` als separates Feld geschickt | Hausnummer in `street` integrieren: `"Haydnstraße 59"` |
| `400 VALIDATION_ERROR: type Required` bei GETs | Query-Parameter `?type=` fehlt | An `/requirements`, `/completeness`, `/certificates/status` Query `?type=demand` oder `consumption` anhängen |
| `400 VALIDATION_ERROR` beim Draft | Pflichtfelder fehlen | Über `details`-Array die Pfade lesen, patchen, erneut versuchen |
| Bauteilflächen tauchen nach Create plötzlich auf | LoD2-Auto-Fill griff für die Adresse | Erwartetes Verhalten. Im `source`-Feld `"lod2"` vs. `"user"` unterscheiden |
| Foto-URL in der Response unterscheidet sich von der gesendeten | Server hat das Bild in eigenen S3-Bucket gespiegelt | Erwartetes Verhalten. Verwende die Server-URL für Anzeigen |
| Heizung mit drei Erzeugern wird abgelehnt | `coverage`-Summe ≠ 1.0 / 100% | Summe der `coverage`-Werte aller Heat-Generatoren prüfen |
| Step in Response heißt anders als gesendet | Server-seitige Aliasierung | Beim *Senden* ein Name reicht; beim *Lesen* sind alte+neue Namen sichtbar. Die Tabelle in [Schritt 3](#schritt-3--daten-editieren-patch) verwenden |
| `final/checkout` gibt eine Stripe-URL zurück | So designed — das ist die Bezahlung | `checkoutUrl` an den Kunden weitergeben, nach Bezahlung Submit aufrufen |
| `500 Timeout waiting for workflow ... to get initialized` beim Draft | HTTP-Antwort timeoutet, Workflow läuft im Backend trotzdem | Nicht erneut POSTen — `/certificates/status` pollen, ggf. mehrere Minuten |
| `500 Workflow execution already started` beim Draft | Es läuft schon ein Draft-Job für diesen Pass | `/certificates/status` pollen statt neuen Draft starten |
| Temporal-Failure `getDatabaseInput`/„fetch failed" mit `RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED` | Backend-Bug — interner Service nicht erreichbar; Worker hat nach max. Retries aufgegeben. Pass-Workflow ist auf `failed` und nicht reaktivierbar. | Frischen Pass anlegen und neu versuchen. Bei Reproduzierbarkeit: Pass-ID, Zeitstempel, Activity-Name und Worker-Identity an Enerithm-Support melden. |

### Demo-Aufräumarbeit

Tests legen Pässe an, die in der UI sichtbar bleiben. Eine Konvention wie `passName: "API_PROBE_DELETEME — …"` macht das spätere Aufräumen leicht. Ein DELETE-Endpoint für Pässe ist in der API nicht ausgewiesen — Aufräumen aktuell über die UI.

---

## End-to-End-Python-Skript

Im Projektordner liegt ein lauffähiges Skript `e2e_demo.py`, das den kompletten Workflow von Create bis Draft durchspielt — **ohne** Stripe-Checkout und ohne Submit, weil beide manuelle Aktionen erfordern. Es eignet sich, um:

- die Auth zu verifizieren,
- ein neues Beispielgebäude zu testen,
- den Zustand eines Passes in der Sandbox zu inspizieren,
- als Vorlage für deine eigene Integration.

Aufruf:

```bash
export EG_TOKEN='egapi_…'
python3 e2e_demo.py
```

Siehe [`e2e_demo.py`](./e2e_demo.py) im selben Verzeichnis.

---

## Anhang A — Endpoint-Referenz

| Methode | Pfad | Zweck |
|---------|------|-------|
| GET | `/health` | Smoke-Test (kein Token) |
| GET | `/building-passes` | Pass-Liste |
| GET | `/building-passes/{passId}` | Pass-Detail |
| POST | `/building-passes` | Pass anlegen (ohne Projekt) |
| PATCH | `/building-passes/{passId}` | Pass-Metadaten ändern |
| POST | `/building-passes/{passId}/projects` | Projekt im existierenden Pass |
| POST | `/building-passes/projects` | Pass + Projekt in einem Call (One-Shot) |
| GET | `/building-passes/{passId}/projects` | Aktives Projekt mit Steps |
| PATCH | `/building-passes/{passId}/projects` | Projekt-Daten patchen (Merge) |
| GET | `/building-passes/{passId}/projects/requirements?type=…` | Anforderungs-Status |
| GET | `/building-passes/{passId}/projects/completeness?type=…` | Vollständigkeits-Quote |
| GET | `/requirements/catalog?type=…` | **Kanonischer Anforderungskatalog** |
| POST | `/building-passes/{passId}/projects/steps/building_pictures/{fieldKey}/upload` | Foto-Upload (multipart) |
| GET | `/building-passes/{passId}/projects/certificates/status?type=…` | Aktueller Zert-Status |
| POST | `/building-passes/{passId}/projects/certificates/drafts` | Draft-Vorschau erzeugen |
| POST | `/building-passes/{passId}/projects/certificates/final/checkout` | **Stripe-Bezahlsession** |
| POST | `/building-passes/{passId}/projects/certificates/final/submit` | Final einreichen (nach Bezahlung) |
| GET | `/building-passes/{passId}/certificates` | Liste der Final-Zertifikate |
| GET | `/certificates/{certificateId}` | Zert-Detail |
| GET | `/certificates/{certificateId}/download` | PDF-Download |

---

## Anhang B — Wichtige Step-IDs

Das ist eine Auswahl der ~30 zentralen Steps. Die vollständige Liste mit Pflichtfeldern und allowedValues bekommst du jederzeit aus `/requirements/catalog`.

| Step-ID | Inhalt |
|---------|--------|
| `reason_for_issue` | Anlass: Neubau / Modernisierung-Erweiterung / Vermietung-Verkauf / Aushangpflicht / Sonstiges |
| `building_address` | Adresse + Bundesland + Land |
| `year_of_construction_building` | Baujahr |
| `renovation_after_construction` / `renovation_measures` | Sanierungs-Anlässe + Jahre |
| `number_of_residential_units` | Wohneinheiten |
| `part_of_residential_building` | Ganzes Gebäude / Teil des Wohngebäudes / … |
| `degree_of_attachment_residential_building` | freistehend / einseitig / zweiseitig angebaut |
| `living_area` | Wohnfläche m² |
| `number_of_heated_storeys`, `mean_zone_height` | Geschosse, Raumhöhe |
| `simplified_opaque_element` | Außenwände, Boden, Tür (mit `source: user/lod2`) |
| `construction_opaque_elements` | Wand-/Bodentypen, Keller-Flags |
| `simplified_roof`, `simplified_roof_details`, `roof_construction` | Dach |
| `simplified_transparent_element`, `transparent_share`, `construction_transparent_element` | Fenster |
| `dhw_supply_demand` | Warmwasser zentral/dezentral/mischsystem |
| `dhw_generator_available` | Warmwasser-Erzeuger Flags |
| `heating_generator_data_step` | Wärmeerzeuger-Array (`heatingGenerators[]`) |
| `heating_generator_details_step` | Hydr. Abgleich, Vorlauf-Temperaturen, … |
| `heating_emission_type` | Radiators / Floorheating / Wallheating / Fan_Coil |
| `cooling_system_basic` | Kühlung ja/nein + Untertypen |
| `ventilation_system_basic` | Fensterlüftung / mechanisch (mit/ohne WRG) |
| `renewable_energy_basic` | EE-Nutzung ja/nein, Quellen |
| `building_pictures` | Pflicht-Fotos: `buildingPic`, `nameplatePic` |

---

## Anhang C — Diskrepanzen OpenAPI ↔ Realität

Die unter `/api/core/v1/docs/openapi.json` veröffentlichte Spec stimmt an einigen Stellen nicht mit dem akzeptierten Wire-Format überein. Wenn die Spec und diese Anleitung sich widersprechen, **gilt diese Anleitung** (oder besser: ein eigener Test gegen die Sandbox).

| Thema | OpenAPI sagt | Real akzeptiert / liefert |
|-------|--------------|---------------------------|
| Heizungs-Format | `HeatingGenerator1`, `EnergyCarrier_HeatingGenerator1`, `CoverageHeatingGenerator1`, … | `heatingGenerators: [{type, energyCarrier, coverage, yearOfConstruction}]` (Array) |
| Step-IDs | `dhw_supply`, `type_of_cooling`, `type_of_ventilation`, `renewable_energy` | Bevorzugt `dhw_supply_demand`, `cooling_system_basic`, `ventilation_system_basic`, `renewable_energy_basic` (Server propagiert) |
| Adresse | `street` + `houseNumber` | Hausnummer in `street`; `federalState` + `country` Pflicht |
| Bauteil-Element-Felder | `Flaechenbezeichnung`, `Flaeche` (PascalCase) | Wire-Format: `flaechenbezeichnung`, `flaeche`, `ausrichtung`, `neigung` (lowercase) |
| Query-Parameter `type` | nicht erwähnt | **Pflicht** an `/requirements/catalog`, `/projects/requirements`, `/projects/completeness`, `/projects/certificates/status` |
| Error-Body | `error.details: object` | `error.details: Array<{path, message}>` |
| `final/checkout` | „Create final checkout for active project" | **Erzeugt eine Stripe-Bezahlsession** mit `checkoutUrl` |
| Success-Response-Schemas | meist nicht definiert | konsistent `{data: {...}}` (siehe Schritt 2/3 für genaue Felder) |
| GET `/projects` Response | nicht definiert | Steps liegen unter **doppelter** Verschachtelung `body.data.data.steps` |
| Drafts in `/certificates`-Liste | nicht spezifiziert | Drafts erscheinen **nicht** in der Liste — nur Final-Zertifikate |
| `final/submit`, `/certificates/{id}`, `/certificates/{id}/download` | dokumentiert | **In dieser Anleitung nicht durchgespielt** — Verhalten beruht auf Mustern der übrigen Endpoints |

---

## Anhang D — Glossar

- **Bedarfsausweis (`demand`)** — Energieausweis auf Basis berechneter Energiekennwerte aus Gebäudegeometrie und Anlagentechnik.
- **Verbrauchsausweis (`consumption`)** — Energieausweis auf Basis gemessener Verbrauchswerte (i. d. R. drei Jahre).
- **GEG** — Gebäudeenergiegesetz; rechtliche Grundlage des Energieausweises.
- **Step** — logische Datengruppe innerhalb eines Projekts (z. B. `building_address`).
- **Catalog** — der Anforderungskatalog (`/requirements/catalog`); kanonische Quelle für Pflichtfelder.
- **LoD2** — Level of Detail 2 — Bundesweite 3D-Geometriedatenbank der amtlichen Vermessung. Liefert Bauteilflächen für viele Adressen automatisch.
- **Draft** — kostenlose Vorschau-Variante eines Energieausweises; jederzeit neu erzeugbar, nicht offiziell ausgestellt.
- **Final** — bezahlter, registrierter und signierter Energieausweis als PDF.

---

*Fragen oder Diskrepanzen entdeckt? Diese Anleitung wurde gegen die Staging-Sandbox verifiziert. Endpoints `final/submit` und `/certificates/{id}/download` wurden nicht durchgespielt — Verhalten dort beruht auf den dokumentierten Mustern der übrigen Endpoints.*
