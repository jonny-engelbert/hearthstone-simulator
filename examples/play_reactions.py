"""Stage-9 sandbox game: automatic reactions, Secrets and weapon scripts."""
import json
from pathlib import Path

from hearthstone.match import MatchEngine


def run(seed=1):
    engine = MatchEngine()
    pool = ['EX1_007', 'CS2_235', 'EX1_595', 'NEW1_020', 'EX1_044',
            'OG_113', 'EX1_287', 'EX1_594', 'EX1_610', 'EX1_130',
            'EX1_132', 'CS2_097', 'FP1_021', 'EX1_506', 'CS2_029'] * 2
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
                minion_ids = {e['id'] for e in state['entities'] if e['kind'] == 'MINION'}
                minion_targets = [i for i in targets if i in minion_ids]
                submit(dict(type='attack', attacker=entity['id'],
                            defender=(minion_targets or targets)[0]))
                break
        else:
            if state['mana'][player] >= 2 and state['heroPowerUsesThisTurn'][player] == 0:
                submit(dict(type='hero_power', target='hero-1'))
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
                if 'SECRET' in card['mechanics']:
                    secrets=[e for e in state['entities'] if e['zone']=='SECRET' and e['controller']==player]
                    if len(secrets)>=5 or any(e['cardId']==entity['cardId'] for e in secrets):
                        continue
                action = dict(type='play', source=entity['id'])
                if entity['kind'] == 'MINION':
                    action['position'] = board_size // 2
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
    output = Path(__file__).resolve().parents[1] / 'outputs/stage9-demo.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(dict(summary=summary, actions=actions, finalState=final), indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    print(f'Saved {output}')
