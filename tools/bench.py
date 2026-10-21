"""Seeded legal-action games: python3 tools/bench.py --games 10 --seed 0.

Includes enumeration and execution; excludes engine/schema setup and deck setup.
Uses a separate driver RNG so action selection never consumes the game RNG.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hearthstone.match import MatchEngine


def check_invariants(engine, state):
    ids = [e['id'] for e in state['entities']]
    assert len(ids) == len(set(ids)), 'duplicate entity ID'
    for player in (0, 1):
        assert len(engine.board(state, player)) <= 7, 'board overflow'
        assert (
            sum(
                e['zone'] == 'HAND' and e['controller'] == player
                for e in state['entities']
            )
            <= 10
        ), 'hand overflow'
        assert state['mana'][player] >= 0, 'negative mana'
        assert state['resources'][player]['filled'] >= 0, 'negative filled mana'
    assert all(
        engine.current_health(state, e) > 0
        for e in state['entities']
        if e['zone'] == 'PLAY' and e['kind'] == 'MINION'
    ), 'unsettled death'
    deck_ids = [eid for deck in state['decks'] for eid in deck]
    assert len(deck_ids) == len(set(deck_ids)), 'duplicate deck entry'
    assert set(deck_ids) == {
        e['id'] for e in state['entities'] if e['zone'] == 'DECK'
    }, 'deck mismatch'
    assert not any(k.startswith('_reaction') for k in state), 'unfinished reaction work'


def random_game(engine, seed, inspect=None):
    driver = random.Random(seed)
    pool = sorted(c['cardId'] for c in engine.cards.values() if c['collectible'])
    decks = [[driver.choice(pool) for _ in range(16)] for _ in (0, 1)]
    state = engine.new_game(
        decks, seed, deck_size=16, turn_limit=50, hero_powers=['CS2_034', 'CS1h_001']
    )
    start = perf_counter()
    trace = []
    while state['result'] is None:
        player = (
            next(p for p in (0, 1) if state['mulligan']['choices'][p] is None)
            if state['phase'] == 'MULLIGAN'
            else state['activePlayer']
        )
        actions = engine.legal_actions(state, player)
        choices = [a for a in actions if a['type'] != 'concede']
        assert choices, 'no non-concede action'
        if inspect:
            inspect(state, player, actions)
        action = driver.choice(choices)
        state = engine.apply(state, player, action)
        trace.append(dict(player=player, action=action))
        if inspect and len(trace) % 11 == 0:
            state = json.loads(json.dumps(state))
        if inspect:
            check_invariants(engine, state)
        assert len(trace) < 2000, 'game exceeded action budget'
    elapsed = perf_counter() - start
    if inspect:
        check_invariants(engine, state)
        for player in (0, 1):
            assert engine.legal_actions(state, player) == []
            try:
                engine.apply(state, player, {'type': 'concede'})
            except ValueError:
                pass
            else:
                raise AssertionError('terminal result can be changed')
    return state, trace, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=10)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument(
        '--event-copy',
        choices=('shared', 'deep'),
        default='shared',
        help='deep reproduces pre-optimization copying for comparison',
    )
    args = parser.parse_args()
    if args.games < 1:
        parser.error('--games must be positive')
    if args.event_copy == 'deep':
        # Benchmark-only control: reproduce the former plain-list event log
        # and full-state deepcopy. No alternate production rules are enabled.
        from hearthstone import prototype, match, reactions

        original_state = prototype.Prototype.state

        def plain_log_state():
            state = original_state()
            state['events'] = []
            return state

        prototype.Prototype.state = staticmethod(plain_log_state)
        for module in (prototype, match, reactions):
            module.copy_state = deepcopy
    engine = MatchEngine()
    actions = 0
    elapsed = 0
    results = []
    digest = hashlib.sha256()
    for seed in range(args.seed, args.seed + args.games):
        state, trace, seconds = random_game(engine, seed)
        actions += len(trace)
        elapsed += seconds
        results.append(state['result'])
        digest.update(json.dumps([state, trace], sort_keys=True).encode())
    print(
        json.dumps(
            dict(
                eventCopy=args.event_copy,
                games=args.games,
                seed=args.seed,
                actions=actions,
                seconds=round(elapsed, 4),
                actionsPerSecond=round(actions / elapsed, 2),
                results=results,
                replayHash=digest.hexdigest(),
            ),
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
