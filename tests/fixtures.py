"""Explicit chronology for entities arranged directly by tests."""


def enter(engine, state, entity):
    if (
        entity['zone'] == 'PLAY'
        and entity['kind'] in ('MINION', 'WEAPON')
        or entity['zone'] == 'SECRET'
    ):
        stamps = [e['playOrder'] for e in state['entities'] if 'playOrder' in e]
        state['nextPlayOrder'] = max(state['nextPlayOrder'], max(stamps, default=0) + 1)
        if 'playOrder' not in entity:
            engine._stamp_enter(state, entity)
    return entity


def spell_bonus(engine, state, player=0, amount=1):
    for index in range(amount):
        entity = engine.entity(f'spell-bonus-{player}-{index}', 'CS2_142', player)
        state['entities'].append(entity)
        enter(engine, state, entity)


def assert_invalid(case, catalog, expected):
    """Require a specific diagnostic (all fragments on the same error line)."""
    from hearthstone.catalog import validate

    fragments = (expected,) if isinstance(expected, str) else expected
    errors = validate(catalog)
    case.assertTrue(
        any(all(part in error for part in fragments) for error in errors),
        f'Expected {fragments!r}, got {errors!r}',
    )


def invalid_field(field, value, maximum=False):
    """Expected JSON Schema diagnostic for a deliberately malformed field."""
    if field == 'extra' or field == 'recipient':
        return (field, 'Additional properties are not allowed')
    if type(value) is bool or type(value) is float:
        return (f"'{field}'", f"{value} is not of type 'integer'")
    if type(value) is int:
        limit = 'greater than the maximum' if maximum else 'less than the minimum'
        return (f"'{field}'", f'{value} is {limit}')
    return (f"'{field}'", f"'{value}' is not one of")
