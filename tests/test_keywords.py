from fixtures import assert_invalid, invalid_field
from fixtures import spell_bonus
from fixtures import enter

"""Stage 7: public hero powers, combat keywords and managed expiration."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.match import MatchEngine
from hearthstone.prototype import Prototype
from hearthstone import resources


def definition(catalog, card_id):
    return next(c for c in catalog['cards'] if c['cardId'] == card_id)


class Stage7CatalogTests(unittest.TestCase):

    def test_keyword_and_representative_stats(self):
        for cid, cost, attack, health, keyword in [
            ('CS2_124', 3, 3, 1, 'CHARGE'),
            ('GIL_113', 3, 3, 3, 'RUSH'),
            ('EX1_033', 6, 4, 5, 'WINDFURY'),
        ]:
            card = definition(load(), cid)
            self.assertEqual(
                card['baseStats'], dict(manaCost=cost, attack=attack, health=health)
            )
            self.assertEqual(card['keywords'], [keyword])

    def test_bad_hero_power_shapes(self):
        for mutation in (
            'collectible',
            'stats',
            'kind',
            'class',
            'policy',
            'empty',
            'overload',
        ):
            catalog = load()
            power = definition(catalog, 'CS2_034')
            if mutation == 'collectible':
                power['collectible'] = True
            if mutation == 'stats':
                power['baseStats']['attack'] = 1
            if mutation == 'kind':
                power['abilities'][0]['kind'] = 'SPELL_EFFECT'
            if mutation == 'class':
                power['abilities'][0]['effects'][0]['damageClass'] = 'SPELL'
            if mutation == 'policy':
                power['abilities'][0]['targeting'][
                    'legalityPolicy'
                ] = 'SPELL_SELECTED_TARGET'
            if mutation == 'empty':
                power['abilities'] = []
            if mutation == 'overload':
                power['overload'] = 1
            with self.subTest(mutation=mutation):
                assert_invalid(
                    self,
                    catalog,
                    {
                        'collectible': ("'collectible'", 'False was expected'),
                        'stats': ('baseStats', 'should not be valid under'),
                        'kind': 'CS2_034: incompatible ability kind',
                        'class': 'CS2_034: incompatible damage class',
                        'policy': 'CS2_034: incompatible targeting policy',
                        'empty': ("'abilities'", 'should be non-empty'),
                        'overload': 'CS2_034: hero power Overload is not supported',
                    }[mutation],
                )

    def test_unknown_keyword_duration_and_freeze_fields_rejected(self):
        for mutation in ('keyword', 'duration', 'freeze'):
            catalog = load()
            if mutation == 'keyword':
                definition(catalog, 'CS2_124')['keywords'] = ['FLYING']
            if mutation == 'duration':
                definition(catalog, 'CS2_188')['abilities'][0]['effects'][0][
                    'duration'
                ] = 'LATER'
            if mutation == 'freeze':
                definition(catalog, 'CS2_024')['abilities'][0]['effects'][1][
                    'duration'
                ] = 'LATER'
            assert_invalid(
                self,
                catalog,
                {
                    'keyword': ("'keywords'", "'FLYING' is not one of"),
                    'duration': ("'duration'", "'LATER' is not one of"),
                    'freeze': ('duration', 'Additional properties'),
                }[mutation],
            )


class ManagedFixture(unittest.TestCase):
    def setUp(self):
        self.catalog = load()
        self.restart()

    def restart(self, powers=None):
        self.engine = MatchEngine(self.catalog)
        self.state = self.engine.new_game(
            [['CS2_182'] * 30] * 2, seed=17, first_player=0, hero_powers=powers
        )
        self.state = self.engine.mulligan(self.state, 0, [])
        self.state = self.engine.mulligan(self.state, 1, [])
        self.refill()

    def refill(self):
        # Explicit arranged fixtures; production actions cannot grant free mana.
        for r in self.state['resources']:
            r.update(permanent=10, filled=10, temporary=0, locked=0, pendingOverload=0)
        resources.sync(self.state)

    def add(self, cid='CS2_182', entity_id='minion', player=0, zone='PLAY', **fields):
        e = self.engine.entity(entity_id, cid, player, zone)
        e.update(fields)
        self.state['entities'].append(e)
        enter(self.engine, self.state, e)
        return e

    def get(self, entity_id, state=None):
        return self.engine._entity(self.state if state is None else state, entity_id)

    def play(self, cid, target=None, entity_id='card'):
        self.add(cid, entity_id, self.state['activePlayer'], 'HAND')
        self.state = self.engine.play(
            self.state, self.state['activePlayer'], entity_id, target
        )

    def end(self):
        self.state = self.engine.end_turn(self.state, self.state['activePlayer'])

    def events(self, kind):
        return [e for e in self.state['events'] if e['type'] == kind]

    def assert_atomic_failure(self, fn):
        before = deepcopy(self.state)
        with self.assertRaises(ValueError):
            fn()
        self.assertEqual(self.state, before)


class HeroPowerTests(ManagedFixture):
    def test_fireblast_pays_once_and_is_not_a_card_play(self):
        before = deepcopy(self.state)
        spell_bonus(self.engine, self.state, 0, 3)
        self.state = self.engine.apply(
            self.state, 0, {'type': 'hero_power', 'target': 'hero-1'}
        )
        self.assertEqual(self.get('hero-1')['damage'], 1)
        self.assertEqual(self.state['mana'][0], 8)
        self.assertEqual(self.state['heroPowerUsesThisTurn'], [1, 0])
        self.assertEqual(self.state['cardsPlayedThisTurn'], [0, 0])
        self.assertEqual(self.get('hero-power-0')['zone'], 'PLAY')
        self.assertEqual(self.events('PLAY'), [])
        self.assertEqual(len(self.events('HERO_POWER')), 1)
        self.assertEqual(before['heroPowerUsesThisTurn'], [0, 0])
        self.assert_atomic_failure(
            lambda: self.engine.hero_power(self.state, 0, 'hero-1')
        )

    def test_powers_reset_only_on_their_own_turn(self):
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.end()
        self.assertEqual(self.state['heroPowerUsesThisTurn'], [1, 0])
        self.state = self.engine.hero_power(self.state, 1, 'hero-0')
        self.end()
        self.assertEqual(self.state['heroPowerUsesThisTurn'], [0, 1])
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 2)

    def test_target_errors_are_atomic_and_do_not_consume_power(self):
        self.add(entity_id='elusive', player=1, keywords=['ELUSIVE'])
        self.add(entity_id='stealth', player=1, keywords=['STEALTH'])
        self.add(entity_id='immune', player=1, keywords=['IMMUNE'])
        for target in (None, 'missing', 'hero-power-1', 'elusive', 'stealth', 'immune'):
            self.assert_atomic_failure(
                lambda: self.engine.hero_power(self.state, 0, target)
            )
        self.assertEqual(self.state['heroPowerUsesThisTurn'][0], 0)

    def test_cost_phase_player_and_finished_checks(self):
        self.state['resources'][0]['filled'] = 1
        resources.sync(self.state)
        self.assert_atomic_failure(
            lambda: self.engine.hero_power(self.state, 0, 'hero-1')
        )
        self.refill()
        for player in (1, True, -1):
            self.assert_atomic_failure(
                lambda: self.engine.hero_power(self.state, player, 'hero-1')
            )
        self.state['phase'] = 'MULLIGAN'
        self.assert_atomic_failure(
            lambda: self.engine.hero_power(self.state, 0, 'hero-1')
        )
        self.state['phase'] = 'MAIN'
        self.state = self.engine.concede(self.state, 1)
        self.assert_atomic_failure(
            lambda: self.engine.hero_power(self.state, 0, 'hero-1')
        )

    def test_frozen_hero_can_use_power_and_equip(self):
        self.get('hero-0')['keywords'].append('FROZEN')
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.play('CS2_106')
        self.assertEqual(self.engine.attack_targets(self.state, 'hero-0'), [])
        self.assertIsNotNone(self.engine.equipped_weapon(self.state, 0))

    def test_lesser_heal_and_full_health_use(self):
        self.restart(['CS1h_001', 'CS2_034'])
        self.get('hero-0')['damage'] = 3
        self.state = self.engine.hero_power(self.state, 0, 'hero-0')
        self.assertEqual(self.get('hero-0')['damage'], 1)
        self.end()
        self.end()
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.assertEqual(self.events('HEAL')[-1]['amount'], 0)
        self.assertEqual(self.state['heroPowerUsesThisTurn'][0], 1)

    def test_deathrattle_and_lethal_settle_within_power_action(self):
        self.add('EX1_096', 'loot', 1)
        self.state = self.engine.hero_power(self.state, 0, 'loot')
        self.assertEqual(self.get('loot')['zone'], 'GRAVEYARD')
        self.assertEqual(self.events('DEATHRATTLE')[-1]['source'], 'loot')
        self.end()
        self.end()
        self.get('hero-1')['damage'] = 29
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.assertEqual(
            (self.state['result'], self.state['phase']), ('PLAYER_0_WINS', 'FINISHED')
        )

    def test_shield_armor_and_friendly_target_legality(self):
        self.get('hero-0').update(armor=2, keywords=['STEALTH'])
        self.state = self.engine.hero_power(self.state, 0, 'hero-0')
        self.assertEqual(
            (self.get('hero-0')['armor'], self.get('hero-0')['damage']), (1, 0)
        )
        self.end()
        self.end()
        self.add(entity_id='shield', player=1, keywords=['DIVINE_SHIELD'])
        self.state = self.engine.hero_power(self.state, 0, 'shield')
        self.assertEqual(
            (self.get('shield')['damage'], self.get('shield')['keywords']), (0, [])
        )

    def test_power_setup_and_action_shapes_are_strict(self):
        for config in (
            ['CS2_182', 'CS2_034'],
            ['missing', None],
            ['CS2_034'],
            'CS2_034',
        ):
            with self.assertRaises(ValueError):
                self.engine.new_game([['CS2_182'] * 30] * 2, 1, hero_powers=config)
        for action in (
            {'type': 'hero_power', 'source': 'hero-power-1'},
            {'type': 'hero_power', 'extra': 1},
        ):
            self.assert_atomic_failure(lambda: self.engine.apply(self.state, 0, action))
        self.restart([None, None])
        self.assert_atomic_failure(
            lambda: self.engine.hero_power(self.state, 0, 'hero-1')
        )

    def test_powers_are_not_deck_or_hand_cards(self):
        with self.assertRaises(ValueError):
            self.engine.new_game([['CS2_034'] * 30] * 2, 1)
        self.add('CS2_034', 'bad-hand-power', zone='HAND')
        self.assert_atomic_failure(
            lambda: self.engine.play(self.state, 0, 'bad-hand-power', 'hero-1')
        )
        self.assertEqual(self.engine.attack_targets(self.state, 'hero-power-0'), [])

    def test_power_replay_and_json_restore(self):
        initial = deepcopy(self.state)
        result = self.engine.hero_power(self.state, 0, 'hero-1')
        self.assertEqual(
            result, self.engine.hero_power(json.loads(json.dumps(initial)), 0, 'hero-1')
        )
        self.assertEqual(self.state, initial)
        self.assertEqual(result, json.loads(json.dumps(result)))


class CombatKeywordTests(ManagedFixture):
    def test_charge_attacks_hero_on_play_and_is_still_limited(self):
        self.play('CS2_124', entity_id='wolf')
        self.assertIn('hero-1', self.engine.attack_targets(self.state, 'wolf'))
        self.state = self.engine.attack(self.state, 0, 'wolf', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 3)
        self.assertEqual(self.engine.attack_targets(self.state, 'wolf'), [])

    def test_rush_only_attacks_minions_on_play(self):
        self.add('EX1_015', 'enemy', 1)
        self.play('GIL_113', entity_id='rush')
        self.assertEqual(self.engine.attack_targets(self.state, 'rush'), ['enemy'])
        self.assert_atomic_failure(
            lambda: self.engine.attack(self.state, 0, 'rush', 'hero-1')
        )
        self.state = self.engine.attack(self.state, 0, 'rush', 'enemy')
        self.assertEqual(self.get('enemy')['zone'], 'GRAVEYARD')

    def test_rush_attacks_hero_next_turn(self):
        self.play('GIL_113', entity_id='rush')
        self.assertEqual(self.engine.attack_targets(self.state, 'rush'), [])
        self.end()
        self.end()
        self.assertIn('hero-1', self.engine.attack_targets(self.state, 'rush'))

    def test_charge_and_rush_obey_taunt_and_frozen(self):
        self.add('CS2_179', 'taunt', 1)
        for cid, eid in [('CS2_124', 'wolf'), ('GIL_113', 'rush')]:
            self.play(cid, entity_id=eid)
            self.assertEqual(self.engine.attack_targets(self.state, eid), ['taunt'])
            self.get(eid)['keywords'].append('FROZEN')
            self.assertEqual(self.engine.attack_targets(self.state, eid), [])

    def test_charge_overrides_rush_restriction_and_silence_restores_exhaustion(self):
        self.play('GIL_113', entity_id='rush')
        self.get('rush')['keywords'].append('CHARGE')  # arranged keyword-gain fixture
        self.assertIn('hero-1', self.engine.attack_targets(self.state, 'rush'))
        self.play('EX1_048', 'rush', 'silence')
        self.assertEqual(self.engine.attack_targets(self.state, 'rush'), [])

    def test_windfury_exhaustion_and_two_attacks_after_refresh(self):
        self.play('EX1_033', entity_id='harpy')
        self.assertEqual(self.engine.attack_targets(self.state, 'harpy'), [])
        self.end()
        self.end()
        for _ in range(2):
            self.state = self.engine.attack(self.state, 0, 'harpy', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 8)
        self.assert_atomic_failure(
            lambda: self.engine.attack(self.state, 0, 'harpy', 'hero-1')
        )
        self.end()
        self.end()
        self.assertIn('hero-1', self.engine.attack_targets(self.state, 'harpy'))

    def test_dynamic_windfury_never_refunds_attack_count(self):
        e = self.add(ready=True)
        self.state = self.engine.attack(self.state, 0, e['id'], 'hero-1')
        self.get(e['id'])['keywords'].append('WINDFURY')
        self.assertIn('hero-1', self.engine.attack_targets(self.state, e['id']))
        self.state = self.engine.attack(self.state, 0, e['id'], 'hero-1')
        self.get(e['id'])['keywords'].clear()
        self.get(e['id'])['keywords'].append('WINDFURY')
        self.assertEqual(self.engine.attack_targets(self.state, e['id']), [])
        self.assertEqual(self.get(e['id'])['attacksThisTurn'], 2)

    def test_losing_windfury_after_one_attack_prevents_second(self):
        self.add('EX1_033', 'harpy', ready=True)
        self.state = self.engine.attack(self.state, 0, 'harpy', 'hero-1')
        self.play('EX1_048', 'harpy', 'silence')
        self.assertEqual(self.engine.attack_targets(self.state, 'harpy'), [])
        self.assertEqual(self.get('harpy')['attacksThisTurn'], 1)

    def test_hero_weapon_windfury_loss_and_replacement_keep_count(self):
        # A weapon-instance fixture tests generic combat without claiming a new card definition.
        self.play('CS2_106', entity_id='axe')
        self.get('axe')['keywords'].append('WINDFURY')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertIn('hero-1', self.engine.attack_targets(self.state, 'hero-0'))
        self.play('CS2_106', entity_id='replacement')
        self.assertEqual(self.engine.attack_targets(self.state, 'hero-0'), [])
        self.get('replacement')['keywords'].append('WINDFURY')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get('hero-0')['attacksThisTurn'], 2)
        self.assertEqual(self.get('replacement')['durability'], 1)
        self.assertEqual(self.engine.attack_targets(self.state, 'hero-0'), [])


class FreezeTests(ManagedFixture):
    def setUp(self):
        super().setUp()
        # Isolate thaw timing from lethal damage to 1-Health Charge cards.
        definition(self.catalog, 'CS2_024')['abilities'][0]['effects'][0]['amount'][
            'value'
        ] = 0
        self.restart()

    def freeze(self, target, eid='frost'):
        self.play('CS2_024', target, eid)

    def test_representative_frostbolt_damage_and_freeze(self):
        self.catalog = load()
        self.restart()
        self.add(entity_id='enemy', player=1)
        self.freeze('enemy')
        self.assertEqual(self.get('enemy')['damage'], 3)
        self.assertIn('FROZEN', self.get('enemy')['keywords'])
        self.assertEqual(self.get('frost')['zone'], 'GRAVEYARD')

    def test_freeze_before_attack_thaws_at_current_turn_end(self):
        self.add(ready=True)
        self.freeze('minion')
        self.assertEqual(self.engine.attack_targets(self.state, 'minion'), [])
        self.end()
        self.assertNotIn('FROZEN', self.get('minion')['keywords'])
        self.assertEqual(self.events('THAW')[-1]['target'], 'minion')

    def test_freeze_after_attack_waits_through_next_own_turn(self):
        self.add(ready=True)
        self.state = self.engine.attack(self.state, 0, 'minion', 'hero-1')
        self.freeze('minion')
        self.end()
        self.end()
        self.assertIn('FROZEN', self.get('minion')['keywords'])
        self.assertEqual(self.engine.attack_targets(self.state, 'minion'), [])
        self.end()
        self.assertNotIn('FROZEN', self.get('minion')['keywords'])

    def test_opponent_freeze_survives_start_and_ends_after_own_turn(self):
        self.add(entity_id='enemy', player=1, ready=True)
        self.freeze('enemy')
        self.end()
        self.assertIn('FROZEN', self.get('enemy')['keywords'])
        self.assertEqual(self.engine.attack_targets(self.state, 'enemy'), [])
        self.end()
        self.assertNotIn('FROZEN', self.get('enemy')['keywords'])

    def test_exhausted_minion_misses_next_turn(self):
        self.play('CS2_182', entity_id='new')
        self.freeze('new')
        self.end()
        self.end()
        self.assertIn('FROZEN', self.get('new')['keywords'])
        self.end()
        self.assertNotIn('FROZEN', self.get('new')['keywords'])

    def test_charge_without_spent_attack_thaws_current_turn(self):
        self.play('CS2_124', entity_id='wolf')
        self.freeze('wolf')
        self.end()
        self.assertNotIn('FROZEN', self.get('wolf')['keywords'])

    def test_rush_without_legal_minion_target_misses_next_turn(self):
        self.play('GIL_113', entity_id='rush')
        self.freeze('rush')
        self.end()
        self.end()
        self.assertIn('FROZEN', self.get('rush')['keywords'])
        self.end()
        self.assertNotIn('FROZEN', self.get('rush')['keywords'])

    def test_rush_with_legal_minion_target_thaws_current_turn(self):
        self.add('EX1_015', 'enemy', 1)
        self.play('GIL_113', entity_id='rush')
        self.freeze('rush')
        self.end()
        self.assertNotIn('FROZEN', self.get('rush')['keywords'])

    def test_windfury_after_first_attack_uses_supplied_kw05_policy(self):
        self.add('EX1_033', 'harpy', ready=True)
        self.state = self.engine.attack(self.state, 0, 'harpy', 'hero-1')
        self.freeze('harpy')
        self.end()
        self.end()
        self.assertIn('FROZEN', self.get('harpy')['keywords'])
        self.end()
        self.assertNotIn('FROZEN', self.get('harpy')['keywords'])

    def test_refreeze_does_not_stack_extra_skipped_turns(self):
        self.add(entity_id='enemy', player=1)
        self.freeze('enemy', 'frost1')
        first = deepcopy(self.get('enemy')['freezeUntil'])
        self.freeze('enemy', 'frost2')
        self.assertEqual(self.get('enemy')['freezeUntil'], first)
        self.end()
        self.end()
        self.assertNotIn('FROZEN', self.get('enemy')['keywords'])
        self.assertEqual(len(self.events('THAW')), 1)

    def test_silence_and_transform_discard_freeze_deadline(self):
        self.add(entity_id='a')
        self.add(entity_id='b')
        self.freeze('a', 'frost1')
        self.freeze('b', 'frost2')
        self.play('EX1_048', 'a', 'silence')
        self.refill()
        self.play('CS2_022', 'b', 'poly')
        for eid in ('a', 'b'):
            self.assertNotIn('FROZEN', self.get(eid)['keywords'])
            self.assertNotIn('freezeUntil', self.get(eid))
        self.end()
        self.end()
        self.end()
        self.assertEqual(self.events('THAW'), [])

    def test_frozen_minion_still_retaliates(self):
        self.add(entity_id='enemy', player=1)
        self.add(entity_id='attacker', ready=True)
        self.freeze('enemy')
        self.state = self.engine.attack(self.state, 0, 'attacker', 'enemy')
        self.assertEqual(self.get('attacker')['damage'], 4)

    def test_frozen_hero_with_no_attack_waits_next_own_turn(self):
        self.freeze('hero-0')
        self.end()
        self.end()
        self.assertIn('FROZEN', self.get('hero-0')['keywords'])
        self.end()
        self.assertNotIn('FROZEN', self.get('hero-0')['keywords'])

    def test_armed_hero_frozen_before_attack_thaws_current_turn(self):
        self.play('CS2_106', entity_id='axe')
        self.freeze('hero-0')
        self.assertEqual(self.engine.attack_targets(self.state, 'hero-0'), [])
        self.end()
        self.assertNotIn('FROZEN', self.get('hero-0')['keywords'])

    def test_dead_frozen_minion_is_not_thawed_from_graveyard(self):
        self.add(entity_id='enemy', player=1)
        self.freeze('enemy')
        self.play('CS2_029', 'enemy', 'fireball')
        self.end()
        self.end()
        self.assertEqual(self.get('enemy')['zone'], 'GRAVEYARD')
        self.assertEqual(self.events('THAW'), [])

    def test_freeze_requires_managed_timing(self):
        engine = Prototype(load())
        state = engine.state()
        state['entities'].append(engine.entity('spell', 'CS2_024', 0, 'HAND'))
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            engine.play(state, 0, 'spell', 'hero-1')
        self.assertEqual(state, before)


class ExpirationTests(ManagedFixture):
    def test_abusive_sergeant_buff_expires_on_current_turn_even_on_enemy(self):
        self.add(entity_id='enemy', player=1)
        self.play('CS2_188', 'enemy', 'sergeant')
        self.assertEqual(self.engine.current_attack(self.state, self.get('enemy')), 6)
        self.end()
        self.assertEqual(self.engine.current_attack(self.state, self.get('enemy')), 4)
        self.assertEqual(self.get('enemy')['enchantments'], [])
        self.assertEqual(len(self.events('BUFF_EXPIRED')), 1)

    def test_permanent_buff_and_aura_survive_temporary_expiration(self):
        self.add(entity_id='yeti')
        self.add('CS2_222', 'champ')
        self.play('CS2_092', 'yeti', 'kings')
        self.play('CS2_188', 'yeti', 'sergeant')
        self.assertEqual(self.engine.current_attack(self.state, self.get('yeti')), 11)
        self.end()
        self.assertEqual(self.engine.current_attack(self.state, self.get('yeti')), 9)
        self.assertEqual(len(self.get('yeti')['enchantments']), 1)

    def test_end_hooks_see_buff_before_expiration(self):
        card = definition(self.catalog, 'CS2_182')
        card['abilities'] = [
            dict(
                kind='END_OF_TURN',
                effects=[
                    dict(op='DRAW_CARD', count=1, targetPlayer='EFFECT_CONTROLLER')
                ],
            )
        ]
        self.restart()
        self.add(entity_id='yeti')
        self.play('CS2_188', 'yeti', 'sergeant')
        self.end()
        kinds = [e['type'] for e in self.state['events']]
        self.assertLess(kinds.index('TURN_TRIGGER'), kinds.index('BUFF_EXPIRED'))
        self.assertLess(
            kinds.index('BUFF_EXPIRED'),
            kinds.index('THAW') if 'THAW' in kinds else len(kinds),
        )

    def test_next_turn_expiration_anchors_effect_controller_not_recipient(self):
        definition(self.catalog, 'CS2_092')['abilities'][0]['effects'][0][
            'duration'
        ] = 'START_OF_NEXT_TURN'
        self.restart()
        self.add(entity_id='enemy', player=1)
        self.play('CS2_092', 'enemy', 'kings')
        self.end()
        self.assertEqual(self.engine.current_attack(self.state, self.get('enemy')), 8)
        self.end()
        self.assertEqual(self.engine.current_attack(self.state, self.get('enemy')), 4)
        self.assertEqual(self.events('BUFF_EXPIRED')[-1]['phase'], 'START_OF_TURN')

    def test_start_expiration_precedes_start_hooks_and_draw(self):
        definition(self.catalog, 'CS2_092')['abilities'][0]['effects'][0][
            'duration'
        ] = 'START_OF_NEXT_TURN'
        definition(self.catalog, 'CS2_182')['abilities'] = [
            dict(
                kind='START_OF_TURN',
                effects=[
                    dict(op='DRAW_CARD', count=1, targetPlayer='EFFECT_CONTROLLER')
                ],
            )
        ]
        self.restart()
        self.add(entity_id='yeti')
        self.play('CS2_092', 'yeti', 'kings')
        self.end()
        self.state['events'] = []
        self.end()
        kinds = [e['type'] for e in self.state['events']]
        self.assertLess(kinds.index('BUFF_EXPIRED'), kinds.index('TURN_TRIGGER'))
        self.assertLess(kinds.index('TURN_TRIGGER'), kinds.index('DRAW'))

    def test_temporary_health_expiration_uses_existing_cap_policy(self):
        definition(self.catalog, 'CS2_092')['abilities'][0]['effects'][0][
            'duration'
        ] = 'END_OF_TURN'
        self.restart()
        self.add(entity_id='yeti')
        self.play('CS2_092', 'yeti', 'kings')
        self.get('yeti')['damage'] = 8  # 1 current Health of 9
        self.end()
        self.assertEqual(self.engine.max_health(self.get('yeti'), self.state), 5)
        self.assertEqual(self.engine.current_health(self.state, self.get('yeti')), 1)
        self.assertEqual(self.get('yeti')['zone'], 'PLAY')

    def test_silence_and_transform_remove_timers_without_later_expiration(self):
        self.add(entity_id='a')
        self.add(entity_id='b')
        self.play('CS2_188', 'a', 's1')
        self.play('CS2_188', 'b', 's2')
        self.play('EX1_048', 'a', 'silence')
        self.play('CS2_022', 'b', 'poly')
        self.end()
        self.assertEqual(self.events('BUFF_EXPIRED'), [])

    def test_expiration_does_not_refund_attacks(self):
        self.add(entity_id='yeti', ready=True)
        self.play('CS2_188', 'yeti', 'sergeant')
        self.state = self.engine.attack(self.state, 0, 'yeti', 'hero-1')
        self.end()
        self.assertEqual(self.get('yeti')['attacksThisTurn'], 1)
        self.assertEqual(self.engine.current_attack(self.state, self.get('yeti')), 4)

    def test_buff_expires_after_source_death_and_only_once(self):
        self.add(entity_id='enemy', player=1)
        self.play('CS2_188', 'enemy', 'sergeant')
        self.play('CS2_029', 'sergeant', 'fireball')
        self.assertEqual(self.engine.current_attack(self.state, self.get('enemy')), 6)
        self.end()
        self.end()
        self.end()
        self.assertEqual(self.engine.current_attack(self.state, self.get('enemy')), 4)
        self.assertEqual(len(self.events('BUFF_EXPIRED')), 1)

    def test_roundtrip_preserves_deadlines_and_end_turn_is_atomic(self):
        self.add(entity_id='yeti', ready=True)
        self.play('CS2_188', 'yeti', 'sergeant')
        self.play('CS2_024', 'hero-0', 'freeze')
        before = deepcopy(self.state)
        result = self.engine.end_turn(self.state, 0)
        self.assertEqual(
            result, self.engine.end_turn(json.loads(json.dumps(self.state)), 0)
        )
        self.assertEqual(self.state, before)
        self.assertEqual(result, json.loads(json.dumps(result)))

    def test_temporary_buff_requires_managed_clock(self):
        engine = Prototype(load())
        state = engine.state()
        state['entities'].extend(
            [
                engine.entity('yeti', 'CS2_182', 0),
                engine.entity('sergeant', 'CS2_188', 0, 'HAND'),
            ]
        )
        enter(engine, state, engine._entity(state, 'yeti'))
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            engine.play(state, 0, 'sergeant', 'yeti')
        self.assertEqual(state, before)


class CompleteKeywordGameTests(unittest.TestCase):
    def test_public_actions_replay_across_json_checkpoints(self):
        from examples.play_keywords import run

        final, actions = run(0)
        engine = MatchEngine(load())
        pool = [
            'CS2_124',
            'GIL_113',
            'EX1_033',
            'CS2_024',
            'CS2_188',
            'CS2_106',
            'EX1_096',
            'EX1_015',
            'CS2_182',
            'CS2_179',
        ] * 3
        state = engine.new_game(
            [pool, list(reversed(pool))], 0, hero_powers=['CS2_034', 'CS1h_001']
        )
        for entry in actions:
            state = engine.apply(
                json.loads(json.dumps(state)), entry['player'], entry['action']
            )
        self.assertEqual(state, final)
        self.assertEqual(
            (final['result'], final['turn'], len(actions)), ('PLAYER_1_WINS', 19, 92)
        )
        kinds = {e['type'] for e in final['events']}
        self.assertTrue(
            {'HERO_POWER', 'FREEZE', 'THAW', 'BUFF_EXPIRED', 'ATTACK', 'DURABILITY'}
            <= kinds
        )


if __name__ == '__main__':
    unittest.main()
