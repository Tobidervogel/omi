"""Konto für den Selbstbetrieb (selfhost/) anlegen oder prüfen.

Läuft im Backend-Container gegen die Emulatoren:

    docker compose exec backend python scripts/selfhost_konto.py
    docker compose exec backend python scripts/selfhost_konto.py --neuer-schluessel

Was es tut:
0. legt die Suchsammlungen in Typesense an, falls sie fehlen,
1. legt das Konto im Anmelde-Emulator an (dieselbe Kennung, mit der sich die App über
   "Local development sign-in" anmeldet),
2. setzt den Tarif auf "unlimited" bis 2100 (sonst gelten Omis Gratis-Grenzen),
3. stellt die Sprache auf Deutsch,
4. erzeugt einen Developer-Key mit allen Rechten für recorder.py und zeigt ihn genau
   einmal an. Omi speichert nur eine Prüfsumme; ein verlorener Key lässt sich nicht
   wieder anzeigen, nur neu erzeugen.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UNTIL_2100 = 4102444800  # 2100-01-01 00:00:00 UTC
KEY_NAME = 'recorder.py (Selbstbetrieb)'


def _suche_einrichten() -> None:
    """Typesense-Sammlungen für Unterhaltungen und Erinnerungen anlegen (idempotent)."""
    import json

    from utils.conversations.search import client as typesense
    from utils.memory.atom_keyword_index import ensure_ledger_keyword_schema, ensure_memories_collection

    schema = json.loads((Path(__file__).resolve().parents[1] / 'typesense' / 'conversations.schema').read_text())
    try:
        typesense.collections[schema['name']].retrieve()
        print(f"Suche: Sammlung {schema['name']} vorhanden")
    except Exception:
        typesense.collections.create(schema)
        print(f"Suche: Sammlung {schema['name']} angelegt")
    ensure_memories_collection()
    ensure_ledger_keyword_schema()
    print('Suche: Sammlung für Erinnerungen bereit')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--uid', default=os.getenv('OMI_KONTO', 'tobi'), help='Konto-Kennung (Standard: tobi)')
    parser.add_argument('--name', default='Tobi', help='Anzeigename')
    parser.add_argument('--sprache', default='de', help='Sprache für Zusammenfassungen (Standard: de)')
    parser.add_argument(
        '--neuer-schluessel',
        action='store_true',
        help='auch dann einen Developer-Key erzeugen, wenn es schon einen gibt',
    )
    args = parser.parse_args(argv)

    if not os.getenv('FIREBASE_AUTH_EMULATOR_HOST') or not os.getenv('FIRESTORE_EMULATOR_HOST'):
        print('Abbruch: Dieses Skript ist nur für den Selbstbetrieb mit Emulatoren gedacht.', file=sys.stderr)
        return 2

    import firebase_admin
    from firebase_admin import auth

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={'projectId': os.getenv('FIREBASE_PROJECT_ID', 'demo-omi-local')})

    import database.dev_api_key as dev_api_key_db
    import database.users as users_db
    from database._client import db
    from utils.scopes import AVAILABLE_SCOPES
    from utils.subscription import get_plan_limits
    from config.plan_catalog_generated import PlanType

    _suche_einrichten()

    uid = args.uid.strip()
    try:
        auth.get_user(uid)
        print(f'Konto {uid}: vorhanden')
    except auth.UserNotFoundError:
        auth.create_user(uid=uid, email=f'{uid}@local.test', email_verified=True, display_name=args.name)
        print(f'Konto {uid}: angelegt')

    db.collection('users').document(uid).set({'name': args.name}, merge=True)
    users_db.update_user_subscription(
        uid,
        {
            'plan': PlanType.unlimited.value,
            'status': 'active',
            'current_period_end': UNTIL_2100,
            'cancel_at_period_end': False,
        },
    )
    subscription = users_db.get_user_valid_subscription(uid)
    if subscription is None or subscription.plan != PlanType.unlimited:
        print('Fehler: Tarif konnte nicht gesetzt werden.', file=sys.stderr)
        return 1
    limits = get_plan_limits(subscription.plan)
    chat = os.getenv('NEO_CHAT_QUESTIONS_PER_MONTH') or limits.chat_questions_per_month
    print(f'Tarif: {subscription.plan.value}, Zuhören unbegrenzt, Chatfragen je Monat: {chat}')

    users_db.set_user_language_preference(uid, args.sprache)
    print(f'Sprache: {args.sprache}')

    existing = [key for key in dev_api_key_db.get_dev_keys_for_user(uid) if key.name == KEY_NAME]
    if existing and not args.neuer_schluessel:
        print(
            f'Developer-Key für recorder.py gibt es schon ({len(existing)}x, beginnt mit '
            f'{existing[0].key_prefix}...). Neu erzeugen mit --neuer-schluessel.'
        )
        return 0

    raw_key, _ = dev_api_key_db.create_dev_key(uid, KEY_NAME, scopes=list(AVAILABLE_SCOPES))
    print()
    print('Neuer Developer-Key (wird nur jetzt angezeigt, in pc/omi_key.txt eintragen):')
    print(raw_key)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
