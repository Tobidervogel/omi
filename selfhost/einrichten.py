"""Erzeugt selfhost/.env aus .env.example mit echten Zufallswerten.

    python einrichten.py                      PC-Adresse wird geraten
    python einrichten.py --adresse 192.168.0.23

Eine vorhandene .env wird nie überschrieben: Ein neuer Verschlüsselungswert würde alle
gespeicherten Unterhaltungen unlesbar machen.
"""

import argparse
import secrets
import socket
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
LAENGEN = {"OMI_VERSCHLUESSELUNG": 48, "OMI_GATEWAY_SCHLUESSEL": 32, "OMI_TYPESENSE_SCHLUESSEL": 24}


def eigene_adresse() -> str:
    """Adresse im Heimnetz: die, über die der PC ins Netz gehen würde (es wird nichts gesendet)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.168.0.1", 9))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main() -> int:
    parser = argparse.ArgumentParser(description="selfhost/.env anlegen")
    parser.add_argument("--adresse", help="Adresse des PCs im Heimnetz, z. B. 192.168.0.23")
    args = parser.parse_args()

    ziel = HIER / ".env"
    if ziel.exists():
        print(f"{ziel} gibt es schon und bleibt unverändert.")
        return 0
    adresse = args.adresse or eigene_adresse()
    zeilen = []
    for zeile in (HIER / ".env.example").read_text(encoding="utf-8").splitlines():
        name = zeile.split("=", 1)[0]
        if name in LAENGEN:
            zeile = f"{name}={secrets.token_urlsafe(LAENGEN[name])}"
        elif name == "OMI_PC_ADRESSE":
            zeile = f"{name}={adresse}"
        zeilen.append(zeile)
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print(f"{ziel} angelegt. PC-Adresse: {adresse} (in .env änderbar).")
    print("Wichtig: .env enthält den Schlüssel, mit dem die Daten verschlüsselt sind. Mitsichern.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
