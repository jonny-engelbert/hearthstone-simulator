from fixtures import assert_invalid, invalid_field
from fixtures import spell_bonus
from fixtures import enter

"""Stage 4: death snapshots, ordered waves and synthetic nested Deathrattles."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.prototype import Prototype, ResolutionLimitError


def card(catalog, card_id):
    return next(c for c in catalog['cards'] if c['cardId'] == card_id)


def damage(amount=1):
    return {
        'op': 'DEAL_DAMAGE',
        'amount': {'kind': 'CONSTANT', 'value': amount},
        'recipient': {
            'kind': 'QUERY',
            'selector': {'zone': 'PLAY', 'entityKind': 'MINION', 'controller': 'ANY'},
            'capture': 'EFFECT_START',
        },
        'missingRecipient': 'SKIP',
        'application': 'SINGLE_DAMAGE_BATCH',
        'damageClass': 'ABILITY',
    }


def synthetic(catalog, card_id='TEST_bomb', health=1, effects=None):
    definition = deepcopy(card(catalog, 'EX1_096'))
    definition.update(
        cardId=card_id,
        name='Synthetic test Deathrattle',
        baseStats={'manaCost': 1, 'attack': 1, 'health': health},
    )
    definition['abilities'][0]['effects'] = effects or [damage()]
    catalog['cards'].append(definition)
    return definition


class DeathCatalogTests(unittest.TestCase):
    def test_loot_hoarder_definition(self):
        loot = card(load(), 'EX1_096')
        self.assertEqual(loot['baseStats'], {'manaCost': 2, 'attack': 2, 'health': 1})
        self.assertEqual((loot['set'], loot['rarity']), ('EXPERT1', 'COMMON'))
        self.assertEqual(
            loot['abilities'],
            [
                {
                    'kind': 'DEATHRATTLE',
                    'effects': [
                        {
                            'op': 'DRAW_CARD',
                            'count': 1,
                            'targetPlayer': 'CONTROLLER_AT_DEATH',
                        }
                    ],
                }
            ],
        )

    def test_deathrattle_label_and_kind_must_agree(self):
        for field in ('mechanics', 'abilities'):
            catalog = load()
            card(catalog, 'EX1_096')[field] = []
            assert_invalid(
                self, catalog, 'EX1_096: DEATHRATTLE label and ability disagree'
            )

    def test_deathrattle_cannot_require_a_selected_target(self):
        catalog = load()
        ability = card(catalog, 'EX1_096')['abilities'][0]
        ability['targeting'] = deepcopy(
            card(catalog, 'CS2_042')['abilities'][0]['targeting']
        )
        assert_invalid(
            self,
            catalog,
            'EX1_096: triggered abilities cannot request a selected target',
        )

    def test_controller_at_death_invalid_for_battlecry_or_spell(self):
        for card_id in ('EX1_015', 'CS2_029'):
            catalog = load()
            card(catalog, card_id)['abilities'][0]['effects'] = [
                {'op': 'DRAW_CARD', 'count': 1, 'targetPlayer': 'CONTROLLER_AT_DEATH'}
            ]
            assert_invalid(
                self, catalog, f'{card_id}: controller-at-death requires a Deathrattle'
            )

    def test_duplicate_abilities_and_spell_deathrattles_rejected(self):
        catalog = load()
        loot = card(catalog, 'EX1_096')
        loot['abilities'].append(deepcopy(loot['abilities'][0]))
        assert_invalid(self, catalog, 'EX1_096: duplicate ability kind')
        catalog = load()
        spell = card(catalog, 'CS2_029')
        spell['abilities'] = deepcopy(card(catalog, 'EX1_096')['abilities'])
        spell['mechanics'] = ['DEATHRATTLE']
        assert_invalid(self, catalog, 'CS2_029: incompatible ability kind')

    def test_deathrattle_damage_is_ability_damage(self):
        catalog = load()
        fixture = synthetic(catalog)
        self.assertEqual(validate(catalog), [])
        fixture['abilities'][0]['effects'][0]['damageClass'] = 'SPELL'
        assert_invalid(self, catalog, 'TEST_bomb: incompatible damage class')

    def test_policy_and_destroy_recipients_are_strict(self):
        catalog = load()
        catalog['deathResolutionPolicy'] = 'UNKNOWN'
        assert_invalid(
            self,
            catalog,
            ("'deathResolutionPolicy'", "'DEATH_WAVES_FIFO' was expected"),
        )
        catalog = load()
        effect = damage()
        effect = {
            'op': 'DESTROY',
            'recipient': effect['recipient'],
            'missingRecipient': 'SKIP',
        }
        synthetic(catalog, effects=[effect])
        self.assertEqual(validate(catalog), [])
        effect['recipient']['selector']['entityKind'] = 'CHARACTER'
        assert_invalid(self, catalog, 'TEST_bomb: destroy requires minion recipients')


class DeathProcessingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load()
        self.engine = Prototype(self.catalog)
        self.state = self.engine.state()

    def add(self, entity_id, card_id='EX1_096', player=0, zone='PLAY', order=None):
        entity = self.engine.entity(entity_id, card_id, player, zone)
        if order is not None:
            entity['playOrder'] = order
        self.state['entities'].append(entity)
        if zone == 'DECK':
            self.state['decks'][player].append(entity_id)
        enter(self.engine, self.state, entity)
        return entity

    @staticmethod
    def get(state, entity_id):
        return next(e for e in state['entities'] if e['id'] == entity_id)

    @staticmethod
    def events(state, kind):
        return [e for e in state['events'] if e['type'] == kind]

    def draws(self, player=0, count=1):
        for i in range(count):
            self.add(f'deck-{player}-{i}', 'CS2_182', player, 'DECK')

    def test_play_does_not_execute_deathrattle(self):
        self.add('loot', zone='HAND')
        self.draws()
        result = self.engine.play(self.state, 0, 'loot')
        self.assertEqual(result['mana'][0], 8)
        self.assertEqual(result['decks'][0], ['deck-0-0'])
        self.assertEqual(self.events(result, 'DEATHRATTLE'), [])
        self.assertGreater(self.get(result, 'loot')['playOrder'], 0)

    def test_spell_kill_draws_after_death_batch(self):
        self.add('loot', player=1)
        self.add('fireball', 'CS2_029', zone='HAND')
        self.draws(1)
        result = self.engine.play(self.state, 0, 'fireball', 'loot')
        self.assertEqual(self.get(result, 'loot')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get(result, 'deck-1-0')['zone'], 'HAND')
        self.assertEqual(
            [e['type'] for e in result['events']],
            [
                'PLAY',
                'DAMAGE',
                'DEATH_BATCH',
                'DEATHRATTLE',
                'REACTION',
                'DRAW_ATTEMPT',
                'DRAW',
            ],
        )

    def test_simultaneous_combat_deathrattles_use_global_play_order(self):
        a = self.add('a', order=20)
        b = self.add('b', player=1, order=10)
        a['ready'] = True
        self.draws(0)
        self.draws(1)
        result = self.engine.attack(self.state, 0, 'a', 'b')
        self.assertEqual(self.events(result, 'DEATH_BATCH')[0]['targets'], ['b', 'a'])
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DEATHRATTLE')], ['b', 'a']
        )
        self.assertEqual([e['player'] for e in self.events(result, 'DRAW')], [1, 0])

    def test_order_survives_entity_store_reordering(self):
        a = self.add('a', order=2)
        b = self.add('b', order=1)
        a['damage'] = b['damage'] = 1
        self.draws(count=2)
        result = self.engine.resolve_deaths(self.state)
        state2 = deepcopy(self.state)
        state2['entities'].reverse()
        result2 = self.engine.resolve_deaths(state2)
        self.assertEqual(result['events'], result2['events'])
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DRAW_ATTEMPT')], ['b', 'a']
        )

    def test_play_chronology_is_recorded_across_normal_actions(self):
        self.add('first', zone='HAND')
        self.add('second', zone='HAND')
        self.state = self.engine.play(self.state, 0, 'first')
        self.state = self.engine.play(self.state, 0, 'second')
        self.assertLess(
            self.get(self.state, 'first')['playOrder'],
            self.get(self.state, 'second')['playOrder'],
        )
        self.get(self.state, 'first')['damage'] = 1
        self.get(self.state, 'second')['damage'] = 1
        self.state['entities'].reverse()
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DEATHRATTLE')],
            ['first', 'second'],
        )

    def test_snapshots_preserve_control_ownership_position_and_definition(self):
        self.add('neighbor', 'CS2_182', player=1, order=1)
        loot = self.add('stolen', player=1, order=2)
        loot.update(owner=0, damage=1, enchantments=['fixture-buff'])
        self.draws(1)
        result = self.engine.resolve_deaths(self.state)
        snap = result['deathHistory'][0]
        self.assertEqual((snap['controllerAtDeath'], snap['position']), (1, 1))
        self.assertEqual(
            (snap['entity']['owner'], snap['entity']['revision']), (0, 'foundation-v4')
        )
        self.assertEqual(snap['entity']['zone'], 'PLAY')
        self.assertEqual(self.events(result, 'DRAW')[0]['player'], 1)
        self.get(result, 'stolen')['controller'] = 0
        self.get(result, 'stolen')['enchantments'].clear()
        self.assertEqual(snap['entity']['controller'], 1)
        self.assertEqual(snap['entity']['enchantments'], ['fixture-buff'])

    def test_removed_batch_cannot_be_hit_again_by_deathrattle(self):
        synthetic(self.catalog)
        self.engine = Prototype(self.catalog)
        a = self.add('bomb', 'TEST_bomb', order=1)
        b = self.add('loot', order=2)
        a['damage'] = b['damage'] = 1
        self.draws()
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.events(result, 'DAMAGE'), [])
        self.assertEqual(
            self.events(result, 'DEATH_BATCH')[0]['targets'], ['bomb', 'loot']
        )
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DEATHRATTLE')], ['bomb', 'loot']
        )

    def test_nested_deaths_wait_until_current_wave_finishes(self):
        synthetic(self.catalog)
        self.engine = Prototype(self.catalog)
        self.add('bomb', 'TEST_bomb', order=10)['damage'] = 1
        self.add('sibling', order=20)['damage'] = 1
        self.add('child', order=1)
        self.draws(count=2)
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(
            [e['targets'] for e in self.events(result, 'DEATH_BATCH')],
            [['bomb', 'sibling'], ['child']],
        )
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DEATHRATTLE')],
            ['bomb', 'sibling', 'child'],
        )
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DRAW_ATTEMPT')],
            ['sibling', 'child'],
        )

    def test_one_deathrattle_completes_all_effects_before_new_deaths(self):
        effects = [
            damage(),
            {'op': 'DRAW_CARD', 'count': 1, 'targetPlayer': 'CONTROLLER_AT_DEATH'},
        ]
        synthetic(self.catalog, effects=effects)
        self.engine = Prototype(self.catalog)
        self.add('bomb', 'TEST_bomb', order=1)['damage'] = 1
        self.add('child', order=2)
        self.draws(count=2)
        result = self.engine.resolve_deaths(self.state)
        kinds = [e['type'] for e in result['events']]
        first_draw = kinds.index('DRAW')
        second_batch = kinds.index('DEATH_BATCH', 1)
        self.assertLess(first_draw, second_batch)
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DRAW_ATTEMPT')],
            ['bomb', 'child'],
        )

    def chain(self, count, limit=1000):
        for i in range(count):
            synthetic(self.catalog, f'TEST_chain_{i}', max(1, i))
        self.engine = Prototype(self.catalog, max_deathrattles=limit)
        for i in range(count):
            self.add(f'chain-{i}', f'TEST_chain_{i}', player=i % 2, order=i + 1)
        self.get(self.state, 'chain-0')['damage'] = 1

    def test_twelve_wave_chain_drains_iteratively_without_repeating_sources(self):
        self.chain(12)
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(len(self.events(result, 'DEATH_BATCH')), 12)
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DEATHRATTLE')],
            [f'chain-{i}' for i in range(12)],
        )
        self.assertEqual(len(result['deathHistory']), 12)
        self.assertFalse(
            any(
                e['zone'] == 'PLAY' and e['kind'] == 'MINION'
                for e in result['entities']
            )
        )

    def test_budget_failure_is_explicit_and_atomic(self):
        self.chain(4, limit=2)
        before = deepcopy(self.state)
        with self.assertRaises(ResolutionLimitError):
            self.engine.resolve_deaths(self.state)
        self.assertEqual(self.state, before)
        self.assertIsNone(self.state['result'])

    def test_pending_destroy_is_collected_without_lethal_damage(self):
        self.add('loot', order=1)['pendingDestroy'] = True
        self.draws()
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.get(result, 'loot')['zone'], 'GRAVEYARD')
        self.assertEqual(len(self.events(result, 'DEATHRATTLE')), 1)

    def test_destroy_effect_causes_next_wave_and_deathrattle(self):
        effect = {
            'op': 'DESTROY',
            'recipient': damage()['recipient'],
            'missingRecipient': 'SKIP',
        }
        synthetic(self.catalog, effects=[effect])
        self.engine = Prototype(self.catalog)
        self.add('destroyer', 'TEST_bomb', order=1)['damage'] = 1
        self.add('child', order=2)
        self.draws()
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DEATHRATTLE')],
            ['destroyer', 'child'],
        )
        self.assertEqual(
            self.events(result, 'DESTROY'),
            [{'type': 'DESTROY', 'source': 'destroyer', 'target': 'child'}],
        )

    def test_deathrattle_damage_ignores_spell_damage(self):
        synthetic(self.catalog)
        self.engine = Prototype(self.catalog)
        self.add('bomb', 'TEST_bomb')['damage'] = 1
        self.add('yeti', 'CS2_182')
        spell_bonus(self.engine, self.state, 0, 3)
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.get(result, 'yeti')['damage'], 1)

    def test_silenced_fixture_death_has_no_deathrattle(self):
        self.add('loot').update(damage=1, silenced=True)
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.events(result, 'DEATHRATTLE'), [])
        self.assertEqual(result['fatigue'], [0, 0])
        self.assertEqual(result['deathHistory'][0]['abilities'], [])

    def test_polymorph_does_not_trigger_old_deathrattle_on_later_death(self):
        self.add('loot', player=1, order=1)
        self.add('poly', 'CS2_022', zone='HAND')
        self.state = self.engine.play(self.state, 0, 'poly', 'loot')
        self.assertEqual(self.state['deathHistory'], [])
        self.assertGreater(self.get(self.state, 'loot')['playOrder'], 1)
        self.get(self.state, 'loot')['damage'] = 1
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.events(result, 'DEATHRATTLE'), [])
        self.assertEqual(result['deathHistory'][0]['entity']['cardId'], 'CS2_tk1')

    def test_burning_loot_hoarder_does_not_trigger_deathrattle(self):
        for i in range(10):
            self.add(f'hand-{i}', 'CS2_182', zone='HAND')
        self.add('loot', zone='DECK')
        result = self.engine.draw(self.state, 0)
        self.assertEqual(len(self.events(result, 'BURN')), 1)
        self.assertEqual(self.events(result, 'DEATHRATTLE'), [])
        self.assertEqual(result['deathHistory'], [])

    def test_deathrattle_draw_into_full_hand_burns_once(self):
        for i in range(10):
            self.add(f'hand-{i}', 'CS2_182', zone='HAND')
        self.add('loot')['damage'] = 1
        self.draws()
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(len(self.events(result, 'DEATHRATTLE')), 1)
        self.assertEqual(len(self.events(result, 'BURN')), 1)
        self.assertEqual(len(self.events(result, 'DRAW')), 0)

    def test_multiple_loot_deaths_escalate_fatigue_in_order(self):
        self.add('second', order=2)['damage'] = 1
        self.add('first', order=1)['damage'] = 1
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(
            [e['source'] for e in self.events(result, 'DRAW_ATTEMPT')],
            ['first', 'second'],
        )
        self.assertEqual([e['amount'] for e in self.events(result, 'FATIGUE')], [1, 2])
        self.assertEqual(self.get(result, 'hero-0')['damage'], 3)

    def test_all_queued_deathrattles_finish_before_final_hero_result(self):
        self.add('a', order=1)['damage'] = 1
        self.add('b', player=1, order=2)['damage'] = 1
        self.get(self.state, 'hero-0')['damage'] = 29
        self.get(self.state, 'hero-1')['damage'] = 29
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(result['result'], 'DRAW')
        self.assertEqual(result['fatigue'], [1, 1])
        self.assertEqual(len(self.events(result, 'DEATHRATTLE')), 2)
        with self.assertRaises(ValueError):
            self.engine.resolve_deaths(result)

    def test_settled_checkpoint_is_idempotent(self):
        self.add('loot')['damage'] = 1
        self.state = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.engine.resolve_deaths(self.state), self.state)

    def test_malformed_stamps_are_rejected_without_committing(self):
        self.add('a', order=1)['damage'] = 1
        self.add('b', order=1)['damage'] = 1
        before = deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'playOrder'):
            self.engine.resolve_deaths(self.state)
        self.assertEqual(self.state, before)

    def test_mixed_battlecry_and_deathrattle_are_distinct(self):
        loot = card(self.catalog, 'EX1_096')
        loot['mechanics'].append('BATTLECRY')
        loot['abilities'].append(
            deepcopy(card(self.catalog, 'EX1_015')['abilities'][0])
        )
        self.engine = Prototype(self.catalog)
        self.add('mixed', zone='HAND')
        self.draws(count=2)
        self.state = self.engine.play(self.state, 0, 'mixed')
        self.assertEqual(len(self.events(self.state, 'DRAW')), 1)
        self.assertEqual(len(self.events(self.state, 'DEATHRATTLE')), 0)
        self.get(self.state, 'mixed')['damage'] = 1
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(len(self.events(result, 'DRAW')), 2)
        self.assertEqual(len(self.events(result, 'DEATHRATTLE')), 1)

    def test_failed_play_resolution_keeps_mana_and_input_unchanged(self):
        self.chain(4, limit=1)
        # The normal play path invokes the same death drain and must not commit
        # partially spent mana/history when that drain fails.
        self.add('yeti', 'CS2_182', zone='HAND')
        before = deepcopy(self.state)
        with self.assertRaises(ResolutionLimitError):
            self.engine.play(self.state, 0, 'yeti')
        self.assertEqual(self.state, before)

    def test_resolution_is_deterministic_serializable_and_input_immutable(self):
        self.add('loot', order=1)['damage'] = 1
        self.draws()
        before = deepcopy(self.state)
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.state, before)
        self.assertEqual(result, self.engine.resolve_deaths(self.state))
        self.assertEqual(result, json.loads(json.dumps(result)))


if __name__ == '__main__':
    unittest.main()
