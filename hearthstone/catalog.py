"""Strict structural and cross-reference validation; no network access."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {'1.9': 'catalog.schema.json'}


def validate(catalog):
    if (not isinstance(catalog, dict) or not isinstance(catalog.get('schemaVersion'), str)
            or catalog['schemaVersion'] not in SCHEMAS):
        return ['unsupported catalog schemaVersion']
    schema = json.loads((ROOT / 'schemas' / SCHEMAS[catalog['schemaVersion']]).read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(catalog)]
    if errors:
        return errors
    cards = catalog['cards']
    definitions = {}
    for card in cards:
        key = (card['cardId'], card['revision'])
        if key in definitions:
            errors.append(f'duplicate definition {key}')
        definitions[key] = card
    for card in cards:
        label = card['cardId']
        if 'overload' in card and card['type'] == 'WEAPON':
            errors.append(f'{label}: weapon Overload is not supported')
        if 'overload' in card and card['type'] == 'HERO_POWER':
            errors.append(f'{label}: hero power Overload is not supported')
        if 'NEUTRAL' in card['classes'] and len(card['classes']) != 1:
            errors.append(f'{label}: NEUTRAL cannot be combined with a class')
        kinds = [a['kind'] for a in card['abilities']]
        if card['type'] == 'HERO_POWER' and kinds != ['HERO_POWER_EFFECT']:
            errors.append(f'{label}: hero power requires one hero power ability')
        if card['type'] == 'SPELL' and card['keywords']:
            errors.append(f'{label}: spells cannot have combat keywords')
        for kind in ('BATTLECRY', 'DEATHRATTLE', 'AURA', 'SECRET'):
            if (kind in kinds) != (kind in card['mechanics']):
                errors.append(f'{label}: {kind} label and ability disagree')
        if len([k for k in kinds if k != 'TRIGGER']) != len(set(k for k in kinds if k != 'TRIGGER')):
            errors.append(f'{label}: duplicate ability kind')
        if 'SECRET' in kinds and (card['type'] != 'SPELL' or kinds != ['SECRET']):
            errors.append(f'{label}: Secret requires a standalone spell Secret ability')
        transforms = False
        for ability in card['abilities']:
            expected = ability['kind']
            allowed = {'BATTLECRY', 'DEATHRATTLE', 'AURA', 'START_OF_TURN', 'END_OF_TURN'} if card['type'] == 'MINION' else {'SPELL_EFFECT'}
            if card['type'] == 'MINION': allowed.add('TRIGGER')
            if card['type'] == 'WEAPON': allowed = {'TRIGGER', 'DEATHRATTLE'}
            if card['type'] == 'SPELL' and 'SECRET' in card['mechanics']: allowed = {'SECRET'}
            if card['type'] == 'HERO_POWER':
                allowed = {'HERO_POWER_EFFECT'}
            if expected not in allowed:
                errors.append(f'{label}: incompatible ability kind')
            if expected == 'AURA':
                selector = ability['selector']
                if selector['entityKind'] != 'MINION' or selector['controller'] != 'FRIENDLY':
                    errors.append(f'{label}: auras require friendly minion selectors')
                if not any(ability['modifiers'].values()):
                    errors.append(f'{label}: aura must modify a stat')
                continue
            targeting = ability.get('targeting')
            if expected in ('DEATHRATTLE', 'START_OF_TURN', 'END_OF_TURN') and targeting:
                errors.append(f'{label}: triggered abilities cannot request a selected target')
            if targeting:
                policy = 'BATTLECRY_SELECTED_TARGET' if expected == 'BATTLECRY' else 'SPELL_SELECTED_TARGET'
                if expected == 'HERO_POWER_EFFECT':
                    policy = 'HERO_POWER_SELECTED_TARGET'
                if targeting['legalityPolicy'] != policy:
                    errors.append(f'{label}: incompatible targeting policy')
            for effect in ability['effects']:
                trigger = ability.get('trigger', {})
                if effect.get('amount', {}).get('kind') == 'EVENT_AMOUNT' and trigger.get('event') not in ('DAMAGE', 'HEAL'):
                    errors.append(f'{label}: event amount requires a damage/heal listener')
                if effect['op'] == 'COUNTER_SPELL':
                    if expected != 'SECRET' or trigger.get('event') != 'BEFORE_SPELL' or trigger.get('relation') != 'ENEMY':
                        errors.append(f'{label}: counter requires a before-spell Secret')
                    continue
                if effect['op'] == 'REDIRECT_ATTACK':
                    destination = definitions.get(tuple(effect['definition'][k] for k in ('cardId','revision')))
                    if not destination or destination['type'] != 'MINION':
                        errors.append(f'{label}: redirect requires a resolved minion definition')
                    if (expected != 'SECRET' or trigger.get('event') != 'BEFORE_ATTACK'
                            or trigger.get('relation') != 'FRIENDLY'):
                        errors.append(f'{label}: redirect requires a before-attack Secret')
                    continue
                if effect['op'] in ('SUMMON', 'ADD_CARD'):
                    key = tuple(effect['definition'][k] for k in ('cardId', 'revision'))
                    destination = definitions.get(key)
                    if destination is None:
                        errors.append(f'{label}: unresolved definition {key}')
                    elif (effect['op'] == 'SUMMON' and destination['type'] != 'MINION'
                          or effect['op'] == 'ADD_CARD' and destination['type'] == 'HERO_POWER'):
                        errors.append(f'{label}: incompatible generated definition type')
                    if effect['targetPlayer'] == 'CONTROLLER_AT_DEATH' and expected != 'DEATHRATTLE':
                        errors.append(f'{label}: controller-at-death requires a Deathrattle')
                    placement = effect.get('placement')
                    if placement == 'DEATH_POSITION' and (expected != 'DEATHRATTLE'
                            or effect['targetPlayer'] != 'CONTROLLER_AT_DEATH' or card['type'] != 'MINION'):
                        errors.append(f'{label}: death placement requires controller-at-death Deathrattle')
                    if placement == 'RIGHT_OF_SOURCE' and (card['type'] != 'MINION'
                            or expected == 'DEATHRATTLE' or effect['targetPlayer'] != 'EFFECT_CONTROLLER'):
                        errors.append(f'{label}: source placement requires a living friendly minion source')
                    continue
                if effect['op'] in ('GAIN_MANA', 'DESTROY_MANA', 'UNLOCK_MANA'):
                    continue
                if effect['op'] == 'DRAW_CARD':
                    if effect['targetPlayer'] == 'CONTROLLER_AT_DEATH' and expected != 'DEATHRATTLE':
                        errors.append(f'{label}: controller-at-death requires a Deathrattle')
                    continue
                recipient = effect['recipient']
                if recipient['kind'] == 'SELF' and card['type'] != 'MINION':
                    errors.append(f'{label}: character self recipient requires a minion')
                if recipient['kind'] in ('EVENT_TARGET', 'ATTACKER', 'DEFENDER') and not trigger:
                    errors.append(f'{label}: event recipient requires a listener')
                if recipient['kind'] in ('ATTACKER','DEFENDER') and trigger.get('event') not in ('BEFORE_ATTACK','AFTER_ATTACK'):
                    errors.append(f'{label}: combat recipient requires an attack listener')
                if recipient['kind'] == 'BOUND_TARGET':
                    if not targeting or recipient['name'] != targeting['bindAs']:
                        errors.append(f'{label}: unbound target {recipient["name"]}')
                if effect['op'] == 'DEAL_DAMAGE':
                    cls = 'SPELL' if expected in ('SPELL_EFFECT','SECRET') else 'ABILITY'
                    if expected == 'HERO_POWER_EFFECT':
                        cls = 'HERO_POWER'
                    if effect['damageClass'] != cls:
                        errors.append(f'{label}: incompatible damage class')
                    batch = recipient['kind'] == 'QUERY'
                    if batch != (effect['application'] == 'SINGLE_DAMAGE_BATCH'):
                        errors.append(f'{label}: recipient and damage application disagree')
                elif effect['op'] in ('DESTROY', 'BUFF', 'SILENCE', 'RETURN_TO_HAND',
                                       'SHUFFLE_INTO_DECK', 'SHUFFLE_COPIES'):
                    selector = recipient.get('selector') if recipient['kind'] == 'QUERY' else (targeting or {}).get('selector')
                    if (recipient['kind'] == 'SELF' and card['type'] == 'MINION'
                            or recipient['kind'] == 'ATTACKER' and trigger.get('actorKind') == 'MINION'
                            or recipient['kind'] in ('EVENT_TARGET','DEFENDER') and trigger.get('subjectKind') == 'MINION'):
                        selector = {'entityKind':'MINION'}
                    if not selector or selector['entityKind'] != 'MINION':
                        errors.append(f'{label}: {effect["op"].lower()} requires minion recipients')
                    if effect['op'] == 'BUFF' and not any(effect['modifiers'].values()):
                        errors.append(f'{label}: buff must modify a stat')
                elif effect['op'] == 'TRANSFORM':
                    transforms = True
                    key = tuple(effect['targetDefinition'][k] for k in ('cardId', 'revision'))
                    target = definitions.get(key)
                    if target is None:
                        errors.append(f'{label}: unresolved definition {key}')
                    elif target['type'] != 'MINION':
                        errors.append(f'{label}: transform result must be a minion')
                    if not targeting or targeting['selector']['entityKind'] != 'MINION':
                        errors.append(f'{label}: transform requires minion targeting')
        if transforms != ('TRANSFORM' in card['mechanics']):
            errors.append(f'{label}: TRANSFORM label and effect disagree')
    return errors


def load(path=None):
    catalog = json.loads(Path(path or ROOT / 'cards/foundation.json').read_text())
    errors = validate(catalog)
    if errors:
        raise ValueError('\n'.join(errors))
    return catalog


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Validate a foundation catalog')
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    try:
        data = load(args.path)
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')
    print(f"Validated {len(data['cards'])} card definitions in {data['catalogId']}")
