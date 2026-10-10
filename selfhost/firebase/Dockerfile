# Firestore- und Auth-Emulator für den Selbstbetrieb (siehe selfhost/README.md).
# firebase-tools braucht Node und für den Firestore-Emulator Java 21.
ARG BASE_IMAGE=node:22-trixie-slim
FROM ${BASE_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Gleiche Version wie im package.json des Omi-Repos.
ARG FIREBASE_TOOLS_VERSION=15.22.0
RUN npm install -g --no-fund --no-audit "firebase-tools@${FIREBASE_TOOLS_VERSION}"

# Den Firestore-Emulator schon beim Bauen laden, damit der Start ohne Internet geht.
RUN firebase setup:emulators:firestore

WORKDIR /srv/firebase
COPY firebase.json start.sh ./
RUN chmod +x start.sh

ENV FIREBASE_PROJECT=demo-omi-local \
    DATEN=/daten \
    SICHERN_ALLE_MINUTEN=10 \
    SICHERUNGEN_BEHALTEN=48

EXPOSE 8085 9099 4400
CMD ["./start.sh"]
