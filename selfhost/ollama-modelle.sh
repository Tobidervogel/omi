#!/bin/sh
# Wie ollama-modelle.bat, für Ollama im Container (docker compose --profile ollama):
#   docker compose exec ollama sh /selfhost/ollama-modelle.sh [modell] [kontext]
set -e
MODELL=${1:-qwen3:4b-instruct}
KONTEXT=${2:-16384}
EINBETTUNG=qwen3-embedding:0.6b
ollama pull "$MODELL"
ollama pull "$EINBETTUNG"
printf 'FROM %s\nPARAMETER num_ctx %s\n' "$MODELL" "$KONTEXT" > /tmp/omi-modell.Modelfile
ollama create gpt-6-luna -f /tmp/omi-modell.Modelfile
ollama create gpt-5-nano -f /tmp/omi-modell.Modelfile
ollama cp "$EINBETTUNG" text-embedding-3-large
rm /tmp/omi-modell.Modelfile
echo "Fertig: gpt-6-luna und gpt-5-nano = $MODELL mit $KONTEXT Token, text-embedding-3-large = $EINBETTUNG"
ollama list
