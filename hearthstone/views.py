"""Allowlisted player projections; engine checkpoints remain omniscient/private."""

from copy import deepcopy


# Never copy arbitrary state/event keys into a client view. In particular, no
# RNG, deck instances, scheduler frames, play stamps, createdBy or deathHistory.
ENTITY_FIELDS = {
    'id',
    'cardId',
    'revision',
    'kind',
    'owner',
    'controller',
    'zone',
    'damage',
    'armor',
    'ready',
    'attacksThisTurn',
    'keywords',
    'silenced',
    'durability',
    'maxHealth',
    'attack',
    'effectiveStats',
}
EVENT_TYPES = {
    'MATCH_SETUP',
    'DRAW_ATTEMPT',
    'DRAW',
    'REVEAL',
    'BURN',
    'FATIGUE',
    'MULLIGAN_SUBMITTED',
    'ADD_TO_HAND',
    'PHASE',
    'TURN_LIMIT',
    'TURN_TRIGGER',
    'MANA_SPENT',
    'MANA_REFILL',
    'MANA_EXPIRE',
    'MANA_CHANGED',
    'OVERLOAD',
    'PLAY',
    'SUMMON',
    'SUMMON_FAILED',
    'GENERATED',
    'COPY',
    'COPY_FAILED',
    'DISCARD',
    'ZONE_CHANGE',
    'ZONE_MOVE_FAILED',
    'SHUFFLE',
    'HERO_POWER',
    'ATTACK',
    'ATTACK_CANCELLED',
    'ATTACK_REDIRECTED',
    'DAMAGE',
    'HEAL',
    'STATS_CHANGED',
    'BUFF',
    'BUFF_EXPIRED',
    'SILENCE',
    'TRANSFORM',
    'DESTROY',
    'FREEZE',
    'THAW',
    'EQUIP',
    'WEAPON_DESTROYED',
    'DURABILITY',
    'DEATH_BATCH',
    'DEATHRATTLE',
    'SECRET_SET',
    'SECRET_REVEALED',
    'SPELL_COUNTERED',
    'REACTION',
    'REACTION_WINDOW',
    'CONCEDE',
    'CHOICE_RESOLVED',
}
EVENT_SCALARS = {
    'type',
    'player',
    'firstPlayer',
    'turn',
    'phase',
    'amount',
    'reason',
    'remaining',
    'temporary',
    'permanent',
    'count',
    'window',
    'kind',
    'damageClass',
    'to',
    'fromZone',
    'policy',
    'controller',
    'damageBefore',
    'damageAfter',
    'position',
    'operation',
}
EVENT_REFERENCES = {
    'source',
    'target',
    'entity',
    'weapon',
    'attacker',
    'defender',
    'original',
}


def player_view(engine, state, player):
    """Return a detached projection, never a state suitable for apply/restore.

    Own hand IDs and public IDs are execution handles. Hidden hand/Secret/deck
    instances have no handles in this projection. A public bounce/reveal can
    make an opponent hand card known; drawing/shuffling clears that knowledge.
    """
    known_hand = set()
    by_id = {entity['id']: entity for entity in state['entities']}
    public_sources = {
        entity['id']
        for entity in state['entities']
        if entity['zone'] in ('PLAY', 'GRAVEYARD')
        and ('privateTo' not in entity or entity['privateTo'] == player)
    }
    for event in state['events']:
        kind = event['type']
        if kind in ('PLAY', 'HERO_POWER'):
            source = by_id.get(event['source'])
            if (
                source is not None
                and 'SECRET' not in engine.definition(source)['mechanics']
            ):
                public_sources.add(source['id'])
        elif kind == 'SECRET_REVEALED':
            public_sources.add(event['source'])
        if kind == 'ZONE_CHANGE':
            if event['to'] == 'HAND':
                known_hand.add(event['entity'])
            else:
                known_hand.discard(event['entity'])
        elif kind == 'REVEAL':
            known_hand.add(event['entity'])
        elif kind == 'DRAW':
            known_hand.discard(event['entity'])
        elif (
            kind == 'GENERATED'
            and event.get('source') in public_sources
            and event.get('visibility') != 'CONTROLLER_ONLY'
        ):
            # Current generation has an exact public definition, not a random
            # private choice. Copies put in decks remain hidden below.
            known_hand.add(event['entity'])
    visible = [
        entity
        for entity in state['entities']
        if entity['zone'] in ('PLAY', 'GRAVEYARD')
        and ('privateTo' not in entity or entity['privateTo'] == player)
        or entity['zone'] in ('HAND', 'SECRET')
        and entity['controller'] == player
        or entity['zone'] == 'HAND'
        and entity['id'] in known_hand
    ]
    visible_ids = {entity['id'] for entity in visible}
    entities = [
        {key: deepcopy(value) for key, value in entity.items() if key in ENTITY_FIELDS}
        for entity in visible
    ]
    result = {
        key: deepcopy(state[key])
        for key in (
            'activePlayer',
            'firstPlayer',
            'phase',
            'turn',
            'result',
            'mana',
            'resources',
            'fatigue',
            'heroPowerUsesThisTurn',
        )
    }
    result.update(player=player, entities=entities, players=[])
    for owner in (0, 1):
        hand = [
            entity
            for entity in entities
            if entity['zone'] == 'HAND' and entity['controller'] == owner
        ]
        hand_count = sum(
            entity['zone'] == 'HAND' and entity['controller'] == owner
            for entity in state['entities']
        )
        secrets = [
            entity
            for entity in state['entities']
            if entity['zone'] == 'SECRET' and entity['controller'] == owner
        ]
        result['players'].append(
            dict(
                player=owner,
                deckCount=len(state['decks'][owner]),
                hand=dict(count=hand_count, cards=hand),
                secrets=(
                    [
                        entity
                        for entity in entities
                        if entity['zone'] == 'SECRET' and entity['controller'] == owner
                    ]
                    if owner == player
                    else [dict(name='a Secret') for _ in secrets]
                ),
            )
        )
    events = []
    for event in state['events']:
        kind = event['type']
        if kind not in EVENT_TYPES:
            continue
        if event.get('visibility') == 'CONTROLLER_ONLY' and event['player'] != player:
            events.append(dict(type=kind, player=event['player']))
            continue
        # Private draw handles must never correlate with an earlier public
        # shuffle/copy or a future play, including identities embedded in IDs.
        if kind == 'DRAW' and event['player'] != player:
            events.append(dict(type='DRAW', player=event['player']))
            continue
        if kind == 'SECRET_SET':
            events.append(dict(type='SECRET_SET', player=event['player']))
            continue
        output = {
            key: deepcopy(value) for key, value in event.items() if key in EVENT_SCALARS
        }
        for key in EVENT_REFERENCES:
            if key in event and (event[key] is None or event[key] in visible_ids):
                output[key] = event[key]
        for key in ('sources', 'targets'):
            if key in event:
                output[key] = [item for item in event[key] if item in visible_ids]
        if kind == 'REACTION_WINDOW' and not output.get('sources'):
            continue
        if kind in ('REVEAL', 'SECRET_REVEALED'):
            output['cardId'] = event['cardId']
        elif kind == 'GENERATED' and event['entity'] in visible_ids:
            output['cardId'] = event['cardId']
        for key in ('before', 'after', 'modifiers'):
            if key not in event:
                continue
            value = event[key]
            if isinstance(value, dict):
                output[key] = {
                    name: value[name] for name in ('attack', 'health') if name in value
                }
            elif value in visible_ids:
                output[key] = value
        if 'resource' in event:
            output['resource'] = {
                key: event['resource'][key]
                for key in (
                    'cap',
                    'permanent',
                    'filled',
                    'temporary',
                    'locked',
                    'pendingOverload',
                )
            }
        events.append(output)
    if state.get('pendingChoice'):
        request = state['pendingChoice']
        choice = dict(player=request['player'], kind=request['kind'])
        if request['player'] == player:
            choice.update(id=request['id'], source=request['source'], options=[])
            for option in request['options']:
                item = dict(id=option['id'])
                if 'definition' in option:
                    reference = option['definition']
                    definition = engine.cards[
                        (reference['cardId'], reference['revision'])
                    ]
                    item.update(
                        definition=deepcopy(reference), label=definition['name']
                    )
                else:
                    item['label'] = option['label']
                choice['options'].append(item)
        result['choice'] = choice
    result['events'] = events
    return result
