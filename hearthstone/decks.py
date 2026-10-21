"""Explicit foundation constructed rules, separate from arranged sandbox games."""

from collections import Counter
from copy import deepcopy

FORMAT = 'FOUNDATION_CONSTRUCTED_V1'
HERO_POWERS = {'MAGE': 'CS2_034', 'PRIEST': 'CS1h_001', 'PALADIN': 'CS2_101'}


def reference(engine, value):
    if isinstance(value, str):
        card_id, revision = value, None
    elif isinstance(value, dict) and set(value) == {'cardId', 'revision'}:
        card_id, revision = value['cardId'], value['revision']
        if not isinstance(card_id, str) or not isinstance(revision, str):
            raise ValueError('invalid definition reference')
    else:
        raise ValueError('invalid definition reference')
    entity = engine.entity('reference', card_id, 0, revision=revision)
    return dict(cardId=entity['cardId'], revision=entity['revision'])


def validate_deck(engine, deck, hero_class, format_id=FORMAT):
    """Return detached exact references, or reject before any match is created.

    Copy identity is cardId across revisions. If any revision is Legendary,
    the identity has a one-copy limit. Alternate-print identity aliases are not
    present in this catalog and require an explicit future format revision.
    """
    if format_id != FORMAT:
        raise ValueError('unsupported constructed format')
    if not isinstance(hero_class, str) or hero_class not in HERO_POWERS:
        raise ValueError('unsupported constructed hero class')
    if not isinstance(deck, list) or len(deck) != 30:
        raise ValueError('constructed deck must contain exactly 30 cards')
    resolved = [reference(engine, item) for item in deck]
    counts = Counter(item['cardId'] for item in resolved)
    legendary = {
        card_id
        for (card_id, _), card in engine.cards.items()
        if card['rarity'] == 'LEGENDARY'
    }
    for item in resolved:
        card = engine.cards[(item['cardId'], item['revision'])]
        if not card['collectible'] or card['type'] not in ('MINION', 'SPELL', 'WEAPON'):
            raise ValueError('constructed decks require collectible playable cards')
        if hero_class not in card['classes'] and 'NEUTRAL' not in card['classes']:
            raise ValueError(f"wrong class for {item['cardId']}: {hero_class}")
        if counts[item['cardId']] > (1 if item['cardId'] in legendary else 2):
            raise ValueError(f"copy limit exceeded for {item['cardId']}")
    return deepcopy(resolved)


def format_description(engine):
    """The catalog fingerprint pins the pool, including definition revisions."""
    return dict(
        id=FORMAT,
        catalogHash=engine.catalog_hash,
        deckSize=30,
        copies=2,
        legendaryCopies=1,
        heroPowers={
            key: reference(engine, value) for key, value in HERO_POWERS.items()
        },
        pool=[
            dict(cardId=card_id, revision=revision)
            for (card_id, revision), card in sorted(engine.cards.items())
            if card['collectible'] and card['type'] in ('MINION', 'SPELL', 'WEAPON')
        ],
    )
