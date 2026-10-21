"""Mana bookkeeping for managed matches; mana[] is a derived compatibility view."""


def fresh(cap=10):
    if type(cap) is not int or not 1 <= cap <= 99:
        raise ValueError('mana cap must be an integer from 1 to 99')
    return dict(
        cap=cap, permanent=0, filled=0, temporary=0, locked=0, pendingOverload=0
    )


def available(resource):
    excess_locks = max(0, resource['locked'] - resource['permanent'])
    return max(
        0,
        min(resource['cap'], resource['filled'] + resource['temporary'] - excess_locks),
    )


def sync(state):
    state['mana'] = [available(resource) for resource in state['resources']]


def spend(state, player, amount):
    resource = state['resources'][player]
    if type(amount) is not int or amount < 0 or available(resource) < amount:
        raise ValueError('insufficient mana')
    temporary = min(amount, resource['temporary'])
    resource['temporary'] -= temporary
    resource['filled'] -= amount - temporary
    sync(state)
    state['events'].append(
        dict(
            type='MANA_SPENT',
            player=player,
            amount=amount,
            temporary=temporary,
            permanent=amount - temporary,
        )
    )


def start_turn(state, player):
    resource = state['resources'][player]
    resource['permanent'] = min(resource['cap'], resource['permanent'] + 1)
    resource['locked'] = resource['pendingOverload']
    resource['pendingOverload'] = 0
    resource['temporary'] = 0
    resource['filled'] = max(0, resource['permanent'] - resource['locked'])
    sync(state)
    state['events'].append(
        dict(type='MANA_REFILL', player=player, resource=dict(resource))
    )


def end_turn(state, player):
    resource = state['resources'][player]
    resource['temporary'] = 0
    resource['filled'] = 0
    sync(state)
    state['events'].append(dict(type='MANA_EXPIRE', player=player))


def overload(state, player, count):
    state['resources'][player]['pendingOverload'] += count
    sync(state)
    state['events'].append(dict(type='OVERLOAD', player=player, amount=count))


def change(state, player, effect):
    if 'resources' not in state:
        raise ValueError('resource effects require a managed match resource state')
    resource = state['resources'][player]
    count = effect.get('count', 0)
    if effect['op'] == 'GAIN_MANA':
        if effect['kind'] == 'TEMPORARY':
            resource['temporary'] += min(
                count,
                max(0, resource['cap'] - resource['filled'] - resource['temporary']),
            )
        else:
            gain = min(count, resource['cap'] - resource['permanent'])
            resource['permanent'] += gain
            if effect['kind'] == 'FILLED':
                resource['filled'] = min(
                    resource['filled'] + gain,
                    max(0, resource['permanent'] - resource['locked']),
                    resource['cap'] - resource['temporary'],
                )
    elif effect['op'] == 'DESTROY_MANA':
        resource['permanent'] = max(0, resource['permanent'] - count)
        resource['filled'] = min(
            resource['filled'], max(0, resource['permanent'] - resource['locked'])
        )
    elif effect['op'] == 'UNLOCK_MANA':
        restored = min(resource['locked'], resource['permanent'])
        resource['filled'] = min(
            resource['permanent'],
            resource['filled'] + restored,
            resource['cap'] - resource['temporary'],
        )
        resource['locked'] = 0
        resource['pendingOverload'] = 0
    else:
        raise ValueError('unsupported resource operation')
    sync(state)
    state['events'].append(
        dict(
            type='MANA_CHANGED',
            player=player,
            operation=effect['op'],
            resource=dict(resource),
        )
    )
