#!/bin/sh
# Omis geplante Hintergrundjobs. In Omis Cloud starten Cloud Scheduler und Cloud Run Jobs sie
# (backend/deploy/scheduler/jobs.yaml), hier diese Schleife im Container "jobs":
#   alle 15 Minuten  modal/job.py                     Tageszusammenfassung und Erinnerungen
#   jede Stunde      modal/memory_maintenance_job.py  Pflege der Erinnerungen
# Ein fehlgeschlagener Lauf hält die Schleife nicht an; er steht im Log ("docker compose logs jobs").
cd /app || exit 1
naechste_pflege=0
while true; do
    python modal/job.py || echo "jobs: modal/job.py fehlgeschlagen"
    if [ "$(date +%s)" -ge "$naechste_pflege" ]; then
        MEMORY_CANONICAL_MAINTENANCE_ENABLED=true python modal/memory_maintenance_job.py \
            || echo "jobs: modal/memory_maintenance_job.py fehlgeschlagen"
        naechste_pflege=$(( $(date +%s) + 3600 ))
    fi
    sleep 900
done
