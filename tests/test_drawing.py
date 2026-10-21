from fixtures import assert_invalid, invalid_field
from fixtures import spell_bonus
from fixtures import enter

"""Stage 2: ordered draw, overdraw, and fatigue conformance scenarios."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.prototype import Prototype


class DrawCatalogTests(unittest.TestCase):

    def test_current_manifest_and_novice_definition(self):
        self.assertEqual(
            verify(json.loads((ROOT / 'cards/manifest.json').read_text())), []
        )
        novice = next(c for c in load()['cards'] if c['cardId'] == 'EX1_015')
        self.assertEqual(novice['baseStats'], {'manaCost': 2, 'attack': 1, 'health': 1})
        self.assertEqual(
            novice['abilities'],
            [
                {
                    'kind': 'BATTLECRY',
                    'effects': [
                        {
                            'op': 'DRAW_CARD',
                            'count': 1,
                            'targetPlayer': 'EFFECT_CONTROLLER',
                        }
                    ],
                }
            ],
        )

    def test_malformed_draw_effects_are_rejected(self):
        for key, value in [
            ('count', 0),
            ('count', -1),
            ('count', True),
            ('count', 1.5),
            ('targetPlayer', 'SELF'),
            ('recipient', {}),
        ]:
            with self.subTest(key=key, value=value):
                catalog = load()
                novice = next(c for c in catalog['cards'] if c['cardId'] == 'EX1_015')
                novice['abilities'][0]['effects'][0][key] = value
                assert_invalid(self, catalog, invalid_field(key, value))
        for key in ('count', 'targetPlayer'):
            catalog = load()
            novice = next(c for c in catalog['cards'] if c['cardId'] == 'EX1_015')
            del novice['abilities'][0]['effects'][0][key]
            assert_invalid(self, catalog, f"'{key}' is a required property")

    def test_unknown_or_malformed_catalog_version_fails_closed(self):
        for value in (None, [], {}, 1.2, '99'):
            assert_invalid(
                self, {'schemaVersion': value}, 'unsupported catalog schemaVersion'
            )


class DrawingTests(unittest.TestCase):
    def setUp(self):
        self.engine = Prototype(load())
        self.state = self.engine.state()

    def add(self, entity_id, card_id='CS2_182', player=0, zone='DECK'):
        entity = self.engine.entity(entity_id, card_id, player, zone)
        self.state['entities'].append(entity)
        if zone == 'DECK':
            self.state['decks'][player].append(entity_id)
        enter(self.engine, self.state, entity)
        return entity

    @staticmethod
    def get(state, entity_id):
        return next(e for e in state['entities'] if e['id'] == entity_id)

    def hand(self, count, player=0):
        for i in range(count):
            self.add(f'hand-{player}-{i}', player=player, zone='HAND')

    @staticmethod
    def events(state, event_type):
        return [e for e in state['events'] if e['type'] == event_type]

    def test_draw_uses_explicit_deck_order_without_mutating_input(self):
        self.add('bottom')
        self.add('top', 'CS2_029')
        self.state['decks'][0] = ['top', 'bottom']
        before = deepcopy(self.state)
        result = self.engine.draw(self.state, 0)
        self.assertEqual(self.get(result, 'top')['zone'], 'HAND')
        self.assertEqual(self.get(result, 'bottom')['zone'], 'DECK')
        self.assertEqual(result['decks'][0], ['bottom'])
        self.assertEqual(self.state, before)
        self.assertEqual(
            [e['type'] for e in result['events']], ['DRAW_ATTEMPT', 'DRAW']
        )
        self.assertEqual(result['fatigue'], [0, 0])

    def test_draw_preserves_instance_identity_and_enchantments(self):
        card = self.add('top')
        card['enchantments'] = ['deck-cost-reduction']
        result = self.engine.draw(self.state, 0)
        drawn = self.get(result, 'top')
        self.assertEqual(drawn['enchantments'], ['deck-cost-reduction'])
        self.assertEqual(
            (drawn['id'], drawn['revision'], drawn['owner']),
            ('top', 'foundation-v1', 0),
        )
        self.assertEqual(len(result['entities']), len(self.state['entities']))

    def test_novice_play_draws_after_entering_play(self):
        self.add('engineer', 'EX1_015', zone='HAND')
        self.add('top')
        result = self.engine.play(self.state, 0, 'engineer')
        self.assertEqual(result['mana'][0], 8)
        self.assertEqual(self.get(result, 'engineer')['zone'], 'PLAY')
        self.assertFalse(self.get(result, 'engineer')['ready'])
        self.assertEqual(self.get(result, 'top')['zone'], 'HAND')
        self.assertEqual(
            result['events'],
            [
                {'type': 'PLAY', 'source': 'engineer'},
                {
                    'type': 'SUMMON',
                    'entity': 'engineer',
                    'source': 'engineer',
                    'player': 0,
                    'position': 0,
                    'reason': 'PLAY',
                },
                {'type': 'DRAW_ATTEMPT', 'player': 0, 'source': 'engineer'},
                {'type': 'DRAW', 'player': 0, 'entity': 'top'},
            ],
        )

    def test_novice_play_from_ten_card_hand_frees_space(self):
        self.hand(9)
        self.add('engineer', 'EX1_015', zone='HAND')
        self.add('top')
        result = self.engine.play(self.state, 0, 'engineer')
        self.assertEqual(sum(e['zone'] == 'HAND' for e in result['entities']), 10)
        self.assertEqual(self.get(result, 'top')['zone'], 'HAND')
        self.assertEqual(self.events(result, 'BURN'), [])

    def test_novice_summoned_without_play_does_not_draw(self):
        self.add('engineer', 'EX1_015', zone='PLAY')
        self.add('top')
        self.assertEqual(self.state['decks'][0], ['top'])
        self.assertEqual(self.state['events'], [])
        with self.assertRaisesRegex(ValueError, 'hand'):
            self.engine.play(self.state, 0, 'engineer')

    def test_full_hand_reveals_and_burns_without_draw_or_death_event(self):
        self.hand(10)
        self.add('top', 'EX1_015')
        result = self.engine.draw(self.state, 0)
        self.assertEqual(
            result['events'],
            [
                {'type': 'DRAW_ATTEMPT', 'player': 0, 'source': None},
                {'type': 'REVEAL', 'player': 0, 'entity': 'top', 'cardId': 'EX1_015'},
                {'type': 'BURN', 'player': 0, 'entity': 'top', 'reason': 'FULL_HAND'},
            ],
        )
        self.assertEqual(self.get(result, 'top')['zone'], 'GRAVEYARD')
        self.assertEqual(result['decks'][0], [])
        self.assertEqual(result['fatigue'], [0, 0])
        self.assertEqual(sum(e['zone'] == 'HAND' for e in result['entities']), 10)

    def test_multi_draw_rechecks_capacity_for_each_card(self):
        self.hand(9)
        for entity_id in ('first', 'second', 'third'):
            self.add(entity_id)
        result = self.engine.draw(self.state, 0, 3)
        self.assertEqual(
            [self.get(result, x)['zone'] for x in ('first', 'second', 'third')],
            ['HAND', 'GRAVEYARD', 'GRAVEYARD'],
        )
        self.assertEqual([e['entity'] for e in self.events(result, 'DRAW')], ['first'])
        self.assertEqual(
            [e['entity'] for e in self.events(result, 'BURN')], ['second', 'third']
        )
        self.assertEqual(result['fatigue'][0], 0)

    def test_empty_deck_increments_fatigue_on_every_attempt(self):
        result = self.engine.draw(self.state, 0, 3)
        self.assertEqual(
            [e['amount'] for e in self.events(result, 'FATIGUE')], [1, 2, 3]
        )
        self.assertEqual(
            [e['amount'] for e in self.events(result, 'DAMAGE')], [1, 2, 3]
        )
        self.assertEqual(result['fatigue'], [3, 0])
        self.assertEqual(self.get(result, 'hero-0')['damage'], 6)
        self.assertEqual(self.events(result, 'DRAW'), [])

    def test_novice_empty_deck_causes_fatigue_not_battlecry_damage(self):
        self.add('engineer', 'EX1_015', zone='HAND')
        spell_bonus(self.engine, self.state, 0, 3)
        result = self.engine.play(self.state, 0, 'engineer')
        self.assertEqual(self.get(result, 'hero-0')['damage'], 1)
        self.assertEqual(result['mana'][0], 8)
        self.assertEqual(
            self.events(result, 'DAMAGE'),
            [
                {
                    'type': 'DAMAGE',
                    'source': None,
                    'target': 'hero-0',
                    'amount': 1,
                    'damageClass': 'FATIGUE',
                }
            ],
        )

    def test_full_hand_with_empty_deck_still_takes_fatigue(self):
        self.hand(10)
        result = self.engine.draw(self.state, 0)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 1)
        self.assertEqual(self.events(result, 'BURN'), [])

    def test_draw_and_burn_then_fatigue_when_deck_runs_out(self):
        self.hand(9)
        self.add('first')
        self.add('second')
        result = self.engine.draw(self.state, 0, 4)
        self.assertEqual(
            [e['type'] for e in result['events']],
            [
                'DRAW_ATTEMPT',
                'DRAW',
                'DRAW_ATTEMPT',
                'REVEAL',
                'BURN',
                'DRAW_ATTEMPT',
                'FATIGUE',
                'DAMAGE',
                'DRAW_ATTEMPT',
                'FATIGUE',
                'DAMAGE',
            ],
        )
        self.assertEqual(result['fatigue'][0], 2)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 3)

    def test_fatigue_persists_after_deck_is_refilled_and_drawn(self):
        self.state = self.engine.draw(self.state, 0)
        self.add('refill')
        self.state = self.engine.draw(self.state, 0)
        self.assertEqual(self.state['fatigue'][0], 1)
        result = self.engine.draw(self.state, 0)
        self.assertEqual(result['fatigue'][0], 2)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 3)

    def test_fatigue_uses_armor_and_ignores_spell_bonus(self):
        self.get(self.state, 'hero-0')['armor'] = 2
        spell_bonus(self.engine, self.state, 0, 3)
        result = self.engine.draw(self.state, 0, 2)
        self.assertEqual(self.get(result, 'hero-0')['armor'], 0)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 1)
        self.assertEqual([e['amount'] for e in self.events(result, 'DAMAGE')], [1, 2])

    def test_immunity_prevents_damage_without_preventing_fatigue_growth(self):
        self.get(self.state, 'hero-0')['keywords'] = ['IMMUNE']
        self.state = self.engine.draw(self.state, 0, 2)
        self.assertEqual(self.state['fatigue'][0], 2)
        self.assertEqual(self.get(self.state, 'hero-0')['damage'], 0)
        self.get(self.state, 'hero-0')['keywords'] = []
        result = self.engine.draw(self.state, 0)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 3)

    def test_opponent_draw_and_fatigue_are_independent(self):
        self.add('opponent-top', player=1)
        self.state['fatigue'][0] = 4
        result = self.engine.draw(self.state, 1, 2)
        self.assertEqual(self.get(result, 'opponent-top')['zone'], 'HAND')
        self.assertEqual(result['fatigue'], [4, 1])
        self.assertEqual(self.get(result, 'hero-1')['damage'], 1)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 0)

    def test_generic_draw_effect_can_address_opponent(self):
        catalog = load()
        novice = next(c for c in catalog['cards'] if c['cardId'] == 'EX1_015')
        effect = novice['abilities'][0]['effects'][0]
        effect.update(targetPlayer='OPPONENT_OF_EFFECT_CONTROLLER', count=2)
        engine = Prototype(catalog)
        self.add('engineer', 'EX1_015', zone='HAND')
        self.add('opponent-top', player=1)
        result = engine.play(self.state, 0, 'engineer')
        self.assertEqual(self.get(result, 'opponent-top')['zone'], 'HAND')
        self.assertEqual(result['fatigue'], [0, 1])

    def test_fatigue_lethal_finalizes_sequence_and_prevents_further_draws(self):
        self.get(self.state, 'hero-0')['damage'] = 29
        result = self.engine.draw(self.state, 0)
        self.assertEqual(result['result'], 'PLAYER_1_WINS')
        with self.assertRaisesRegex(ValueError, 'already over'):
            self.engine.draw(result, 0)

    def test_novice_fatigue_lethal_still_spends_mana_and_places_minion(self):
        self.add('engineer', 'EX1_015', zone='HAND')
        self.get(self.state, 'hero-0')['damage'] = 29
        result = self.engine.play(self.state, 0, 'engineer')
        self.assertEqual(result['result'], 'PLAYER_1_WINS')
        self.assertEqual(result['mana'][0], 8)
        self.assertEqual(self.get(result, 'engineer')['zone'], 'PLAY')

    def test_invalid_draw_requests_are_atomic(self):
        before = deepcopy(self.state)
        for player, count in [
            (2, 1),
            (-1, 1),
            (True, 1),
            (0, 0),
            (0, -1),
            (0, 1.5),
            (0, True),
        ]:
            with (
                self.subTest(player=player, count=count),
                self.assertRaises(ValueError),
            ):
                self.engine.draw(self.state, player, count)
            self.assertEqual(self.state, before)

    def test_malformed_deck_is_rejected_atomically(self):
        self.add('top')
        for deck in (['unknown'], ['top', 'top'], []):
            with self.subTest(deck=deck):
                self.state['decks'][0] = deck
                before = deepcopy(self.state)
                with self.assertRaises(ValueError):
                    self.engine.draw(self.state, 0)
                self.assertEqual(self.state, before)

    def test_novice_rejected_on_full_board_does_not_draw_or_pay(self):
        self.add('engineer', 'EX1_015', zone='HAND')
        self.add('top')
        for i in range(7):
            self.add(f'board-{i}', zone='PLAY')
        before = deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'board is full'):
            self.engine.play(self.state, 0, 'engineer')
        self.assertEqual(self.state, before)

    def test_draw_is_deterministic_and_serializable(self):
        self.hand(9)
        self.add('first')
        self.add('second')
        result = self.engine.draw(self.state, 0, 3)
        self.assertEqual(result, self.engine.draw(self.state, 0, 3))
        self.assertEqual(result, json.loads(json.dumps(result)))


if __name__ == '__main__':
    unittest.main()
