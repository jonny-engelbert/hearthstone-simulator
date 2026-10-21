"""Explicit chronology for entities arranged directly by tests."""
def enter(engine, state, entity):
    if (entity['zone'] == 'PLAY' and entity['kind'] in ('MINION', 'WEAPON')
            or entity['zone'] == 'SECRET'):
        stamps = [e['playOrder'] for e in state['entities'] if 'playOrder' in e]
        state['nextPlayOrder'] = max(state['nextPlayOrder'], max(stamps, default=0) + 1)
        if 'playOrder' not in entity:
            engine._stamp_enter(state, entity)
    return entity
