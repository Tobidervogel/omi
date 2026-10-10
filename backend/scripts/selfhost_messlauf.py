"""Messlauf für den Selbstbetrieb (selfhost/): reicht das Sprachmodell auf diesem PC?

    docker compose exec backend python scripts/selfhost_messlauf.py --schluessel omi_dev_...
    docker compose exec backend python scripts/selfhost_messlauf.py --schluessel omi_dev_... --wiederholen 3

Misst dreierlei:
1. das Modell direkt: wie viele Token je Sekunde es liest und schreibt,
2. eine echte Omi-Verarbeitung: ein erfundenes Gespräch (scripts/selfhost_beispiel.json) geht wie bei
   recorder.py über die Developer-API hinein; gemessen wird, wie lange es dauert und was herauskommt,
3. die Modellaufrufe dieser Verarbeitung aus Omis Verbrauchserfassung (llm_gateway_attempts): Anzahl,
   Token und was dieselben Aufrufe bei OpenAI kosten würden (Omis eigene Preistabelle).

Daraus wird auf 10 Minuten Gespräch und auf einen Monat hochgerechnet. Der Bericht landet als Markdown
unter /daten/messlauf/ (auf dem PC: selfhost/daten/backend/messlauf/) und auf dem Bildschirm.
Das Beispielgespräch bleibt danach als Unterhaltung in Omi stehen; es ist als Messlauf erkennbar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

BEISPIEL = Path(__file__).resolve().with_name('selfhost_beispiel.json')
BACKEND = os.getenv('OMI_MESSLAUF_BACKEND', 'http://127.0.0.1:8000')


def _zahl(wert: float, stellen: int = 1) -> str:
    return f'{wert:,.{stellen}f}'.replace(',', ' ').replace('.', ',')


def _dauer(sekunden: float) -> str:
    minuten, rest = divmod(int(round(sekunden)), 60)
    return f'{minuten} min {rest} s' if minuten else f'{rest} s'


def modell_direkt(text: str) -> dict:
    """Ein Aufruf mit langem Text, gestreamt: Zeit bis zum ersten Token = Lesen, danach = Schreiben."""
    base = os.environ['OPENAI_BASE_URL'].rstrip('/')
    nonce = uuid.uuid4().hex  # verhindert, dass ein Zwischenspeicher das Lesen abkürzt
    body = {
        'model': 'gpt-6-luna',
        'stream': True,
        'stream_options': {'include_usage': True},
        'max_tokens': 200,
        'messages': [
            {'role': 'system', 'content': f'Messlauf {nonce}. Antworte auf Deutsch.'},
            {'role': 'user', 'content': f'Fasse dieses Gespräch in etwa 150 Wörtern zusammen:\n\n{text}'},
        ],
    }
    headers = {'Authorization': f"Bearer {os.getenv('OPENAI_API_KEY', '')}"}
    start = time.monotonic()
    erstes = None
    usage = {}
    with httpx.stream('POST', f'{base}/chat/completions', json=body, headers=headers, timeout=3600) as res:
        res.raise_for_status()
        for line in res.iter_lines():
            if not line.startswith('data: ') or line == 'data: [DONE]':
                continue
            chunk = json.loads(line[6:])
            if erstes is None and chunk.get('choices') and chunk['choices'][0].get('delta', {}).get('content'):
                erstes = time.monotonic()
            if chunk.get('usage'):
                usage = chunk['usage']
    ende = time.monotonic()
    erstes = erstes or ende
    lesen = max(erstes - start, 1e-6)
    schreiben = max(ende - erstes, 1e-6)
    eingabe = int(usage.get('prompt_tokens') or 0)
    ausgabe = int(usage.get('completion_tokens') or 0)
    return {
        'eingabe_token': eingabe,
        'ausgabe_token': ausgabe,
        'lesen_s': lesen,
        'schreiben_s': schreiben,
        'lesen_token_je_s': eingabe / lesen,
        'schreiben_token_je_s': max(ausgabe - 1, 0) / schreiben,
    }


def gespraech(wiederholen: int) -> tuple[list[dict], float, int]:
    daten = json.loads(BEISPIEL.read_text(encoding='utf-8'))
    segmente, versatz = [], 0.0
    for _ in range(wiederholen):
        for wer, start, ende, text in daten['segmente']:
            segmente.append(
                {
                    'text': text,
                    'start': round(start + versatz, 2),
                    'end': round(ende + versatz, 2),
                    'speaker': 'SPEAKER_00' if wer == 'Tobi' else 'SPEAKER_01',
                    'is_user': wer == 'Tobi',
                }
            )
        versatz = segmente[-1]['end'] + 2.0
    woerter = sum(len(s['text'].split()) for s in segmente)
    return segmente, segmente[-1]['end'], woerter


def verbrauch(uid: str, seit: str) -> list[dict]:
    from database._client import db

    zeilen = []
    for doc in db.collection('llm_gateway_attempts').where('user_uid', '==', uid).stream():
        d = doc.to_dict()
        if str(d.get('occurred_at', '')) >= seit:
            zeilen.append(d)
    return zeilen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Messlauf für den Selbstbetrieb')
    parser.add_argument('--schluessel', default=os.getenv('OMI_SCHLUESSEL'), help='Developer-Key (omi_dev_...)')
    parser.add_argument('--wiederholen', type=int, default=1, help='Beispielgespräch n-mal hintereinander')
    parser.add_argument('--stunden-pro-tag', type=float, default=2.0, help='Gespräch je Tag für die Hochrechnung')
    parser.add_argument('--ohne-modell-direkt', action='store_true', help='Schritt 1 auslassen')
    args = parser.parse_args(argv)
    if not args.schluessel:
        parser.error('--schluessel fehlt')

    import firebase_admin
    import database.dev_api_key as dev_api_key_db

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={'projectId': os.getenv('FIREBASE_PROJECT_ID', 'demo-omi-local')})
    kontext = dev_api_key_db.get_api_key_auth_result(args.schluessel).context
    if not kontext:
        print('Der Schlüssel ist diesem Backend unbekannt.', file=sys.stderr)
        return 2
    uid = kontext['user_id']

    jetzt = datetime.now(timezone.utc)
    bericht = [
        f'# Messlauf {jetzt.astimezone():%d.%m.%Y %H:%M}',
        '',
        f"Sprachmodell: `gpt-6-luna` über `{os.getenv('OPENAI_BASE_URL')}`, "
        f"Zeitfaktor {os.getenv('OMI_LLM_TIMEOUT_SCALE', '1')}.",
        '',
    ]
    ergebnis: dict = {'zeit': jetzt.isoformat(), 'llm_url': os.getenv('OPENAI_BASE_URL')}
    segmente, dauer_audio, woerter = gespraech(args.wiederholen)

    if not args.ohne_modell_direkt:
        print('1/3 Modell direkt ...', flush=True)
        direkt = modell_direkt(' '.join(s['text'] for s in segmente[: len(segmente) // args.wiederholen] * 2))
        ergebnis['modell_direkt'] = direkt
        bericht += [
            '## Modell direkt',
            '',
            f"- Lesen: {direkt['eingabe_token']} Token in {_zahl(direkt['lesen_s'])} s = "
            f"**{_zahl(direkt['lesen_token_je_s'])} Token/s**",
            f"- Schreiben: {direkt['ausgabe_token']} Token in {_zahl(direkt['schreiben_s'])} s = "
            f"**{_zahl(direkt['schreiben_token_je_s'])} Token/s**",
            '',
        ]

    print('2/3 Omi-Verarbeitung (kann mit lokalem Modell viele Minuten dauern) ...', flush=True)
    seit = datetime.now(timezone.utc).isoformat()
    auftrag = {
        'transcript_segments': segmente,
        'language': 'de',
        'source': 'external_integration',
        'started_at': (jetzt - timedelta(seconds=dauer_audio + 60)).isoformat(),
        'client_session_id': f'messlauf-{jetzt:%Y%m%d-%H%M%S}',
    }
    start = time.monotonic()
    antwort = httpx.post(
        f'{BACKEND}/v1/dev/user/conversations/from-segments',
        json=auftrag,
        headers={'Authorization': f'Bearer {args.schluessel}'},
        timeout=7200,
    )
    dauer = time.monotonic() - start
    ergebnis['verarbeitung'] = {'http': antwort.status_code, 'dauer_s': dauer, 'antwort': antwort.text[:500]}
    bericht += [
        '## Omi-Verarbeitung',
        '',
        f'- Gespräch: {_dauer(dauer_audio)}, {len(segmente)} Sätze, {woerter} Wörter '
        f'(Beispielgespräch x{args.wiederholen})',
        f'- Antwort: HTTP {antwort.status_code} nach **{_dauer(dauer)}**',
    ]
    if antwort.status_code == 200:
        unterhaltung_id = antwort.json()['id']
        u = httpx.get(
            f'{BACKEND}/v1/dev/user/conversations/{unterhaltung_id}',
            headers={'Authorization': f'Bearer {args.schluessel}'},
            timeout=60,
        ).json()
        s = u.get('structured') or {}
        aufgaben = [a.get('description') for a in s.get('action_items') or []]
        ergebnis['unterhaltung'] = {'id': unterhaltung_id, 'titel': s.get('title'), 'aufgaben': aufgaben}
        bericht += [
            f"- Titel: {s.get('title') or '(keiner)'}",
            f"- Zusammenfassung: {(s.get('overview') or '(keine)')[:600]}",
            f'- Aufgaben ({len(aufgaben)}): ' + ('; '.join(a for a in aufgaben if a) or '(keine)'),
        ]
    else:
        bericht.append(f'- Fehler: `{antwort.text[:300]}`')
    bericht.append('')

    print('3/3 Verbrauch ...', flush=True)
    time.sleep(5)  # das Gateway schreibt seine Erfassung nachgelagert
    zeilen = verbrauch(uid, seit)
    je_funktion: dict[str, dict] = {}
    for z in zeilen:
        f = je_funktion.setdefault(
            str(z.get('feature') or z.get('api_surface')), {'aufrufe': 0, 'eingabe': 0, 'ausgabe': 0, 'kosten': 0}
        )
        f['aufrufe'] += 1
        f['eingabe'] += int(z.get('prompt_tokens') or 0)
        f['ausgabe'] += int(z.get('output_tokens') or 0)
        f['kosten'] += int(z.get('estimated_cost_micro_usd') or 0)
    summe = {k: sum(f[k] for f in je_funktion.values()) for k in ('aufrufe', 'eingabe', 'ausgabe', 'kosten')}
    ergebnis['verbrauch'] = {'je_funktion': je_funktion, 'summe': summe}
    bericht += [
        '## Modellaufrufe dieser Verarbeitung',
        '',
        '| Funktion | Aufrufe | Eingabe-Token | Ausgabe-Token | bei OpenAI (US-Cent) |',
        '|---|---|---|---|---|',
    ]
    for name, f in sorted(je_funktion.items()):
        bericht.append(
            f"| {name} | {f['aufrufe']} | {f['eingabe']} | {f['ausgabe']} | {_zahl(f['kosten'] / 10_000, 3)} |"
        )
    bericht += [
        f"| **zusammen** | {summe['aufrufe']} | {summe['eingabe']} | {summe['ausgabe']} | "
        f"{_zahl(summe['kosten'] / 10_000, 3)} |",
        '',
        'Kosten nach Omis Preistabelle (`llm_gateway/config/cost_rate_cards.yaml`); Einbettungen sind dort ohne Preis.',
        '',
    ]

    if antwort.status_code == 200 and dauer_audio > 0:
        faktor = 600 / dauer_audio
        tag = args.stunden_pro_tag * 6  # 10-Minuten-Stücke je Tag
        cent_10 = summe['kosten'] / 10_000 * faktor
        ergebnis['hochrechnung'] = {
            'je_10_min_s': dauer * faktor,
            'je_10_min_token': (summe['eingabe'] + summe['ausgabe']) * faktor,
            'je_10_min_cent': cent_10,
        }
        bericht += [
            '## Hochrechnung',
            '',
            f'- Je 10 Minuten Gespräch: rund {_dauer(dauer * faktor)} Rechenzeit, '
            f"{_zahl((summe['eingabe'] + summe['ausgabe']) * faktor, 0)} Token, "
            f'in der Cloud {_zahl(cent_10, 2)} US-Cent',
            f'- Bei {_zahl(args.stunden_pro_tag)} Stunden Gespräch am Tag: lokal rund '
            f'{_dauer(dauer * faktor * tag)} Rechenzeit täglich; in der Cloud rund '
            f'{_zahl(cent_10 * tag * 30 / 100, 2)} US-Dollar im Monat',
            '- Lokal geht es, wenn die tägliche Rechenzeit deutlich unter 24 Stunden bleibt und die Ergebnisse '
            'oben brauchbar sind. Die Verarbeitung läuft der Reihe nach; recorder.py wartet.',
            '',
        ]

    text = '\n'.join(bericht)
    ziel = Path(os.getenv('OMI_HARNESS_STATE_ROOT', '/daten')) / 'messlauf'
    ziel.mkdir(parents=True, exist_ok=True)
    name = f'messlauf-{jetzt.astimezone():%Y%m%d-%H%M%S}'
    (ziel / f'{name}.md').write_text(text + '\n', encoding='utf-8')
    (ziel / f'{name}.json').write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print()
    print(text)
    print(f'Gespeichert: {ziel / name}.md')
    return 0 if antwort.status_code == 200 else 1


if __name__ == '__main__':
    raise SystemExit(main())
