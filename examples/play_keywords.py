"""Stage-7 sandbox game: only public actions, with powers and mixed cards."""
import json
from pathlib import Path

from hearthstone.match import MatchEngine
from hearthstone.catalog import ROOT, load


def run(seed=0):
    engine = MatchEngine(load())
    pool = ['CS2_124', 'GIL_580', 'EX1_033', 'CS2_024', 'EX1_046',
            'CS2_106', 'EX1_096', 'EX1_015', 'CS2_182', 'CS2_179'] * 3
    state = engine.new_game([pool, list(reversed(pool))], seed,
                            hero_powers=['CS2_034', 'CS1h_001'])
    actions = []

    def submit(action):
        nonlocal state
        player = state['activePlayer']
        state = engine.apply(state, player, action)
        actions.append(dict(player=player, action=action))

    for player in (0, 1):
        action = dict(type='mulligan', replace=[])
        state = engine.apply(state, player, action)
        actions.append(dict(player=player, action=action))
    while state['result'] is None:
        if len(actions) >= 2000:
            raise RuntimeError('example action guard exceeded')
        player = state['activePlayer']
        for entity in state['entities']:
            if entity['controller'] != player or entity['kind'] not in ('HERO', 'MINION'):
                continue
            targets = engine.attack_targets(state, entity['id'])
            if targets:
                enemy_hero = f'hero-{1-player}'
                submit(dict(type='attack', attacker=entity['id'],
                            defender=enemy_hero if enemy_hero in targets else targets[0]))
                break
        else:
            if state['mana'][player] >= 2 and state['heroPowerUsesThisTurn'][player] == 0:
                submit(dict(type='hero_power', target=f'hero-{1-player}' if player == 0 else f'hero-{player}'))
                continue
            board_size = sum(e['zone'] == 'PLAY' and e['kind'] == 'MINION'
                             and e['controller'] == player for e in state['entities'])
            action = None
            for entity in state['entities']:
                if entity['zone'] != 'HAND' or entity['controller'] != player:
                    continue
                card = engine.definition(entity)
                if card['baseStats']['manaCost'] > state['mana'][player] or (entity['kind'] == 'MINION' and board_size >= 7):
                    continue
                action = dict(type='play', source=entity['id'])
                ability = next((a for a in card['abilities'] if a['kind'] in ('BATTLECRY', 'SPELL_EFFECT')), None)
                targeting = ability.get('targeting') if ability else None
                if targeting:
                    legal = engine.select(state, targeting['selector'], player, entity['id'], targeting['legalityPolicy'])
                    if not legal and targeting['mode'] == 'REQUIRED':
                        action = None
                        continue
                    if legal:
                        preferred = f'hero-{1-player}' if entity['kind'] == 'SPELL' else None
                        action['target'] = next((e['id'] for e in legal if e['id'] == preferred), legal[0]['id'])
                break
            if action is not None:
                submit(action)
            else:
                submit(dict(type='end_turn'))
    return state, actions


if __name__ == '__main__':
    final, actions = run()
    summary = dict(seed=final['match']['seed'], catalogId=final['match']['catalogId'],
                   profile=final['match']['profile'], result=final['result'],
                   turn=final['turn'], actions=len(actions), events=len(final['events']))
    output = Path(__file__).resolve().parents[1] / 'outputs/stage7-demo.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(dict(summary=summary, actions=actions, finalState=final), indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    print(f'Saved {output}')
