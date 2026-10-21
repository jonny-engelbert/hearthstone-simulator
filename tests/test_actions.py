"""Shared legality, complete seeded games, and public action dictionaries."""

from copy import deepcopy
import itertools
import json
import os
import unittest

from hearthstone.match import MatchEngine
from test_zones import ZoneFixture
from tools.bench import random_game, check_invariants


class LegalActionTests(ZoneFixture):
    def test_targets_positions_powers_and_attack_pairs(self):
        self.add('CS2_042', 'elemental', zone='HAND')
        self.add('CS2_022', 'polymorph', zone='HAND')
        self.add('CS2_182', 'yeti', ready=True)
        self.add('CS2_179', 'taunt', 1)
        self.add('CS2_182', 'stealth', 1, keywords=['STEALTH'])
        actions = self.engine.legal_actions(self.state, 0)
        for target, position in itertools.product(
            ['hero-0', 'hero-1', 'yeti', 'taunt'], range(2)
        ):
            self.assertIn(
                dict(type='play', source='elemental', target=target, position=position),
                actions,
            )
        self.assertNotIn(dict(type='play', source='elemental', position=0), actions)
        self.assertIn(dict(type='play', source='polymorph', target='taunt'), actions)
        self.assertFalse(any(a.get('target') == 'stealth' for a in actions))
        self.assertEqual(
            [a for a in actions if a['type'] == 'attack'],
            [dict(type='attack', attacker='yeti', defender='taunt')],
        )
        self.assertIn(dict(type='hero_power', target='hero-1'), actions)
        before = deepcopy(self.state)
        for action in actions:
            self.engine.apply(self.state, 0, action)
        self.assertEqual(before, self.state)

    def test_every_mulligan_subset_and_waiting_player(self):
        engine = self.engine
        state = engine.new_game([['CS2_182'] * 16] * 2, 12, deck_size=16)
        for player in (0, 1):
            actions = engine.legal_actions(state, player)
            hand = state['mulligan']['initialHands'][player]
            self.assertEqual(len(actions), 2 ** len(hand) + 1)
            for action in actions:
                engine.apply(state, player, action)
        state = engine.mulligan(state, 0, [])
        self.assertEqual(engine.legal_actions(state, 0), [{'type': 'concede'}])
        state = engine.mulligan(state, 1, [])
        self.assertEqual(
            engine.legal_actions(state, 1 - state['activePlayer']),
            [{'type': 'concede'}],
        )

    def test_small_deck_mulligan_subsets_respect_replacement_capacity(self):
        state = self.engine.new_game(
            [['CS2_182'] * 4] * 2, 0, deck_size=4, first_player=0
        )
        for player, expected in [(0, 5), (1, 2)]:
            actions = self.engine.legal_actions(state, player)
            self.assertEqual(len(actions), expected)
            for action in actions:
                self.engine.apply(state, player, action)

    def test_illegal_unlisted_actions_fail_atomically(self):
        self.add('CS2_182', 'yeti', zone='HAND')
        self.add('CS2_022', 'poly', zone='HAND')
        self.add(eid='enemy', player=1)
        invalid = [
            dict(type='play', source='yeti', target='hero-1'),
            dict(type='play', source='yeti', position=-1),
            dict(type='play', source='yeti', position=8),
            dict(type='play', source='unknown'),
            dict(type='play', source='enemy'),
            dict(type='play', source='poly', target='hero-1'),
            dict(type='hero_power', target='unknown'),
            dict(type='attack', attacker='enemy', defender='hero-0'),
        ]
        actions = self.engine.legal_actions(self.state, 0)
        before = deepcopy(self.state)
        for action in invalid:
            self.assertNotIn(action, actions)
            with self.assertRaises(ValueError):
                self.engine.apply(self.state, 0, action)
            self.assertEqual(before, self.state)

    def test_board_capacity_secret_duplicates_and_power_usage(self):
        self.add('CS2_182', 'hand-yeti', zone='HAND')
        self.add('EX1_287', 'counter', zone='SECRET')
        self.add('EX1_287', 'hand-counter', zone='HAND')
        for i in range(7):
            self.add(eid=f'm{i}')
        self.state['heroPowerUsesThisTurn'][0] = 1
        actions = self.engine.legal_actions(self.state, 0)
        self.assertFalse(
            any(
                a['type'] == 'hero_power'
                or a.get('source') in ('hand-yeti', 'hand-counter')
                for a in actions
            )
        )

    def test_enumeration_does_not_consume_rng_or_reveal_secrets(self):
        self.add('CS2_029', 'fireball', zone='HAND')
        self.add('EX1_287', 'counter', 1, 'SECRET')
        before = deepcopy(self.state)
        a = self.engine.legal_actions(self.state, 0)
        self.get('counter').update(cardId='EX1_594', revision='foundation-v9')
        b = self.engine.legal_actions(self.state, 0)
        self.assertEqual(a, b)
        self.get('counter').update(cardId='EX1_287', revision='foundation-v9')
        self.assertEqual(before, self.state)


class SeededLegalGameTests(unittest.TestCase):
    def test_random_games_and_every_listed_action(self):
        engine = MatchEngine()
        games = int(os.environ.get('HS_RANDOM_GAMES', '6'))
        self.assertGreater(games, 0)
        for seed in range(games):

            def inspect(state, player, actions):
                before = deepcopy(state)
                for action in actions:
                    result = engine.apply(state, player, action)
                    check_invariants(engine, result)
                self.assertEqual(before, state)
                for action in [
                    dict(type='play', source='does-not-exist'),
                    dict(type='hero_power', target='does-not-exist'),
                    dict(type='play', source='hero-0', position=999),
                ]:
                    self.assertNotIn(action, actions)
                    with self.assertRaises(ValueError):
                        engine.apply(state, player, action)

            with self.subTest(seed=seed):
                state, trace, _ = random_game(engine, seed, inspect)
                self.assertIsNotNone(state['result'])
                second, replay, _ = random_game(engine, seed)
                self.assertEqual(trace, replay)
                self.assertEqual(json.loads(json.dumps(state)), second)
