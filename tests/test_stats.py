"""Stage 5: additive stat layers, healing, flat auras and silence cleanup."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.prototype import Prototype


def definition(catalog, card_id):
    return next(c for c in catalog['cards'] if c['cardId'] == card_id)


class StatCatalogTests(unittest.TestCase):
    def test_all_five_catalogs_and_manifests(self):
        for v, count in ((1, 7), (2, 8), (3, 9), (4, 10), (5, 14)):
            self.assertEqual(len(load(ROOT / f'cards/foundation-v{v}.json')['cards']), count)
            name = 'manifest.json' if v == 1 else f'manifest-v{v}.json'
            self.assertEqual(verify(json.loads((ROOT / 'cards' / name).read_text())), [])

    def test_representative_historical_stats(self):
        expected = {'EX1_011': {'manaCost': 1, 'attack': 2, 'health': 1},
                    'CS2_092': {'manaCost': 4},
                    'CS2_222': {'manaCost': 7, 'attack': 6, 'health': 6},
                    'EX1_048': {'manaCost': 4, 'attack': 4, 'health': 3}}
        for card_id, stats in expected.items():
            self.assertEqual(definition(load(), card_id)['baseStats'], stats)

    def test_previous_schema_rejects_new_abilities(self):
        catalog = load(ROOT / 'cards/foundation-v4.json')
        champ = deepcopy(definition(load(), 'CS2_222'))
        champ['schemaVersion'] = '1.4'
        catalog['cards'].append(champ)
        self.assertTrue(validate(catalog))

    def test_malformed_buff_amounts_and_duration_are_rejected(self):
        for key, value in [('attack', -1), ('health', True), ('health', 0.5)]:
            catalog = load()
            effect = definition(catalog, 'CS2_092')['abilities'][0]['effects'][0]
            effect['modifiers'][key] = value
            self.assertTrue(validate(catalog))
        catalog = load(ROOT / 'cards/foundation-v5.json')
        definition(catalog, 'CS2_092')['abilities'][0]['effects'][0]['duration'] = 'END_OF_TURN'
        self.assertTrue(validate(catalog))

    def test_zero_buffs_and_auras_are_rejected(self):
        for card_id in ('CS2_092', 'CS2_222'):
            catalog = load()
            ability = definition(catalog, card_id)['abilities'][0]
            node = ability if card_id == 'CS2_222' else ability['effects'][0]
            node['modifiers'] = {'attack': 0, 'health': 0}
            self.assertTrue(validate(catalog))

    def test_buff_and_silence_cannot_target_heroes(self):
        for card_id in ('CS2_092', 'EX1_048'):
            catalog = load()
            definition(catalog, card_id)['abilities'][0]['targeting']['selector']['entityKind'] = 'CHARACTER'
            self.assertTrue(validate(catalog))

    def test_aura_shape_and_mechanic_label_are_strict(self):
        for mutation in ('enemy', 'characters', 'label', 'duration'):
            catalog = load()
            champ = definition(catalog, 'CS2_222')
            aura = champ['abilities'][0]
            if mutation == 'enemy': aura['selector']['controller'] = 'OPPONENT_OF_EFFECT_CONTROLLER'
            if mutation == 'characters': aura['selector']['entityKind'] = 'CHARACTER'
            if mutation == 'label': champ['mechanics'] = []
            if mutation == 'duration': aura['duration'] = 'PERMANENT'
            self.assertTrue(validate(catalog))

    def test_heal_and_policy_are_strict(self):
        for value in (-1, True, 1.5):
            catalog = load()
            definition(catalog, 'EX1_011')['abilities'][0]['effects'][0]['amount']['value'] = value
            self.assertTrue(validate(catalog))
        catalog = load()
        catalog['healthModifierPolicy'] = 'UNKNOWN'
        self.assertTrue(validate(catalog))


class HealingBuffAuraTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load()
        self.engine = Prototype(self.catalog)
        self.state = self.engine.state()

    def add(self, entity_id, card_id='CS2_182', player=0, zone='PLAY'):
        entity = self.engine.entity(entity_id, card_id, player, zone)
        self.state['entities'].append(entity)
        return entity

    @staticmethod
    def get(state, entity_id):
        return next(e for e in state['entities'] if e['id'] == entity_id)

    def play(self, card_id, target=None, entity_id='spell'):
        self.add(entity_id, card_id, zone='HAND')
        self.state = self.engine.play(self.state, 0, entity_id, target)
        return self.state

    def stats(self, entity_id, state=None):
        state = state or self.state
        entity = self.get(state, entity_id)
        return (self.engine.current_attack(state, entity), self.engine.max_health(entity, state),
                self.engine.current_health(state, entity))

    @staticmethod
    def events(state, kind):
        return [e for e in state['events'] if e['type'] == kind]

    def test_doctor_heals_hero_without_touching_armor_or_spell_bonus(self):
        self.get(self.state, 'hero-0').update(damage=5, armor=7)
        self.state['spellDamage'][0] = 50
        result = self.play('EX1_011', 'hero-0')
        self.assertEqual(self.get(result, 'hero-0')['damage'], 3)
        self.assertEqual(self.get(result, 'hero-0')['armor'], 7)
        self.assertEqual(self.events(result, 'HEAL'), [{'type': 'HEAL', 'source': 'spell', 'target': 'hero-0', 'amount': 2}])

    def test_heal_is_capped_and_full_health_target_is_legal(self):
        self.get(self.state, 'hero-0')['damage'] = 1
        self.play('EX1_011', 'hero-0', 'doctor1')
        self.assertEqual(self.events(self.state, 'HEAL')[-1]['amount'], 1)
        self.play('EX1_011', 'hero-0', 'doctor2')
        self.assertEqual(self.events(self.state, 'HEAL')[-1]['amount'], 0)
        self.assertEqual(self.get(self.state, 'hero-0')['damage'], 0)

    def test_doctor_heals_enemy_minion(self):
        self.add('enemy', player=1)['damage'] = 3
        self.play('EX1_011', 'enemy')
        self.assertEqual(self.get(self.state, 'enemy')['damage'], 1)

    def test_healing_does_not_consume_divine_shield(self):
        target = self.add('target')
        target.update(damage=2, keywords=['DIVINE_SHIELD', 'IMMUNE'])
        self.play('EX1_011', 'target')
        self.assertEqual(self.get(self.state, 'target')['damage'], 0)
        self.assertEqual(self.get(self.state, 'target')['keywords'], ['DIVINE_SHIELD', 'IMMUNE'])

    def test_doctor_requires_target_and_cannot_target_self(self):
        self.add('doctor', 'EX1_011', zone='HAND')
        before = deepcopy(self.state)
        for target in (None, 'doctor'):
            with self.assertRaises(ValueError): self.engine.play(self.state, 0, 'doctor', target)
            self.assertEqual(self.state, before)

    def test_spell_healing_uses_same_primitive_without_spell_bonus(self):
        spell = definition(self.catalog, 'CS2_029')
        spell['abilities'][0]['effects'] = deepcopy(definition(self.catalog, 'EX1_011')['abilities'][0]['effects'])
        self.engine = Prototype(self.catalog)
        self.get(self.state, 'hero-0')['damage'] = 4
        self.state['spellDamage'][0] = 50
        self.play('CS2_029', 'hero-0')
        self.assertEqual(self.get(self.state, 'hero-0')['damage'], 2)

    def test_deathrattle_heal_can_save_hero_before_final_result(self):
        effect = deepcopy(definition(self.catalog, 'EX1_011')['abilities'][0]['effects'][0])
        effect['recipient'] = {'kind': 'QUERY', 'capture': 'EFFECT_START',
                               'selector': {'zone': 'PLAY', 'entityKind': 'CHARACTER', 'controller': 'FRIENDLY'}}
        definition(self.catalog, 'EX1_096')['abilities'][0]['effects'] = [effect]
        self.engine = Prototype(self.catalog)
        self.add('loot', 'EX1_096')['damage'] = 1
        self.get(self.state, 'hero-0')['damage'] = 30
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.get(result, 'hero-0')['damage'], 28)
        self.assertIsNone(result['result'])

    def test_same_ability_heal_can_save_mortally_wounded_minion(self):
        ability = definition(self.catalog, 'CS2_042')['abilities'][0]
        ability['effects'].extend(deepcopy(definition(self.catalog, 'EX1_011')['abilities'][0]['effects']))
        self.engine = Prototype(self.catalog)
        self.add('yeti')['damage'] = 3  # Current 2; damage 3 then heal 2 => current 1.
        result = self.play('CS2_042', 'yeti')
        self.assertEqual(self.stats('yeti'), (4, 5, 1))
        self.assertEqual(self.get(result, 'yeti')['zone'], 'PLAY')
        self.assertEqual(self.events(result, 'DEATH_BATCH'), [])

    def test_healing_does_not_cancel_pending_destroy(self):
        ability = definition(self.catalog, 'CS2_042')['abilities'][0]
        ability['targeting']['selector']['entityKind'] = 'MINION'
        heal = deepcopy(definition(self.catalog, 'EX1_011')['abilities'][0]['effects'][0])
        ability['effects'] = [{'op': 'DESTROY', 'recipient': deepcopy(heal['recipient']),
                               'missingRecipient': 'SKIP'}, heal]
        self.engine = Prototype(self.catalog)
        self.add('yeti')['damage'] = 2
        result = self.play('CS2_042', 'yeti')
        self.assertEqual(self.get(result, 'yeti')['damage'], 0)
        self.assertEqual(self.get(result, 'yeti')['zone'], 'GRAVEYARD')

    def test_kings_increases_max_and_current_health_retaining_damage(self):
        self.add('yeti')['damage'] = 3
        self.play('CS2_092', 'yeti')
        self.assertEqual(self.stats('yeti'), (8, 9, 6))
        self.assertEqual(self.get(self.state, 'yeti')['damage'], 3)
        self.assertEqual(self.engine.cards[('CS2_182', 'foundation-v1')]['baseStats']['health'], 5)

    def test_two_permanent_buffs_stack_and_survive_spell_graveyard(self):
        self.add('yeti')
        self.play('CS2_092', 'yeti', 'kings1')
        self.play('CS2_092', 'yeti', 'kings2')
        self.assertEqual(self.stats('yeti'), (12, 13, 13))
        self.assertEqual(self.get(self.state, 'kings1')['zone'], 'GRAVEYARD')
        self.assertEqual(len(self.get(self.state, 'yeti')['enchantments']), 2)

    def test_buff_does_not_refresh_attack_count_or_exhaustion(self):
        self.add('yeti').update(ready=False, attacksThisTurn=1)
        self.play('CS2_092', 'yeti')
        self.assertEqual(self.engine.attack_targets(self.state, 'yeti'), [])
        self.assertEqual(self.get(self.state, 'yeti')['attacksThisTurn'], 1)
        self.assertFalse(self.get(self.state, 'yeti')['ready'])

    def test_buffed_attack_and_health_are_used_in_combat(self):
        self.add('yeti')['ready'] = True
        self.add('enemy', player=1)
        self.play('CS2_092', 'yeti')
        result = self.engine.attack(self.state, 0, 'yeti', 'enemy')
        self.assertEqual(self.get(result, 'enemy')['zone'], 'GRAVEYARD')
        self.assertEqual(self.engine.current_health(result, self.get(result, 'yeti')), 5)

    def test_buff_target_restrictions_and_invalid_action_atomicity(self):
        self.add('enemy', player=1)['keywords'] = ['ELUSIVE']
        self.add('weapon', 'CS2_106')
        self.add('kings', 'CS2_092', zone='HAND')
        before = deepcopy(self.state)
        for target in (None, 'hero-0', 'weapon', 'enemy'):
            with self.assertRaises(ValueError): self.engine.play(self.state, 0, 'kings', target)
            self.assertEqual(self.state, before)

    def test_silence_removes_buff_and_caps_current_health_at_new_max(self):
        self.add('yeti')['damage'] = 3
        self.play('CS2_092', 'yeti')  # 8/9, current 6
        self.play('EX1_048', 'yeti', 'breaker')
        self.assertEqual(self.stats('yeti'), (4, 5, 5))
        self.assertEqual(self.get(self.state, 'yeti')['enchantments'], [])

    def test_silencing_wounded_buff_preserves_low_current_health(self):
        self.add('yeti')
        self.play('CS2_092', 'yeti')
        self.get(self.state, 'yeti')['damage'] = 8  # current 1 of 9
        self.play('EX1_048', 'yeti', 'breaker')
        self.assertEqual(self.stats('yeti'), (4, 5, 1))
        self.assertEqual(self.get(self.state, 'yeti')['damage'], 4)

    def test_silenced_minion_accepts_new_buffs(self):
        self.add('yeti')
        self.play('EX1_048', 'yeti', 'breaker')
        self.play('CS2_092', 'yeti')
        self.assertEqual(self.stats('yeti'), (8, 9, 9))

    def test_silence_removes_taunt_frozen_and_deathrattle(self):
        self.add('loot', 'EX1_096', player=1)['keywords'] = ['TAUNT', 'FROZEN']
        self.play('EX1_048', 'loot')
        self.assertEqual(self.get(self.state, 'loot')['keywords'], [])
        self.get(self.state, 'loot')['damage'] = 1
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.events(result, 'DEATHRATTLE'), [])

    def test_champion_aura_affects_only_other_friendly_minions(self):
        self.add('yeti')
        self.add('enemy', player=1)
        self.play('CS2_222', entity_id='champ')
        self.assertEqual(self.stats('champ'), (6, 6, 6))
        self.assertEqual(self.stats('yeti'), (5, 6, 6))
        self.assertEqual(self.stats('enemy'), (4, 5, 5))
        self.assertEqual(self.get(self.state, 'hero-0')['maxHealth'], 30)

    def test_new_minion_immediately_receives_existing_aura(self):
        self.add('champ', 'CS2_222')
        self.play('CS2_182', entity_id='new-yeti')
        self.assertEqual(self.stats('new-yeti'), (5, 6, 6))
        self.assertFalse(self.get(self.state, 'new-yeti')['ready'])

    def test_two_champions_stack_and_buff_each_other(self):
        self.add('champ1', 'CS2_222')
        self.add('champ2', 'CS2_222')
        self.add('yeti')
        self.state = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.stats('champ1'), (7, 7, 7))
        self.assertEqual(self.stats('champ2'), (7, 7, 7))
        self.assertEqual(self.stats('yeti'), (6, 7, 7))

    def test_buffs_and_auras_are_separate_additive_layers(self):
        self.add('champ', 'CS2_222')
        self.add('yeti')
        self.play('CS2_092', 'yeti')
        self.assertEqual(self.stats('yeti'), (9, 10, 10))
        self.assertEqual(len(self.get(self.state, 'yeti')['enchantments']), 1)
        self.play('EX1_048', 'yeti', 'breaker')
        self.assertEqual(self.stats('yeti'), (5, 6, 6))  # external aura remains

    def test_silencing_aura_source_removes_aura_but_not_recipient_buff(self):
        self.add('champ', 'CS2_222')
        self.add('yeti')
        self.play('CS2_092', 'yeti')
        self.play('EX1_048', 'champ', 'breaker')
        self.assertEqual(self.stats('yeti'), (8, 9, 9))
        self.assertEqual(len(self.get(self.state, 'yeti')['enchantments']), 1)

    def test_aura_loss_preserves_damaged_minions_current_health(self):
        self.add('champ', 'CS2_222')
        self.add('loot', 'EX1_096')
        self.state = self.engine.resolve_deaths(self.state)
        self.get(self.state, 'loot')['damage'] = 1  # 1 of 2
        self.get(self.state, 'champ')['damage'] = 6
        self.state = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.stats('loot'), (2, 1, 1))
        self.assertEqual(self.get(self.state, 'loot')['zone'], 'PLAY')
        self.assertEqual(self.events(self.state, 'DEATHRATTLE'), [])

    def test_aura_raises_lethal_threshold_before_death_checks(self):
        self.add('champ', 'CS2_222')
        self.add('loot', 'EX1_096')['damage'] = 1
        self.state = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.stats('loot'), (3, 2, 1))
        self.assertEqual(self.state['deathHistory'], [])

    def test_aura_loss_does_not_rescue_minions_already_dead_in_same_batch(self):
        self.add('champ', 'CS2_222')
        self.add('loot', 'EX1_096')
        self.state = self.engine.resolve_deaths(self.state)
        self.get(self.state, 'champ')['damage'] = 6
        self.get(self.state, 'loot')['damage'] = 2
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.events(result, 'DEATH_BATCH')[-1]['targets'], ['champ', 'loot'])
        self.assertEqual(len(self.events(result, 'DEATHRATTLE')), 1)

    def test_source_aura_removed_before_its_deathrattle_effects(self):
        champ = definition(self.catalog, 'CS2_222')
        champ['mechanics'].append('DEATHRATTLE')
        effect = {'op': 'DEAL_DAMAGE', 'amount': {'kind': 'CONSTANT', 'value': 1},
                  'recipient': {'kind': 'QUERY', 'capture': 'EFFECT_START',
                                'selector': {'zone': 'PLAY', 'entityKind': 'MINION', 'controller': 'FRIENDLY'}},
                  'missingRecipient': 'SKIP', 'damageClass': 'ABILITY', 'application': 'SINGLE_DAMAGE_BATCH'}
        champ['abilities'].append({'kind': 'DEATHRATTLE', 'effects': [effect]})
        self.engine = Prototype(self.catalog)
        self.add('champ', 'CS2_222')
        self.add('loot', 'EX1_096')
        self.state = self.engine.resolve_deaths(self.state)
        self.get(self.state, 'champ')['damage'] = 6
        result = self.engine.resolve_deaths(self.state)
        self.assertEqual([e['targets'] for e in self.events(result, 'DEATH_BATCH')], [['champ'], ['loot']])

    def test_transform_discards_buffs_and_receives_external_aura_afresh(self):
        self.add('champ', 'CS2_222')
        self.add('yeti')
        self.play('CS2_092', 'yeti')
        self.get(self.state, 'yeti')['damage'] = 8
        self.play('CS2_022', 'yeti', 'poly')
        self.assertEqual(self.get(self.state, 'yeti')['cardId'], 'CS2_tk1')
        self.assertEqual(self.stats('yeti'), (2, 2, 2))
        self.assertEqual(self.get(self.state, 'yeti')['enchantments'], [])

    def test_transforming_aura_source_removes_its_aura(self):
        self.add('champ', 'CS2_222')
        self.add('yeti')
        self.play('CS2_022', 'champ')
        self.assertEqual(self.stats('yeti'), (4, 5, 5))

    def test_aura_follows_controller_change_in_arranged_fixture(self):
        self.add('champ', 'CS2_222')
        self.add('friendly')
        self.add('enemy', player=1)
        self.state = self.engine.resolve_deaths(self.state)
        self.get(self.state, 'champ')['controller'] = 1
        self.state = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.stats('friendly'), (4, 5, 5))
        self.assertEqual(self.stats('enemy'), (5, 6, 6))

    def test_aura_is_absent_in_hand_or_graveyard(self):
        champ = self.add('champ', 'CS2_222', zone='HAND')
        self.add('yeti')
        self.assertEqual(self.stats('yeti'), (4, 5, 5))
        champ['zone'] = 'GRAVEYARD'
        self.assertEqual(self.stats('yeti'), (4, 5, 5))

    def test_stat_queries_are_read_only_and_refresh_does_not_accumulate(self):
        self.add('champ', 'CS2_222')
        self.add('yeti')
        before = deepcopy(self.state)
        self.assertEqual(self.stats('yeti'), (5, 6, 6))
        self.assertEqual(self.state, before)
        self.state = self.engine.resolve_deaths(self.state)
        self.assertEqual(self.engine.resolve_deaths(self.state), self.state)

    def test_bad_stat_enchantment_is_rejected_atomically(self):
        self.add('yeti')['enchantments'] = [{'kind': 'STAT_BUFF', 'attack': True, 'health': 1}]
        before = deepcopy(self.state)
        with self.assertRaises(ValueError): self.engine.resolve_deaths(self.state)
        self.assertEqual(self.state, before)

    def test_stats_events_and_final_states_are_deterministic_and_serializable(self):
        self.add('yeti')
        self.add('kings', 'CS2_092', zone='HAND')
        before = deepcopy(self.state)
        result = self.engine.play(self.state, 0, 'kings', 'yeti')
        self.assertEqual(len(self.events(result, 'STATS_CHANGED')), 1)
        self.assertEqual(result, self.engine.play(self.state, 0, 'kings', 'yeti'))
        self.assertEqual(result, json.loads(json.dumps(result)))
        self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
