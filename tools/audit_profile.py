"""Extract the pinned card facts from CardDefs.xml; never infer executable effects.

Reproduce: download manifest.cardDataSource.url, verify sha256, then run
python3 tools/audit_profile.py outputs/CardDefs-24118.xml
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'af94b04fdff91a1900f4adfc873d89c76aa298cd'
URL = f'https://raw.githubusercontent.com/HearthSim/hsdata/{REVISION}/CardDefs.xml'
PROFILE = 'wild-11.0.0.24118-subset'
KEYWORDS = {
    'TAUNT',
    'CHARGE',
    'RUSH',
    'WINDFURY',
    'DIVINE_SHIELD',
    'STEALTH',
    'IMMUNE',
    'POISONOUS',
    'LIFESTEAL',
}


def extract(path, ids):
    raw = Path(path).read_bytes()
    root = ET.fromstring(raw)
    assert root.get('build') == '24118'
    entities = {e.get('CardID'): e for e in root}
    facts = []
    for cid in ids:
        entity = entities[cid]
        tags = {t.get('name'): t for t in entity.findall('Tag')}

        def number(name, default=0):
            return int(tags[name].get('value')) if name in tags else default

        def loc(name):
            return tags[name].findtext('enUS', '') if name in tags else ''

        kind = {4: 'MINION', 5: 'SPELL', 7: 'WEAPON', 10: 'HERO_POWER'}[
            number('CARDTYPE')
        ]
        stats = dict(manaCost=number('COST'))
        if kind == 'MINION':
            stats.update(attack=number('ATK'), health=number('HEALTH'))
        if kind == 'WEAPON':
            stats.update(attack=number('ATK'), durability=number('DURABILITY'))
        keywords = sorted(k for k in KEYWORDS if number(k))
        if number('SPELLPOWER'):
            keywords.append('SPELL_DAMAGE')
        # Normalize rendering markup/placeholders, never paraphrase card rules.
        text = re.sub(
            r'\s+',
            ' ',
            re.sub(r'<[^>]+>', '', loc('CARDTEXT'))
            .replace('[x]', '')
            .replace('_', ' ')
            .replace('$', '')
            .replace('#', ''),
        ).strip()
        facts.append(
            dict(
                cardId=cid,
                name=loc('CARDNAME'),
                type=kind,
                baseStats=stats,
                collectible=bool(number('COLLECTIBLE')),
                rarity={1: 'COMMON', 2: 'FREE', 3: 'RARE', 4: 'EPIC', 5: 'LEGENDARY'}[
                    number('RARITY', 2)
                ],
                keywords=keywords,
                text=text,
                rawText=loc('CARDTEXT'),
            )
        )
    return dict(
        profile=PROFILE,
        build='11.0.0.24118',
        revision=REVISION,
        url=URL,
        sha256=hashlib.sha256(raw).hexdigest(),
        cards=facts,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xml')
    parser.add_argument('--output', default='docs/sources/card-profile.json')
    args = parser.parse_args()
    catalog = json.loads((ROOT / 'cards/foundation.json').read_text())
    facts = extract(args.xml, [c['cardId'] for c in catalog['cards']])
    expected = json.loads((ROOT / 'cards/manifest.json').read_text())['cardDataSource']
    if (
        facts['sha256'] != expected['sha256']
        or facts['revision'] != expected['revision']
    ):
        raise SystemExit('source does not match the pinned manifest revision/hash')
    (ROOT / args.output).write_text(json.dumps(facts, indent=2) + '\n')
    print(f"Extracted {len(facts['cards'])} definitions from build 24118")
