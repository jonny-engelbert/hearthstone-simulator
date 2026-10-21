from fixtures import assert_invalid, invalid_field
from fixtures import spell_bonus
from fixtures import enter
from copy import deepcopy
import json
import unittest

from jsonschema import Draft202012Validator
from hearthstone.catalog import ROOT, SCHEMAS, load, validate
from hearthstone.prototype import Prototype


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load()

    def test_schema_itself_is_valid(self):
        for filename in SCHEMAS.values():
            Draft202012Validator.check_schema(
                json.loads((ROOT / 'schemas' / filename).read_text())
            )

    def test_identifiers_match_reviewed_reference(self):
        expected = {
            'Chillwind Yeti': 'CS2_182',
            "Sen'jin Shieldmasta": 'CS2_179',
            'Fire Elemental': 'CS2_042',
            'Polymorph': 'CS2_022',
            'Sheep': 'CS2_tk1',
            'Flamestrike': 'CS2_032',
            'Fireball': 'CS2_029',
            'Novice Engineer': 'EX1_015',
            'Fiery War Axe': 'CS2_106',
            'Loot Hoarder': 'EX1_096',
            'Voodoo Doctor': 'EX1_011',
            'Blessing of Kings': 'CS2_092',
            'Stormwind Champion': 'CS2_222',
            'Spellbreaker': 'EX1_048',
            'The Coin': 'GAME_005',
            'Lightning Bolt': 'EX1_238',
            'Fireblast': 'CS2_034',
            'Lesser Heal': 'CS1h_001',
            'Wolfrider': 'CS2_124',
            'Rabid Worgen': 'GIL_113',
            'Windfury Harpy': 'EX1_033',
            'Frostbolt': 'CS2_024',
            'Abusive Sergeant': 'CS2_188',
        }
        new = {
            ('Murloc Tidehunter', 'EX1_506'),
            ('Murloc Scout', 'EX1_506a'),
            ('Mirror Image', 'CS2_027'),
            ('Mirror Image', 'CS2_mirror'),
            ('Haunted Creeper', 'FP1_002'),
            ('Spectral Spider', 'FP1_002t'),
            ('Youthful Brewmaster', 'EX1_049'),
            ('Sap', 'EX1_581'),
            ('King Mukla', 'EX1_014'),
            ('Bananas', 'EX1_014t'),
            ('Gang Up', 'BRM_007'),
            ('Recycle', 'GVG_031'),
            ('Reinforce', 'CS2_101'),
            ('Silver Hand Recruit', 'CS2_101t'),
        }
        new |= {
            ('Arcane Missiles', 'EX1_277'),
            ('Mad Bomber', 'EX1_082'),
            ('Deadly Shot', 'EX1_617'),
            ('Babbling Book', 'KAR_009'),
            ('Stonehill Defender', 'UNG_072'),
            ('Ironfur Grizzly', 'CS2_125'),
            ('Goldshire Footman', 'CS1_042'),
            ('Wrath', 'EX1_154'),
            ('Kobold Geomancer', 'CS2_142'),
            ('Acolyte of Pain', 'EX1_007'),
            ('Northshire Cleric', 'CS2_235'),
            ('Cult Master', 'EX1_595'),
            ('Wild Pyromancer', 'NEW1_020'),
            ('Questing Adventurer', 'EX1_044'),
            ('Darkshire Councilman', 'OG_113'),
            ('Counterspell', 'EX1_287'),
            ('Vaporize', 'EX1_594'),
            ('Explosive Trap', 'EX1_610'),
            ('Noble Sacrifice', 'EX1_130'),
            ('Defender', 'EX1_130a'),
            ('Truesilver Champion', 'CS2_097'),
            ("Death's Bite", 'FP1_021'),
            ('Eye for an Eye', 'EX1_132'),
        }
        self.assertEqual(
            {(c['name'], c['cardId']) for c in self.catalog['cards']},
            set(expected.items()) | new,
        )

    def test_duplicate_definition_is_rejected(self):
        self.catalog['cards'].append(deepcopy(self.catalog['cards'][0]))
        self.assertTrue(any('duplicate' in e for e in validate(self.catalog)))

    def test_unknown_fields_and_operations_are_rejected(self):
        for mutation in ('extra', 'op', 'version', 'policy'):
            with self.subTest(mutation=mutation):
                catalog = deepcopy(self.catalog)
                card = catalog['cards'][2]
                if mutation == 'extra':
                    card['madeUp'] = True
                if mutation == 'op':
                    card['abilities'][0]['effects'][0]['op'] = 'UNKNOWN_OP'
                if mutation == 'version':
                    card['schemaVersion'] = '99'
                if mutation == 'policy':
                    card['abilities'][0]['targeting']['legalityPolicy'] = 'UNKNOWN'
                assert_invalid(
                    self,
                    catalog,
                    {
                        'extra': ('madeUp', 'Additional properties'),
                        'op': 'UNKNOWN_OP',
                        'version': ("'schemaVersion'", "'1.12' was expected"),
                        'policy': ("'legalityPolicy'", "'UNKNOWN' is not one of"),
                    }[mutation],
                )

    def test_invalid_stat_shapes_are_rejected(self):
        for index, key, value in [
            (0, 'health', 0),
            (0, 'manaCost', -1),
            (3, 'attack', 1),
        ]:
            with self.subTest(index=index, key=key):
                catalog = deepcopy(self.catalog)
                catalog['cards'][index]['baseStats'][key] = value
                assert_invalid(
                    self,
                    catalog,
                    (
                        (key, 'should not be valid under')
                        if key == 'attack'
                        else invalid_field(key, value)
                    ),
                )
        del self.catalog['cards'][0]['baseStats']['health']
        assert_invalid(self, self.catalog, "'health' is a required property")

    def test_unresolved_revision_and_token_are_rejected(self):
        for field in ('cardId', 'revision'):
            catalog = deepcopy(self.catalog)
            catalog['cards'][3]['abilities'][0]['effects'][0]['targetDefinition'][
                field
            ] = 'UNKNOWN'
            self.assertTrue(any('unresolved' in e for e in validate(catalog)))

    def test_unbound_target_is_rejected(self):
        self.catalog['cards'][2]['abilities'][0]['effects'][0]['recipient'][
            'name'
        ] = 'other'
        self.assertTrue(any('unbound' in e for e in validate(self.catalog)))

    def test_wrong_ability_and_damage_class_are_rejected(self):
        ability = self.catalog['cards'][2]['abilities'][0]
        ability['effects'][0]['damageClass'] = 'SPELL'
        self.assertTrue(any('damage class' in e for e in validate(self.catalog)))
        ability['kind'] = 'SPELL_EFFECT'
        self.assertTrue(any('ability kind' in e for e in validate(self.catalog)))

    def test_batch_shape_must_match_recipient(self):
        self.catalog['cards'][5]['abilities'][0]['effects'][0][
            'application'
        ] = 'SINGLE_HIT'
        self.assertTrue(
            any('application disagree' in e for e in validate(self.catalog))
        )

    def test_transform_cannot_reference_spell(self):
        self.catalog['cards'][3]['abilities'][0]['effects'][0]['targetDefinition'][
            'cardId'
        ] = 'CS2_029'
        self.assertTrue(any('must be a minion' in e for e in validate(self.catalog)))


class BehaviorTests(unittest.TestCase):
    def setUp(self):
        self.engine = Prototype(load())
        self.state = self.engine.state()

    def add(self, card_id, entity_id, controller=0, zone='PLAY'):
        entity = self.engine.entity(entity_id, card_id, controller, zone)
        self.state['entities'].append(entity)
        enter(self.engine, self.state, entity)
        return entity

    def get(self, state, entity_id):
        return next(e for e in state['entities'] if e['id'] == entity_id)

    def test_yeti_play_pays_mana_and_starts_exhausted(self):
        self.add('CS2_182', 'yeti', zone='HAND')
        result = self.engine.play(self.state, 0, 'yeti')
        self.assertEqual(result['mana'][0], 6)
        self.assertEqual(self.get(result, 'yeti')['zone'], 'PLAY')
        self.assertFalse(self.get(result, 'yeti')['ready'])
        self.assertEqual(self.get(self.state, 'yeti')['zone'], 'HAND')

    def test_definitions_and_other_copies_are_unchanged(self):
        a = self.add('CS2_179', 'a')
        b = self.add('CS2_179', 'b')
        a['keywords'].clear()
        self.assertEqual(b['keywords'], ['TAUNT'])
        self.assertEqual(self.engine.definition(a)['keywords'], ['TAUNT'])

    def test_illegal_actions_are_atomic(self):
        self.add('CS2_022', 'poly', zone='HAND')
        before = deepcopy(self.state)
        for target in (None, 'hero-1', 'unknown'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.engine.play(self.state, 0, 'poly', target)
            self.assertEqual(self.state, before)

    def test_insufficient_mana_full_board_and_wrong_turn(self):
        self.add('CS2_182', 'source', zone='HAND')
        self.state['mana'][0] = 3
        with self.assertRaisesRegex(ValueError, 'mana'):
            self.engine.play(self.state, 0, 'source')
        self.state['mana'][0] = 10
        for i in range(7):
            self.add('CS2_182', f'm{i}')
        with self.assertRaisesRegex(ValueError, 'full'):
            self.engine.play(self.state, 0, 'source')
        with self.assertRaisesRegex(ValueError, 'decision'):
            self.engine.play(self.state, 1, 'source')

    def test_fire_elemental_requires_target_when_available(self):
        self.add('CS2_042', 'fire', zone='HAND')
        with self.assertRaisesRegex(ValueError, 'required'):
            self.engine.play(self.state, 0, 'fire')
        result = self.engine.play(self.state, 0, 'fire', 'hero-1')
        self.assertEqual(self.get(result, 'hero-1')['damage'], 3)

    def test_battlecry_no_target_branch_and_self_exclusion(self):
        self.add('CS2_042', 'fire', zone='HAND')
        self.get(self.state, 'hero-1')['keywords'] = ['IMMUNE']
        # A friendly hero is still a legal target; hide it from this synthetic
        # fixture to exercise REQUIRED_IF_AVAILABLE with zero candidates.
        self.get(self.state, 'hero-0')['zone'] = 'SET_ASIDE'
        result = self.engine.play(self.state, 0, 'fire')
        self.assertEqual(self.get(result, 'fire')['zone'], 'PLAY')
        self.assertFalse(any(e['type'] == 'DAMAGE' for e in result['events']))
        with self.assertRaisesRegex(ValueError, 'illegal'):
            self.engine.play(self.state, 0, 'fire', 'fire')

    def test_optional_target_can_be_declined(self):
        catalog = load()
        catalog['cards'][2]['abilities'][0]['targeting']['mode'] = 'OPTIONAL'
        engine = Prototype(catalog)
        self.add('CS2_042', 'fire', zone='HAND')
        result = engine.play(self.state, 0, 'fire')
        self.assertEqual(self.get(result, 'hero-1')['damage'], 0)

    def test_spell_bonus_does_not_modify_battlecry(self):
        self.add('CS2_042', 'fire', zone='HAND')
        spell_bonus(self.engine, self.state, 0, 2)
        result = self.engine.play(self.state, 0, 'fire', 'hero-1')
        self.assertEqual(self.get(result, 'hero-1')['damage'], 3)

    def test_battlecry_still_obeys_divine_shield(self):
        self.add('CS2_042', 'fire', zone='HAND')
        target = self.add('CS2_182', 'target', 1)
        target['keywords'].append('DIVINE_SHIELD')
        result = self.engine.play(self.state, 0, 'fire', 'target')
        self.assertEqual(self.get(result, 'target')['damage'], 0)
        self.assertNotIn('DIVINE_SHIELD', self.get(result, 'target')['keywords'])

    def test_fireball_bonus_armor_and_graveyard(self):
        self.add('CS2_029', 'spell', zone='HAND')
        spell_bonus(self.engine, self.state, 0, 1)
        self.get(self.state, 'hero-1')['armor'] = 3
        result = self.engine.play(self.state, 0, 'spell', 'hero-1')
        self.assertEqual(self.get(result, 'hero-1')['damage'], 4)
        self.assertEqual(self.get(result, 'hero-1')['armor'], 0)
        self.assertEqual(self.get(result, 'spell')['zone'], 'GRAVEYARD')

    def test_flamestrike_batch_and_spell_damage_per_recipient(self):
        self.add('CS2_032', 'spell', zone='HAND')
        self.add('CS2_182', 'a', 1)
        self.add('CS2_182', 'b', 1)
        self.add('CS2_182', 'friendly')
        spell_bonus(self.engine, self.state, 0, 1)
        result = self.engine.play(self.state, 0, 'spell')
        damage = [e for e in result['events'] if e['type'] == 'DAMAGE']
        self.assertEqual(
            [(e['target'], e['amount']) for e in damage], [('a', 5), ('b', 5)]
        )
        self.assertEqual(
            result['events'][-1], {'type': 'DEATH_BATCH', 'targets': ['a', 'b']}
        )
        self.assertEqual(self.get(result, 'friendly')['damage'], 0)
        self.assertEqual(self.get(result, 'hero-1')['damage'], 0)

    def test_area_effect_ignores_selection_restrictions_but_not_immunity(self):
        self.add('CS2_032', 'spell', zone='HAND')
        for entity_id, keyword in [
            ('hidden', 'STEALTH'),
            ('elusive', 'ELUSIVE'),
            ('immune', 'IMMUNE'),
        ]:
            self.add('CS2_182', entity_id, 1)['keywords'].append(keyword)
        result = self.engine.play(self.state, 0, 'spell')
        self.assertEqual(
            [self.get(result, e)['damage'] for e in ('hidden', 'elusive', 'immune')],
            [4, 4, 0],
        )

    def test_spell_and_battlecry_target_legality_differ(self):
        self.add('CS2_029', 'spell', zone='HAND')
        self.add('CS2_042', 'fire', zone='HAND')
        target = self.add('CS2_182', 'target', 1)
        target['keywords'] = ['ELUSIVE']
        with self.assertRaisesRegex(ValueError, 'illegal'):
            self.engine.play(self.state, 0, 'spell', 'target')
        result = self.engine.play(self.state, 0, 'fire', 'target')
        self.assertEqual(self.get(result, 'target')['damage'], 3)
        target['keywords'] = ['STEALTH']
        with self.assertRaisesRegex(ValueError, 'illegal'):
            self.engine.play(self.state, 0, 'fire', 'target')

    def test_polymorph_resets_damage_and_buffs_preserving_controller(self):
        self.add('CS2_022', 'spell', zone='HAND')
        target = self.add('CS2_179', 'target', 1)
        target.update(damage=3, enchantments=['test-buff'], ready=True)
        target['owner'] = 0
        result = self.engine.play(self.state, 0, 'spell', 'target')
        sheep = self.get(result, 'target')
        self.assertEqual(
            (sheep['cardId'], sheep['damage'], sheep['controller'], sheep['owner']),
            ('CS2_tk1', 0, 1, 0),
        )
        self.assertEqual(sheep['keywords'], [])
        self.assertEqual(sheep['enchantments'], [])
        self.assertFalse(
            any(e['type'] in ('DEATH_BATCH', 'SUMMON') for e in result['events'])
        )

    def test_taunt_limits_attacks_but_not_fireball(self):
        self.add('CS2_182', 'attacker')['ready'] = True
        taunt = self.add('CS2_179', 'taunt', 1)
        self.assertEqual(self.engine.attack_targets(self.state, 'attacker'), ['taunt'])
        self.add('CS2_029', 'spell', zone='HAND')
        result = self.engine.play(self.state, 0, 'spell', 'hero-1')
        self.assertEqual(self.get(result, 'hero-1')['damage'], 6)
        taunt['keywords'].append('STEALTH')
        self.assertEqual(self.engine.attack_targets(self.state, 'attacker'), ['hero-1'])

    def test_empty_area_spell_is_playable(self):
        self.add('CS2_032', 'spell', zone='HAND')
        result = self.engine.play(self.state, 0, 'spell')
        self.assertEqual(result['mana'][0], 3)
        self.assertEqual(len(result['events']), 1)

    def test_identical_inputs_produce_identical_outputs(self):
        self.add('CS2_029', 'spell', zone='HAND')
        self.assertEqual(
            self.engine.play(self.state, 0, 'spell', 'hero-1'),
            self.engine.play(self.state, 0, 'spell', 'hero-1'),
        )

    def test_lethal_hero_damage_ends_fixture(self):
        self.add('CS2_029', 'spell', zone='HAND')
        self.get(self.state, 'hero-1')['damage'] = 24
        result = self.engine.play(self.state, 0, 'spell', 'hero-1')
        self.assertEqual(result['result'], 'PLAYER_0_WINS')
        with self.assertRaisesRegex(ValueError, 'decision'):
            self.engine.play(result, 0, 'spell', 'hero-1')


if __name__ == '__main__':
    unittest.main()
