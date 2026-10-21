"""Run a complete deterministic sandbox game using only public player actions.

The repeated-card decks intentionally use the sandbox deck profile. This is a
simple demonstration policy, not an AI or constructed-deck legality example.
"""

import json
from pathlib import Path

from hearthstone.match import MatchEngine


def run(seed=17):
    engine = MatchEngine()
    state = engine.new_game([['CS2_182'] * 30, ['CS2_182'] * 30], seed)
    actions = []

    def submit(player, action):
        nonlocal state
        state = engine.apply(state, player, action)
        actions.append(dict(player=player, action=action))

    for player in (0, 1):
        submit(player, dict(type='mulligan', replace=[]))
    while state['result'] is None:
        if len(actions) >= 2000:
            raise RuntimeError('example exceeded its action guard')
        player = state['activePlayer']
        attackers = [
            e
            for e in state['entities']
            if e['kind'] == 'MINION'
            and e['zone'] == 'PLAY'
            and e['controller'] == player
        ]
        attacked = False
        for attacker in attackers:
            targets = engine.attack_targets(state, attacker['id'])
            if targets:
                hero = f'hero-{1-player}'
                submit(
                    player,
                    dict(
                        type='attack',
                        attacker=attacker['id'],
                        defender=hero if hero in targets else targets[0],
                    ),
                )
                attacked = True
                break
        if attacked:
            continue
        board_count = len(attackers)
        playable = [
            e
            for e in state['entities']
            if e['zone'] == 'HAND'
            and e['controller'] == player
            and engine.definition(e)['baseStats']['manaCost'] <= state['mana'][player]
            and (e['kind'] != 'MINION' or board_count < 7)
        ]
        if playable:
            submit(player, dict(type='play', source=playable[0]['id']))
        else:
            submit(player, dict(type='end_turn'))
    return state, actions


if __name__ == '__main__':
    final, actions = run()
    summary = dict(
        seed=final['match']['seed'],
        catalogId=final['match']['catalogId'],
        profile=final['match']['profile'],
        firstPlayer=final['firstPlayer'],
        result=final['result'],
        turn=final['turn'],
        actions=len(actions),
        events=len(final['events']),
    )
    output = Path(__file__).resolve().parents[1] / 'outputs/stage6-demo.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(dict(summary=summary, actions=actions, finalState=final), indent=2)
        + '\n'
    )
    print(json.dumps(summary, indent=2))
    print(f'Saved {output}')
