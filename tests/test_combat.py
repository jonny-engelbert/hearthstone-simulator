from fixtures import assert_invalid, invalid_field
from fixtures import spell_bonus
from fixtures import enter

"""Stage 3: plain weapons and normal hero/minion combat."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.prototype import Prototype


class WeaponCatalogTests(unittest.TestCase):

    def test_historical_axe_definition(self):
        axe = next(c for c in load()['cards'] if c['cardId'] == 'CS2_106')
        self.assertEqual(axe['type'], 'WEAPON')
        self.assertEqual(axe['classes'], ['WARRIOR'])
        self.assertEqual(
            axe['baseStats'], {'manaCost': 2, 'attack': 3, 'durability': 2}
        )
        self.assertEqual(axe['abilities'], [])

    def test_weapon_stat_shapes_are_strict(self):
        for field, value in [
            ('health', 2),
            ('durability', 0),
            ('durability', -1),
            ('durability', True),
            ('durability', 1.5),
            ('attack', -1),
        ]:
            with self.subTest(field=field, value=value):
                catalog = load()
                next(c for c in catalog['cards'] if c['cardId'] == 'CS2_106')[
                    'baseStats'
                ][field] = value
                assert_invalid(
                    self,
                    catalog,
                    (
                        ('health', 'should not be valid under')
                        if field == 'health'
                        else invalid_field(field, value)
                    ),
                )
        for field in ('attack', 'durability'):
            catalog = load()
            del next(c for c in catalog['cards'] if c['cardId'] == 'CS2_106')[
                'baseStats'
            ][field]
            assert_invalid(self, catalog, f"'{field}' is a required property")

    def test_minions_and_spells_cannot_have_durability(self):
        for index in (0, 3):
            catalog = load()
            catalog['cards'][index]['baseStats']['durability'] = 2
            assert_invalid(self, catalog, ('durability', 'should not be valid under'))

    def test_battlecry_weapon_is_rejected(self):
        catalog = load()
        next(c for c in catalog['cards'] if c['cardId'] == 'CS2_106')['abilities'] = (
            deepcopy(catalog['cards'][2]['abilities'])
        )
        next(c for c in catalog['cards'] if c['cardId'] == 'CS2_106')['mechanics'] = [
            'BATTLECRY'
        ]
        assert_invalid(self, catalog, ('mechanics', "'DEATHRATTLE' was expected"))


class CombatTests(unittest.TestCase):
    def setUp(self):
        self.engine = Prototype(load())
        self.state = self.engine.state()

    def add(self, entity_id, card_id='CS2_182', player=0, zone='PLAY', ready=True):
        entity = self.engine.entity(entity_id, card_id, player, zone)
        entity['ready'] = ready
        self.state['entities'].append(entity)
        enter(self.engine, self.state, entity)
        return entity

    @staticmethod
    def get(state, entity_id):
        return next(e for e in state['entities'] if e['id'] == entity_id)

    @staticmethod
    def events(state, event_type):
        return [e for e in state['events'] if e['type'] == event_type]

    def equip(self, entity_id='axe', player=0):
        self.add(entity_id, 'CS2_106', player, 'HAND')
        self.state = self.engine.play(self.state, player, entity_id)

    def test_equip_pays_mana_grants_attack_and_preserves_input(self):
        self.add('axe', 'CS2_106', zone='HAND')
        before = deepcopy(self.state)
        result = self.engine.play(self.state, 0, 'axe')
        self.assertEqual(self.state, before)
        self.assertEqual(result['mana'][0], 8)
        self.assertEqual(self.engine.equipped_weapon(result, 0)['id'], 'axe')
        self.assertEqual(self.get(result, 'axe')['durability'], 2)
        self.assertEqual(
            self.engine.current_attack(result, self.get(result, 'hero-0')), 3
        )
        self.assertIn('hero-1', self.engine.attack_targets(result, 'hero-0'))

    def test_replacement_destroys_old_without_touching_opponent(self):
        self.equip('old')
        self.add('enemy-axe', 'CS2_106', player=1)
        self.add('new', 'CS2_106', zone='HAND')
        result = self.engine.play(self.state, 0, 'new')
        self.assertEqual(self.get(result, 'old')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get(result, 'old')['durability'], 2)
        self.assertEqual(self.get(result, 'enemy-axe')['zone'], 'PLAY')
        self.assertEqual(self.engine.equipped_weapon(result, 0)['id'], 'new')
        self.assertEqual(
            result['events'][-2:],
            [
                {'type': 'WEAPON_DESTROYED', 'weapon': 'old', 'reason': 'REPLACED'},
                {'type': 'EQUIP', 'weapon': 'new', 'player': 0},
            ],
        )

    def test_weapon_does_not_use_a_minion_board_slot(self):
        for i in range(7):
            self.add(f'm{i}')
        self.equip()
        self.assertEqual(self.get(self.state, 'axe')['zone'], 'PLAY')
        self.assertEqual(
            sum(
                e['kind'] == 'MINION' and e['zone'] == 'PLAY'
                for e in self.state['entities']
            ),
            7,
        )

    def test_invalid_weapon_play_preserves_previous_weapon_and_mana(self):
        self.equip('old')
        self.add('new', 'CS2_106', zone='HAND')
        self.state['mana'][0] = 1
        before = deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'mana'):
            self.engine.play(self.state, 0, 'new')
        self.assertEqual(self.state, before)
        self.state['mana'][0] = 10
        with self.assertRaisesRegex(ValueError, 'unexpected target'):
            self.engine.play(self.state, 0, 'new', 'hero-1')
        self.assertEqual(self.engine.equipped_weapon(self.state, 0)['id'], 'old')

    def test_hero_attacks_minion_and_takes_return_damage(self):
        self.equip()
        self.add('yeti', player=1)
        result = self.engine.attack(self.state, 0, 'hero-0', 'yeti')
        self.assertEqual(self.get(result, 'yeti')['damage'], 3)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 4)
        self.assertEqual(self.get(result, 'axe')['durability'], 1)
        self.assertEqual(self.get(result, 'hero-0')['attacksThisTurn'], 1)
        self.assertEqual(
            [e['damageClass'] for e in self.events(result, 'DAMAGE')],
            ['COMBAT', 'COMBAT'],
        )

    def test_minions_deal_simultaneous_damage_and_die_together(self):
        a = self.add('a')
        b = self.add('b', player=1)
        a['damage'] = b['damage'] = 1
        result = self.engine.attack(self.state, 0, 'a', 'b')
        self.assertEqual(self.get(result, 'a')['damage'], 5)
        self.assertEqual(self.get(result, 'b')['damage'], 5)
        self.assertEqual(
            self.events(result, 'DEATH_BATCH'),
            [{'type': 'DEATH_BATCH', 'targets': ['a', 'b']}],
        )
        self.assertEqual(
            [e['type'] for e in result['events']],
            ['ATTACK', 'DAMAGE', 'DAMAGE', 'DEATH_BATCH'],
        )

    def test_lethally_hit_defender_still_retaliates(self):
        self.add('attacker')
        self.add('defender', 'EX1_015', player=1)
        result = self.engine.attack(self.state, 0, 'attacker', 'defender')
        self.assertEqual(self.get(result, 'defender')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get(result, 'attacker')['damage'], 1)

    def test_enemy_hero_does_not_retaliate_with_weapon_or_attack_buff(self):
        self.add('enemy-axe', 'CS2_106', player=1)
        self.get(self.state, 'hero-1')['attack'] = 8
        self.add('attacker')
        result = self.engine.attack(self.state, 0, 'attacker', 'hero-1')
        self.assertEqual(self.get(result, 'attacker')['damage'], 0)
        self.assertEqual(self.get(result, 'hero-1')['damage'], 4)
        self.assertEqual(self.get(result, 'enemy-axe')['durability'], 2)
        self.assertEqual(len(self.events(result, 'DAMAGE')), 1)

    def test_second_attack_is_rejected_for_hero_and_minion(self):
        self.equip()
        self.add('minion')
        for attacker in ('hero-0', 'minion'):
            with self.subTest(attacker=attacker):
                result = self.engine.attack(self.state, 0, attacker, 'hero-1')
                before = deepcopy(result)
                self.assertEqual(self.engine.attack_targets(result, attacker), [])
                with self.assertRaises(ValueError):
                    self.engine.attack(result, 0, attacker, 'hero-1')
                self.assertEqual(result, before)

    def test_replacement_does_not_reset_hero_attack_count(self):
        self.equip('old')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.equip('new')
        self.assertEqual(self.get(self.state, 'hero-0')['attacksThisTurn'], 1)
        with self.assertRaises(ValueError):
            self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get(self.state, 'new')['durability'], 2)

    def test_replacement_before_attack_still_allows_one_attack(self):
        self.equip('old')
        self.equip('new')
        result = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get(result, 'new')['durability'], 1)
        self.assertEqual(self.get(result, 'old')['zone'], 'GRAVEYARD')

    def test_final_durability_breaks_weapon_and_removes_hero_attack(self):
        self.equip()
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.state = self.engine.begin_combat_turn(self.state, 1)
        self.state = self.engine.begin_combat_turn(self.state, 0)
        result = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get(result, 'axe')['durability'], 0)
        self.assertEqual(self.get(result, 'axe')['zone'], 'GRAVEYARD')
        self.assertIsNone(self.engine.equipped_weapon(result, 0))
        self.assertEqual(
            self.engine.current_attack(result, self.get(result, 'hero-0')), 0
        )
        self.assertEqual(
            self.events(result, 'WEAPON_DESTROYED')[-1]['reason'], 'EXHAUSTED'
        )
        self.assertEqual(
            self.engine.cards[('CS2_106', 'foundation-v3')]['baseStats']['durability'],
            2,
        )

    def test_minion_attacking_never_spends_friendly_weapon_durability(self):
        self.equip()
        self.add('minion')
        result = self.engine.attack(self.state, 0, 'minion', 'hero-1')
        self.assertEqual(self.get(result, 'axe')['durability'], 2)
        self.assertEqual(self.events(result, 'DURABILITY'), [])

    def test_weapon_attack_is_sheathed_on_opponents_turn(self):
        self.equip()
        result = self.engine.begin_combat_turn(self.state, 1)
        self.assertEqual(
            self.engine.current_attack(result, self.get(result, 'hero-0')), 0
        )
        self.assertEqual(self.engine.attack_targets(result, 'hero-0'), [])
        result = self.engine.begin_combat_turn(result, 0)
        self.assertEqual(
            self.engine.current_attack(result, self.get(result, 'hero-0')), 3
        )

    def test_taunt_restricts_hero_and_minion_attacks(self):
        self.equip()
        self.add('attacker')
        self.add('taunt', 'CS2_179', player=1)
        self.add('other', player=1)
        for attacker in ('hero-0', 'attacker'):
            self.assertEqual(
                self.engine.attack_targets(self.state, attacker), ['taunt']
            )
            with self.assertRaises(ValueError):
                self.engine.attack(self.state, 0, attacker, 'other')

    def test_stealthed_or_immune_taunt_does_not_protect_other_targets(self):
        self.equip()
        taunt = self.add('taunt', 'CS2_179', player=1)
        for keyword in ('STEALTH', 'IMMUNE'):
            taunt['keywords'] = ['TAUNT', keyword]
            self.assertEqual(
                self.engine.attack_targets(self.state, 'hero-0'), ['hero-1']
            )
            with self.assertRaises(ValueError):
                self.engine.attack(self.state, 0, 'hero-0', 'taunt')

    def test_divine_shield_prevents_hit_but_still_consumes_attack_and_durability(self):
        self.equip()
        self.add('shielded', player=1)['keywords'] = ['DIVINE_SHIELD']
        result = self.engine.attack(self.state, 0, 'hero-0', 'shielded')
        self.assertEqual(self.get(result, 'shielded')['damage'], 0)
        self.assertNotIn('DIVINE_SHIELD', self.get(result, 'shielded')['keywords'])
        self.assertEqual(self.get(result, 'hero-0')['damage'], 4)
        self.assertEqual(self.get(result, 'axe')['durability'], 1)
        self.assertEqual(self.engine.attack_targets(result, 'hero-0'), [])

    def test_immune_attacking_hero_still_spends_weapon_durability(self):
        self.equip()
        self.get(self.state, 'hero-0')['keywords'] = ['IMMUNE']
        self.add('defender', player=1)
        result = self.engine.attack(self.state, 0, 'hero-0', 'defender')
        self.assertEqual(self.get(result, 'hero-0')['damage'], 0)
        self.assertEqual(self.get(result, 'axe')['durability'], 1)

    def test_combat_damage_uses_armor_not_spell_bonus(self):
        self.equip()
        spell_bonus(self.engine, self.state, 0, 3)
        self.get(self.state, 'hero-1')['armor'] = 2
        result = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get(result, 'hero-1')['armor'], 0)
        self.assertEqual(self.get(result, 'hero-1')['damage'], 1)

    def test_exhausted_frozen_and_cannot_attack_are_rejected(self):
        self.equip()
        self.add('minion', ready=False)
        with self.assertRaises(ValueError):
            self.engine.attack(self.state, 0, 'minion', 'hero-1')
        for keyword in ('FROZEN', 'CANT_ATTACK'):
            self.get(self.state, 'hero-0')['keywords'] = [keyword]
            before = deepcopy(self.state)
            with self.assertRaises(ValueError):
                self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
            self.assertEqual(self.state, before)

    def test_zero_attack_and_non_character_attackers_are_rejected(self):
        self.add('spell', 'CS2_029')
        self.add('axe', 'CS2_106')
        self.get(self.state, 'axe')['zone'] = 'HAND'
        for attacker in ('hero-0', 'spell', 'axe'):
            with self.assertRaises(ValueError):
                self.engine.attack(self.state, 0, attacker, 'hero-1')

    def test_invalid_defenders_players_and_zones_are_atomic(self):
        self.equip()
        self.add('friendly')
        self.add('hand-minion', player=1, zone='HAND')
        self.add('enemy-weapon', 'CS2_106', player=1)
        before = deepcopy(self.state)
        for defender in (
            'hero-0',
            'friendly',
            'axe',
            'hand-minion',
            'enemy-weapon',
            'unknown',
        ):
            with self.subTest(defender=defender), self.assertRaises(ValueError):
                self.engine.attack(self.state, 0, 'hero-0', defender)
            self.assertEqual(self.state, before)
        for player in (-1, 1, 2, True):
            with self.assertRaises(ValueError):
                self.engine.attack(self.state, player, 'hero-0', 'hero-1')
        with self.assertRaises(ValueError):
            self.engine.attack(self.state, 0, 'unknown', 'hero-1')

    def test_combat_turn_refreshes_only_incoming_players_characters(self):
        a = self.add('a', ready=False)
        b = self.add('b', player=1, ready=False)
        a['attacksThisTurn'] = b['attacksThisTurn'] = 1
        result = self.engine.begin_combat_turn(self.state, 0)
        self.assertEqual(self.get(result, 'a')['attacksThisTurn'], 0)
        self.assertTrue(self.get(result, 'a')['ready'])
        self.assertEqual(self.get(result, 'b')['attacksThisTurn'], 1)
        self.assertFalse(self.get(result, 'b')['ready'])
        self.assertEqual(result['mana'], self.state['mana'])
        self.assertEqual(result['fatigue'], self.state['fatigue'])
        self.assertEqual(result['decks'], self.state['decks'])

    def test_attacking_breaks_stealth(self):
        self.add('attacker')['keywords'] = ['STEALTH']
        result = self.engine.attack(self.state, 0, 'attacker', 'hero-1')
        self.assertNotIn('STEALTH', self.get(result, 'attacker')['keywords'])

    def test_weaponless_hero_with_fixture_attack_can_attack(self):
        self.get(self.state, 'hero-0')['attack'] = 2
        result = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get(result, 'hero-1')['damage'], 2)
        self.assertEqual(self.events(result, 'DURABILITY'), [])

    def test_zero_attack_defender_deals_no_return_damage(self):
        catalog = load()
        catalog['cards'][0]['baseStats']['attack'] = 0
        engine = Prototype(catalog)
        self.add('attacker', 'CS2_179')
        self.add('zero', player=1)
        result = engine.attack(self.state, 0, 'attacker', 'zero')
        self.assertEqual(self.get(result, 'attacker')['damage'], 0)
        self.assertEqual(len(self.events(result, 'DAMAGE')), 1)

    def test_hero_can_die_to_retaliation_while_killing_defender(self):
        self.equip()
        self.get(self.state, 'hero-0')['damage'] = 29
        self.add('small', 'EX1_015', player=1)
        result = self.engine.attack(self.state, 0, 'hero-0', 'small')
        self.assertEqual(result['result'], 'PLAYER_1_WINS')
        self.assertEqual(self.get(result, 'small')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get(result, 'axe')['durability'], 1)

    def test_lethal_combat_finishes_and_blocks_all_actions(self):
        self.equip()
        self.get(self.state, 'hero-1')['damage'] = 27
        result = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(result['result'], 'PLAYER_0_WINS')
        with self.assertRaises(ValueError):
            self.engine.attack(result, 0, 'hero-0', 'hero-1')
        with self.assertRaises(ValueError):
            self.engine.begin_combat_turn(result, 1)
        with self.assertRaises(ValueError):
            self.engine.draw(result, 0)
        with self.assertRaises(ValueError):
            self.engine.play(result, 0, 'axe')

    def test_ambiguous_or_broken_equipped_weapon_is_rejected(self):
        self.equip()
        self.get(self.state, 'axe')['durability'] = 0
        before = deepcopy(self.state)
        with self.assertRaises(ValueError):
            self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.state, before)
        self.get(self.state, 'axe')['durability'] = 2
        self.add('other', 'CS2_106')
        with self.assertRaises(ValueError):
            self.engine.attack(self.state, 0, 'hero-0', 'hero-1')

    def test_combat_is_deterministic_serializable_and_input_immutable(self):
        self.equip()
        self.add('defender', player=1)
        before = deepcopy(self.state)
        result = self.engine.attack(self.state, 0, 'hero-0', 'defender')
        self.assertEqual(self.state, before)
        self.assertEqual(
            result, self.engine.attack(self.state, 0, 'hero-0', 'defender')
        )
        self.assertEqual(result, json.loads(json.dumps(result)))


if __name__ == '__main__':
    unittest.main()
