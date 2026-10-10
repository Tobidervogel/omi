#!/bin/sh
# Startet Firestore- und Auth-Emulator mit Sicherung.
#
# Der Firestore-Emulator hält alle Daten im Arbeitsspeicher. Gesichert wird deshalb
# 1. alle SICHERN_ALLE_MINUTEN Minuten über den Emulator-Hub (POST /_admin/export),
# 2. beim sauberen Beenden (--export-on-exit, z. B. "docker compose stop").
# Jede Sicherung ist ein eigener Ordner unter $DATEN/sicherungen. Beim Start wird die
# jüngste vollständige Sicherung geladen; vollständig heißt: die Metadatei, die
# firebase-tools zuletzt schreibt, ist da.
set -eu

SICHERUNGEN="$DATEN/sicherungen"
mkdir -p "$SICHERUNGEN"

juengste_sicherung() {
    # jüngste Metadatei nach Änderungszeit, nicht nach Name: die Sicherung beim
    # Beenden wird beim Start benannt und ist trotzdem die neueste.
    ls -t "$SICHERUNGEN"/*/firebase-export-metadata.json 2>/dev/null | head -n 1 | xargs -r dirname
}

alte_sicherungen_loeschen() {
    ls -dt "$SICHERUNGEN"/*/ 2>/dev/null | tail -n +"$((SICHERUNGEN_BEHALTEN + 1))" | while read -r alt; do
        rm -rf "$alt"
    done
}

IMPORT="$(juengste_sicherung || true)"
STARTZEIT="$(date -u +%Y%m%d-%H%M%S)"
BEIM_BEENDEN="$SICHERUNGEN/beendet-$STARTZEIT"

set -- firebase emulators:start \
    --project "$FIREBASE_PROJECT" \
    --only firestore,auth \
    --config /srv/firebase/firebase.json \
    --export-on-exit "$BEIM_BEENDEN"
if [ -n "$IMPORT" ]; then
    echo "Lade Sicherung $IMPORT"
    set -- "$@" --import "$IMPORT"
else
    echo "Keine Sicherung gefunden, starte mit leerer Datenbank"
fi

"$@" &
EMULATOR=$!

beenden() {
    echo "Beende Emulatoren, sichere nach $BEIM_BEENDEN"
    kill -INT "$EMULATOR" 2>/dev/null || true
    wait "$EMULATOR" || true
    alte_sicherungen_loeschen
    exit 0
}
trap beenden INT TERM

regelmaessig_sichern() {
    # erst warten, bis der Hub antwortet
    until curl -fsS -o /dev/null http://127.0.0.1:4400/emulators; do sleep 2; done
    while true; do
        sleep "$((SICHERN_ALLE_MINUTEN * 60))"
        ZIEL="$SICHERUNGEN/$(date -u +%Y%m%d-%H%M%S)"
        if curl -fsS -X POST -H 'Content-Type: application/json' \
            -d "{\"path\":\"$ZIEL\",\"initiatedBy\":\"sicherung\"}" \
            http://127.0.0.1:4400/_admin/export >/dev/null; then
            echo "Gesichert: $ZIEL"
            alte_sicherungen_loeschen
        else
            echo "Sicherung fehlgeschlagen: $ZIEL" >&2
            rm -rf "$ZIEL"
        fi
    done
}
regelmaessig_sichern &

wait "$EMULATOR"
