# Omi im Selbstbetrieb

Omi läuft hier auf dem eigenen PC statt in Omis Cloud: Backend, Datenbank, Anmeldung, Suche und das
Sprachmodell. Gedacht für eine Person (Tobi) im Heimnetz. Grundlage ist Omis eigener Aufbau für die
lokale Entwicklung (`scripts/dev-harness`): Firestore und Anmeldung als Emulatoren, Ablage auf der Platte.

```
Recorder ──SD/WLAN──► PC: recorder.py (Whisper, Stimmen) ──► Omi-Backend :8000 ──► LLM-Gateway ──► Ollama (Sprachmodell)
                                                              │
Handy (App) ─────────────── Anmeldung :9099, Daten :8000 ─────┘   Firestore-Emulator, Redis, Typesense, Pusher, Jobs
```

## Was du brauchst

- Windows 10 22H2 (64 Bit) mit WSL 2 und **Docker Desktop** (für private Nutzung kostenlos).
- **Ollama für Windows** (kostenlos) für das Sprachmodell. Es nutzt die Grafikkarte von selbst.
- Rund 15 GB freien Platz: Images rund 5 GB, Modelle rund 3 GB, dazu die Daten.
- 16 GB Arbeitsspeicher reichen: Omi braucht rund 2 GB, das Modell mit 16 384 Token Kontext rund 5 GB.
- Python (ist für `recorder.py` schon da).

## Einmal einrichten

1. **Docker Desktop** installieren (bei der Installation „WSL 2“ wählen), neu starten, Docker Desktop
   öffnen und unter Einstellungen „Start Docker Desktop when you sign in“ anhaken.
2. **Ollama** installieren (ollama.com). Danach in diesem Ordner:
   ```
   ollama-modelle.bat
   ```
   Lädt `qwen3:4b-instruct` (2,5 GB, passt auf die GTX 980) und `qwen3-embedding:0.6b` und legt die
   Namen an, nach denen Omi fragt (`gpt-6-luna`, `gpt-5-nano`, `text-embedding-3-large`).
3. **Einstellungen erzeugen:**
   ```
   python einrichten.py --adresse 192.168.0.23
   ```
   Statt `192.168.0.23` die Adresse des PCs im Heimnetz (`ipconfig`). Das legt `.env` mit zufälligen
   Geheimnissen an. **`.env` gut aufheben:** Darin steht der Schlüssel, mit dem die Daten verschlüsselt sind.
4. **Bauen und starten** (das erste Bauen dauert 10 bis 20 Minuten):
   ```
   docker compose build
   docker compose up -d
   docker compose ps
   ```
   Alle Dienste müssen „running“ zeigen, `firebase` und `llm-gateway` zusätzlich „healthy“.
5. **Konto anlegen** (Tarif ohne Grenzen, Sprache Deutsch, Schlüssel für `recorder.py`):
   ```
   docker compose exec backend python scripts/selfhost_konto.py
   ```
   Die letzte Zeile ist der Developer-Key (`omi_dev_...`). Er wird nur dieses eine Mal angezeigt.
   Ihn in `A:\Recorder\omi_key.txt` speichern (eine Zeile, nichts sonst). Verloren? Mit
   `--neuer-schluessel` einen neuen erzeugen.
6. **`recorder.py` prüfen:** Es spricht von selbst `http://localhost:8000` an.
   ```
   A:\Recorder\.venv\Scripts\python.exe A:\Recorder\recorder.py omi-pruefen
   ```
   Erwartet: „Schluessel gilt, 0 Unterhaltung(en) gelesen“.
7. **Messlauf** (siehe unten), dann entscheiden: lokal oder Cloud-Rückfall.
8. **Firewall:** Nur PC und Handy sollen Port 8000 und 9099 erreichen (siehe „Sicherheit“).
9. **Sicherung einrichten** (siehe unten).

## Messlauf: reicht der PC?

```
docker compose exec backend python scripts/selfhost_messlauf.py --schluessel omi_dev_... --stunden-pro-tag 2
```

Er misst die Geschwindigkeit des Modells, schickt ein erfundenes Gespräch von gut 3 Minuten durch die
echte Omi-Verarbeitung und zählt die Modellaufrufe. Daraus rechnet er die Rechenzeit je 10 Minuten
Gespräch und die Kosten in der Cloud hoch. Der Bericht steht danach in `daten\backend\messlauf\`.
Bitte ins Recorder-LiveUp-Repo legen (`brain/Notizen`), damit er nicht verloren geht.

Faustregel: Die tägliche Rechenzeit muss deutlich unter der Zeit liegen, in der der PC läuft, und
Titel, Zusammenfassung und Aufgaben im Bericht müssen brauchbar sein.

## Cloud-Rückfall

Reicht das lokale Modell nicht, übernimmt OpenAI nur die Modellaufrufe; alles andere bleibt zu Hause.
Die Transkripte gehen dann an OpenAI. In `.env`:

```
OMI_LLM_URL=https://api.openai.com/v1
OMI_LLM_SCHLUESSEL=sk-...        (eigener API-Schlüssel, getrennt von ChatGPT Plus)
OMI_LLM_ZEITFAKTOR=1
```

Dann `docker compose up -d`. Omi fragt dort dieselben Modelle an wie in seiner Cloud (`gpt-6-luna`,
`gpt-5-nano`). Was das kostet, zeigt der Messlauf (Spalte „bei OpenAI“).

Mit der RTX 3080 geht auch ein größeres lokales Modell: `ollama-modelle.bat <modell>`. Geprüft ist nur
`qwen3:4b-instruct`.

## Zeitfaktor

Omis Zeitgrenzen sind für schnelle Cloud-Modelle gemacht (z. B. 15 s bis zur ersten Antwort). Ein
lokales Modell braucht für dieselbe Arbeit viel länger; jede Grenze, die zuschlägt, kostet eine
Zusammenfassung oder die Erinnerungen. `OMI_LLM_ZEITFAKTOR` in `.env` verlängert alle Grenzen für
Modellaufrufe zugleich (Standard 30). Steht im Protokoll (`docker compose logs backend`)
`APITimeoutError` oder `TimeoutError`, den Faktor erhöhen und `docker compose up -d`. In der Cloud 1.

## Täglicher Betrieb

- Docker Desktop startet mit Windows, die Dienste starten von selbst wieder (`restart: unless-stopped`).
- Läuft der PC nicht, sammelt `recorder.py` die Aufträge in `omi_outbox\` und schickt sie später.
- Protokolle: `docker compose logs -f backend` (oder `llm-gateway`, `firebase`, `jobs`).
- Stoppen: `docker compose stop` (sichert die Datenbank beim Beenden). Nicht `docker compose down -v`.
- Aktualisieren: `git pull`, `docker compose build`, `docker compose up -d`.

## Sicherung

Die Datenbank ist Omis Firestore-**Emulator**. Er hält alles im Arbeitsspeicher und schreibt alle
10 Minuten und beim Beenden eine Sicherung nach `daten\firebase\sicherungen\` (die letzten 48 bleiben).
Stürzt der PC ab, fehlen höchstens die letzten 10 Minuten in Omi. Transkripte und Ton liegen davon
unabhängig im Brain und auf dem NAS.

Aufs NAS sichert `sichern.bat`. In der Aufgabenplanung täglich um 3:30 Uhr eintragen:

```
Programm:   A:\omi\selfhost\sichern.bat
Argumente:  \\jacobnas\JacobNAS\Tobi\Omi-Sicherung
```

Es stoppt Omi kurz, kopiert `daten` (ohne Modelle und Zwischenspeicher) und `.env` und startet wieder.
Zurückholen: Omi stoppen, `daten` und `.env` vom NAS zurückkopieren, `docker compose up -d`.

## Sicherheit

Die Anmeldung läuft über den Emulator; er prüft keine Unterschriften. Wer im Heimnetz Port 8000 oder
9099 des PCs erreicht, kann sich als jedes Konto ausgeben. Deshalb in PowerShell (als Administrator)
nur das Handy zulassen (`192.168.0.50` durch die Adresse des Handys ersetzen):

```
New-NetFirewallRule -DisplayName "Omi Handy" -Direction Inbound -Protocol TCP -LocalPort 8000,9099 -RemoteAddress 192.168.0.50 -Action Allow
```

Danach unter „Windows Defender Firewall mit erweiterter Sicherheit → Eingehende Regeln“ nachsehen, ob
Docker Desktop eine eigene Regel „Zulassen“ für alle Adressen angelegt hat (sie heißt meist wie ein
Docker-Programm, z. B. „Docker Desktop Backend“). Gibt es eine, unter „Bereich → Remote-IP-Adresse“ auch
dort nur das Handy eintragen. Geprüft ist das nicht; ob Docker Desktop eine Regel anlegt, hängt von der
Installation ab. Von außerhalb des Heimnetzes ist nichts erreichbar, solange der Router keine Ports
weiterleitet; unterwegs später über WireGuard.

## Was gegenüber Omis Cloud fehlt

Nichts davon fällt stillschweigend weg:

- Websuche im Chat (Perplexity), Push-Mitteilungen, Vorlesen, Kalender, Notion und andere Integrationen,
  Telefonate, Ortsnamen zu Unterhaltungen, Gefühlsanalyse, Omis App-Marktplatz, Support-Chat.
- Anmeldung mit Google oder Apple: Die App meldet sich über den lokalen Server an.
- Live-Spracherkennung im Backend: Tobis Weg ist `recorder.py`. Für Live-Ton über die App gibt es dort
  die Einstellung „Local Whisper“ (eigener Whisper-Server auf dem PC).
- Ergebnisse hängen am lokalen Modell und sind schwächer als bei Omis Cloud-Modellen.

## Was am Omi-Code geändert ist

- `backend/database/local_vector_index.py`: Vektorsuche in einer SQLite-Datei statt Pinecone
  (`OMI_LOCAL_VECTOR_DB`). Tests: `backend/tests/unit/test_local_vector_index.py`.
- `backend/utils/llm/timeout_scale.py`: `OMI_LLM_TIMEOUT_SCALE` verlängert alle Zeitgrenzen für
  Modellaufrufe in Backend und Gateway (lokale Modelle sind langsamer). Ohne die Variable ändert sich
  nichts. Tests: `backend/tests/unit/test_llm_timeout_scale.py`.
- `backend/utils/llm/model_config.py` und `working_observations.py`: `OMI_LLM_SCHEMA_FEATURES=memory_l1`
  lässt das Modell die Erinnerungen in Omis Schema schreiben (Ollama erzwingt es). Ohne das schrieb
  `qwen3:4b-instruct` ein JSON, das Omi nicht lesen konnte, und es entstand keine einzige Erinnerung.
  Ohne die Variable ändert sich nichts. Tests: `backend/tests/unit/test_llm_schema_features.py`.
- `backend/scripts/selfhost_konto.py`, `backend/scripts/selfhost_messlauf.py`,
  `backend/scripts/selfhost_beispiel.json`: Konto und Messlauf.
- `selfhost/`: Compose, Emulator-Image mit Sicherung, Jobs, Skripte, diese Anleitung.

## Was geprüft ist

Geprüft in der Cloud-Umgebung von Claude (Linux, Docker, 4 CPU-Kerne, ohne Grafikkarte) am 10.10.2026:

- Alle Dienste starten mit diesem Compose (Backend, Gateway, Pusher, Emulatoren, Redis, Typesense, Ollama
  im Container).
- `selfhost_konto.py` legt Konto, Tarif, Sprache und Developer-Key an.
- Ein Gespräch über `POST /v1/dev/user/conversations/from-segments` wird mit `qwen3:4b-instruct`
  vollständig verarbeitet: deutscher Titel, gegliederte Zusammenfassung, Aufgaben.
- Omis Unit-Tests für Gateway, Modellkonfiguration und Vektorsuche bestehen mit den Änderungen.

Nicht geprüft, weil hier kein Windows, keine Grafikkarte und kein NAS ist: Docker Desktop, Ollama für
Windows, die GTX 980, `ollama-modelle.bat`, `sichern.bat`, die Firewall-Regel und die Handy-App.
