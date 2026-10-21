"""Versioned transport and private persistence boundaries for the managed API."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, validators

from .events import copy_state
from . import resources

API_VERSION = '1.0'
CHECKPOINT_VERSION = '1.0'
RULES_VERSION = 'foundation-rules-11'
SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schemas/integration.schema.json'
LIMITS = ('max_choices', 'max_deathrattles', 'max_reactions', 'max_random_steps')


def plain(value):
    """Detach JSON data, including immutable engine event payloads."""
    return json.loads(json.dumps(value, allow_nan=False))


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(',', ':'), allow_nan=False
        ).encode()
    ).hexdigest()


@lru_cache(maxsize=None)
def validator(kind):
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    if kind not in schema['$defs']:
        raise ValueError('unknown integration contract')
    # Python floats and bools are never accepted as API integer values.
    strict = validators.extend(
        Draft202012Validator,
        type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
            'integer', lambda checker, value: type(value) is int
        ),
    )
    return strict(
        {
            '$schema': schema['$schema'],
            '$defs': schema['$defs'],
            '$ref': f'#/$defs/{kind}',
        }
    )


def validate(kind, value):
    error = next(validator(kind).iter_errors(value), None)
    if error is not None:
        path = '.'.join(str(item) for item in error.absolute_path) or '$'
        raise ValueError(f'{kind} contract at {path}: {error.message}')


def validate_action_values(action):
    """Cheap hot-path check after MatchEngine's exact action-field validation.

    JSON Schema is also published for independent consumers. Tests compare this
    execution check with the schema, including non-JSON Python inputs.
    """
    for key, value in action.items():
        if key == 'replace':
            if (
                not isinstance(value, list)
                or any(type(item) is not str or not item for item in value)
                or len(value) != len(set(value))
            ):
                raise ValueError('invalid action replace list')
        elif key == 'position':
            if value is not None and (type(value) is not int or not 0 <= value <= 7):
                raise ValueError('invalid action position')
        elif key == 'target' and value is None:
            continue
        elif type(value) is not str or not value:
            raise ValueError(f'invalid action {key}')


def description(engine):
    from .decks import format_description

    return dict(
        apiVersion=API_VERSION,
        checkpointVersion=CHECKPOINT_VERSION,
        rulesVersion=RULES_VERSION,
        catalogId=engine.catalog_id,
        catalogHash=engine.catalog_hash,
        schemaId='urn:hearthstone-foundation:integration:1.0',
        limits={key: getattr(engine, key) for key in LIMITS},
        formats=[format_description(engine)],
    )


def _state_boundary(engine, state, nested=False):
    """Check decision-boundary invariants; private state is not a client input."""
    validate('privateState', state)
    engine._managed(state)
    if any(key.startswith('_') for key in state):
        raise ValueError('checkpoint contains unfinished runtime work')
    phase = state['phase']
    if (phase == 'FINISHED') != (state['result'] is not None):
        raise ValueError('checkpoint phase/result mismatch')
    if state['mana'] != [resources.available(r) for r in state['resources']]:
        raise ValueError('checkpoint mana disagrees with resources')
    for resource in state['resources']:
        if (
            not 1 <= resource['cap'] <= 99
            or not (resource['filled'] <= resource['permanent'] <= resource['cap'])
            or resource['temporary'] + resource['filled'] > resource['cap']
        ):
            raise ValueError('checkpoint resource bounds')
    entities = state['entities']
    ids = [entity['id'] for entity in entities]
    if any(type(item) is not str or not item for item in ids) or len(ids) != len(
        set(ids)
    ):
        raise ValueError('checkpoint entity IDs must be unique')
    by_id = dict(zip(ids, entities))
    stamps = []
    for entity in entities:
        engine._player(entity['controller'])
        engine._player(entity['owner'])
        if entity['zone'] not in ('PLAY', 'HAND', 'DECK', 'SECRET', 'GRAVEYARD'):
            raise ValueError('checkpoint entity zone')
        for key in ('damage', 'armor', 'attacksThisTurn'):
            if type(entity[key]) is not int or entity[key] < 0:
                raise ValueError(f'checkpoint entity {key}')
        if type(entity['ready']) is not bool or not isinstance(
            entity['enchantments'], list
        ):
            raise ValueError('checkpoint entity runtime fields')
        if entity['kind'] == 'HERO':
            if (
                entity['id'] != f"hero-{entity['controller']}"
                or entity['zone'] != 'PLAY'
            ):
                raise ValueError('checkpoint hero identity')
        elif entity['kind'] != engine.definition(entity)['type']:
            raise ValueError('checkpoint entity definition kind')
        requires_stamp = (
            entity['zone'] == 'PLAY'
            and entity['kind'] in ('MINION', 'WEAPON')
            or entity['zone'] == 'SECRET'
        )
        if requires_stamp or 'playOrder' in entity:
            stamp = entity['playOrder']
            if type(stamp) is not int or stamp < 1:
                raise ValueError('checkpoint entry stamp')
            stamps.append(stamp)
        if entity.get('pendingDestroy', False):
            raise ValueError('checkpoint contains pending destruction')
        if (
            entity['zone'] == 'PLAY'
            and entity['kind'] == 'MINION'
            and engine.current_health(state, entity) <= 0
        ):
            raise ValueError('checkpoint contains unsettled minion death')
    if len(stamps) != len(set(stamps)) or state['nextPlayOrder'] <= max(
        stamps, default=0
    ):
        raise ValueError('checkpoint entry chronology')
    if {e['id'] for e in entities if e['kind'] == 'HERO'} != {'hero-0', 'hero-1'}:
        raise ValueError('checkpoint must contain two heroes')
    for player in (0, 1):
        deck = state['decks'][player]
        expected = {
            e['id']
            for e in entities
            if e['zone'] == 'DECK' and e['controller'] == player
        }
        if len(deck) != len(set(deck)) or set(deck) != expected or len(deck) > 99:
            raise ValueError('checkpoint deck membership')
        if (
            len(engine.board(state, player)) > 7
            or sum(e['zone'] == 'HAND' and e['controller'] == player for e in entities)
            > 10
        ):
            raise ValueError('checkpoint board/hand capacity')
        power = state['heroPowers'][player]
        if power is not None and not (
            by_id[power]['kind'] == 'HERO_POWER'
            and by_id[power]['controller'] == player
            and by_id[power]['zone'] == 'PLAY'
        ):
            raise ValueError('checkpoint hero power')
    from .decks import FORMAT, HERO_POWERS

    if state['match']['profile'] == FORMAT:
        classes = state['match']['classes']
        if (
            len(classes) != 2
            or any(cls not in HERO_POWERS for cls in classes)
            or state['match']['catalogHash'] != engine.catalog_hash
        ):
            raise ValueError('checkpoint constructed profile')
        for player, cls in enumerate(classes):
            if by_id[state['heroPowers'][player]]['cardId'] != HERO_POWERS[cls]:
                raise ValueError('checkpoint class/power mismatch')
    elif state['match']['profile'] != 'FOUNDATION_SANDBOX':
        raise ValueError('unsupported checkpoint match profile')
    if phase == 'CHOICE':
        if nested:
            raise ValueError('checkpoint continuation cannot itself be pending')
        continuation = state['continuation']
        if set(continuation) != {'start', 'player', 'action', 'answers'}:
            raise ValueError('checkpoint continuation fields')
        _state_boundary(engine, continuation['start'], nested=True)
        engine._player(continuation['player'])
        validate('action', continuation['action'])
        if len(continuation['answers']) >= engine.max_choices:
            raise ValueError('checkpoint choice budget')
        replay = engine._run_decision(
            continuation['start'],
            continuation['player'],
            continuation['action'],
            continuation['answers'],
        )
        if replay != state:
            raise ValueError('checkpoint pending transaction does not replay')
    elif 'pendingChoice' in state or 'continuation' in state:
        raise ValueError('checkpoint has an unexpected continuation')
    if phase == 'MULLIGAN':
        mulligan = state['mulligan']
        if len(mulligan['initialHands']) != 2 or len(mulligan['choices']) != 2:
            raise ValueError('checkpoint mulligan shape')
        if all(choice is not None for choice in mulligan['choices']):
            raise ValueError('checkpoint contains an unsettled mulligan')
        for player in (0, 1):
            actual = [
                e['id']
                for e in entities
                if e['zone'] == 'HAND' and e['controller'] == player
            ]
            if actual != mulligan['initialHands'][player]:
                raise ValueError('checkpoint mulligan hand')
            selected = mulligan['choices'][player]
            if selected is not None and (
                not isinstance(selected, list)
                or len(selected) != len(set(selected))
                or not set(selected) <= set(actual)
                or len(selected) > len(state['decks'][player])
            ):
                raise ValueError('checkpoint mulligan selections')


def _checked_state(engine, state):
    try:
        _state_boundary(engine, state)
    except (KeyError, TypeError, IndexError, AttributeError, RecursionError) as error:
        raise ValueError('invalid private checkpoint state') from error


def checkpoint(engine, state, sequence=0):
    detached = plain(state)
    _checked_state(engine, detached)
    result = dict(
        checkpointVersion=CHECKPOINT_VERSION,
        rulesVersion=RULES_VERSION,
        catalogHash=engine.catalog_hash,
        limits={key: getattr(engine, key) for key in LIMITS},
        sequence=sequence,
        stateHash=digest(detached),
        state=detached,
    )
    validate('checkpoint', result)
    return result


def restore(engine, value):
    validate('checkpoint', value)
    if value['catalogHash'] != engine.catalog_hash:
        raise ValueError('checkpoint catalog fingerprint mismatch')
    if value['limits'] != {key: getattr(engine, key) for key in LIMITS}:
        raise ValueError('checkpoint resolution limits mismatch')
    if value['stateHash'] != digest(value['state']):
        raise ValueError('checkpoint state checksum mismatch')
    detached = plain(value['state'])
    _checked_state(engine, detached)
    return copy_state(detached)


class Session:
    """Server-owned state, detached player observations, stale-command guard.

    Player identity is supplied by the host's authenticated connection, never
    taken from a client command. Checkpoints belong only in private storage.
    This synchronous adapter deliberately has no network/authentication layer.
    """

    def __init__(self, engine, state):
        self.engine = engine
        self._state = engine.restore(engine.checkpoint(state))
        self.sequence = 0

    @classmethod
    def resume(cls, engine, checkpoint):
        result = cls.__new__(cls)
        result.engine = engine
        result._state = engine.restore(checkpoint)
        result.sequence = checkpoint['sequence']
        return result

    def observe(self, player):
        return dict(
            apiVersion=API_VERSION,
            sequence=self.sequence,
            view=self.engine.view(self._state, player),
            legalActions=self.engine.legal_actions(self._state, player),
        )

    def submit(self, player, command):
        validate('command', command)
        if command['sequence'] != self.sequence:
            raise ValueError('stale command sequence; observe again')
        next_state = self.engine.apply(self._state, player, command['action'])
        self._state = next_state
        self.sequence += 1
        return self.observe(player)

    def checkpoint(self):
        return self.engine.checkpoint(self._state, self.sequence)
