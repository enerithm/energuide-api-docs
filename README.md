# EnerGuide API — Developer Docs

Dokumentation und Beispielcode für die **EnerGuide External API** von [Enerithm](https://enerithm.com).

Die API ermöglicht es, GEG-konforme Energieausweise (Bedarfs- und Verbrauchsausweis) vollständig programmatisch zu erstellen — vom Anlegen eines Gebäudepasses bis zum signierten PDF.

---

## Inhalt dieses Repos

| Datei | Beschreibung |
|---|---|
| [`ENERGUIDE_API_GUIDE.md`](./ENERGUIDE_API_GUIDE.md) | Vollständige Schritt-für-Schritt-Anleitung für Integratoren |
| [`examples/e2e_demo.py`](./examples/e2e_demo.py) | End-to-End-Demo: kompletter Workflow von Auth bis Vollständigkeitsprüfung |

---

## Quickstart

### 1. Token besorgen

Im [EnerGuide-Portal](https://energuide.de) einen API-Token generieren und als Umgebungsvariable setzen:

```bash
export EG_TOKEN='egapi_...'
```

> **Achtung:** Token niemals in Code oder Repos einchecken.

### 2. Demo-Skript ausführen

```bash
# Dependencies installieren
pip install requests

# Demo gegen Staging-Umgebung ausführen
python examples/e2e_demo.py
```

Das Skript legt automatisch einen Gebäudepass und ein Projekt an, befüllt die Pflichtfelder und prüft die Vollständigkeit. Vorschau und Checkout können optional aktiviert werden — Details im Skript-Header.

### 3. Vollständige Anleitung lesen

→ [`ENERGUIDE_API_GUIDE.md`](./ENERGUIDE_API_GUIDE.md)

---

## API-Umgebungen

| Umgebung | Host |
|---|---|
| Staging | `https://api.staging.enerithm.com/api/core/v1` |
| Produktion | Über Account / Support erhältlich |

---

## Kontakt & Support

- Website: [enerithm.com](https://enerithm.de)
- Fragen zur API: [felix@enerithm.com](mailto:felix@enerithm.com)
