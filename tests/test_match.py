from fixtures import enter
"""Stage 6: managed setup, mulligans, complete turns and resource accounting."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.match import MatchEngine
from hearthstone import resources, rng


def definition(catalog, card_id):
    return next(c for c in catalog['cards'] if c['cardId'] == card_id)


def draw_effect():
    return {'op': 'DRAW_CARD', 'count': 1, 'targetPlayer': 'EFFECT_CONTROLLER'}


class MatchCatalogTests(unittest.TestCase):

    def test_coin_and_bolt_definitions(self):
        coin = definition(load(), 'GAME_005')
        self.assertFalse(coin['collectible'])
        self.assertEqual(coin['baseStats']['manaCost'], 0)
        self.assertEqual(coin['abilities'][0]['effects'], [
            {'op': 'GAIN_MANA', 'count': 1, 'kind': 'TEMPORARY', 'targetPlayer': 'EFFECT_CONTROLLER'}])
        bolt = definition(load(), 'EX1_238')
        self.assertEqual((bolt['overload'], bolt['baseStats']['manaCost']), (1, 1))
        self.assertEqual(bolt['abilities'][0]['effects'][0]['amount']['value'], 3)

    def test_resource_schema_rejects_invalid_fields(self):
        for field, value in [('count', 0), ('count', True), ('count', -1),
                             ('kind', 'REFILL'), ('targetPlayer', 'SELF'), ('extra', 1)]:
            catalog = load()
            definition(catalog, 'GAME_005')['abilities'][0]['effects'][0][field] = value
            self.assertTrue(validate(catalog))
        for value in (0, True, -1, 1.5):
            catalog = load()
            definition(catalog, 'EX1_238')['overload'] = value
            self.assertTrue(validate(catalog))

    def test_resource_policy_and_old_schema_rejection(self):
        catalog = load()
        catalog['resourcePolicy'] = 'UNKNOWN'
        self.assertTrue(validate(catalog))


    def test_turn_triggers_cannot_request_targets_or_be_spell_abilities(self):
        for card_id in ('CS2_182', 'CS2_029'):
            catalog = load()
            card = definition(catalog, card_id)
            ability = {'kind': 'END_OF_TURN', 'effects': [draw_effect()]}
            if card_id == 'CS2_182':
                ability['targeting'] = deepcopy(definition(catalog, 'CS2_042')['abilities'][0]['targeting'])
            card['abilities'] = [ability]
            self.assertTrue(validate(catalog))


class RngTests(unittest.TestCase):
    def test_splitmix64_known_vectors(self):
        state = rng.new(0)
        self.assertEqual(rng.next_u64(state), 0xE220A8397B1DCDAF)
        self.assertEqual(rng.next_u64(state), 0x6E789E6AA1B965F4)
        self.assertEqual(state['draws'], 2)

    def test_rng_resumes_after_json_roundtrip(self):
        original = rng.new(123)
        rng.next_u64(original)
        restored = json.loads(json.dumps(original))
        self.assertEqual([rng.randbelow(original, 11) for _ in range(20)],
                         [rng.randbelow(restored, 11) for _ in range(20)])

    def test_shuffle_is_a_repeatable_permutation(self):
        a, b = list(range(30)), list(range(30))
        rng.shuffle(rng.new(77), a)
        rng.shuffle(rng.new(77), b)
        self.assertEqual(a, b)
        self.assertEqual(sorted(a), list(range(30)))
        self.assertNotEqual(a, list(range(30)))

    def test_invalid_seed_and_bounds_rejected(self):
        for seed in (True, '1', None):
            with self.assertRaises(ValueError): rng.new(seed)
        for bound in (0, -1, True, 1.5, (1 << 64) + 1):
            with self.assertRaises(ValueError): rng.randbelow(rng.new(0), bound)


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.engine = MatchEngine()

    def setup(self, size=12, first=0, **kwargs):
        return self.engine.new_game([['CS2_182'] * size, ['CS2_182'] * size],
                                    seed=17, first_player=first, deck_size=size, **kwargs)

    def main(self, **kwargs):
        state = self.setup(**kwargs)
        return self.engine.mulligan(self.engine.mulligan(state, 0, []), 1, [])

    @staticmethod
    def hand(state, player):
        return [e for e in state['entities'] if e['zone'] == 'HAND' and e['controller'] == player]

    @staticmethod
    def get(state, entity_id):
        return next(e for e in state['entities'] if e['id'] == entity_id)

    def add(self, state, entity_id, card_id, player=0, zone='HAND'):
        entity = self.engine.entity(entity_id, card_id, player, zone)
        state['entities'].append(entity)
        enter(self.engine, state, entity)
        return entity

    @staticmethod
    def events(state, kind):
        return [e for e in state['events'] if e['type'] == kind]

    def test_opening_hands_resources_and_unique_entities(self):
        state = self.setup()
        self.assertEqual(state['phase'], 'MULLIGAN')
        self.assertEqual([len(self.hand(state, p)) for p in (0, 1)], [3, 4])
        self.assertEqual(state['mana'], [0, 0])
        self.assertEqual(state['turn'], 0)
        self.assertEqual([len(d) for d in state['decks']], [9, 8])
        ids = [e['id'] for e in state['entities']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(any(e.get('cardId') == 'GAME_005' for e in state['entities']))

    def test_seeded_setup_is_repeatable_and_does_not_modify_decks(self):
        decks = [['CS2_182'] * 30, ['CS2_182'] * 30]
        before = deepcopy(decks)
        self.assertEqual(self.engine.new_game(decks, 7), self.engine.new_game(decks, 7))
        self.assertEqual(decks, before)
        self.assertNotEqual(self.engine.new_game(decks, 7)['rng'], self.engine.new_game(decks, 8)['rng'])

    def test_seeded_first_player_and_override(self):
        state = self.engine.new_game([['CS2_182'] * 30] * 2, 0)
        self.assertEqual(state['firstPlayer'], 1)  # Known first RNG output is odd.
        self.assertEqual([len(self.hand(state, p)) for p in (0, 1)], [4, 3])
        self.assertEqual(self.setup(first=1)['firstPlayer'], 1)

    def test_exact_definition_references_are_supported(self):
        reference = {'cardId': 'CS2_182', 'revision': 'foundation-v1'}
        state = self.engine.new_game([[reference] * 30] * 2, 9)
        self.assertTrue(all(e['revision'] == 'foundation-v1' for e in state['entities'] if e['kind'] not in ('HERO', 'HERO_POWER')))

    def test_bad_decks_and_configuration_rejected(self):
        for decks in ([], [['CS2_182'] * 30], [['CS2_182'] * 29] * 2,
                      [['GAME_005'] * 30] * 2, [['UNKNOWN'] * 30] * 2,
                      [[True] * 30] * 2):
            with self.subTest(decks=str(decks)[:20]), self.assertRaises(ValueError):
                self.engine.new_game(decks, 1)
        for kwargs in ({'deck_size': True}, {'turn_limit': 1}, {'mana_cap': 100}, {'first_player': True}):
            with self.assertRaises(ValueError): self.engine.new_game([['CS2_182'] * 30] * 2, 1, **kwargs)

    def test_first_submission_waits_without_replacing_or_granting_coin(self):
        state = self.setup()
        chosen = self.hand(state, 0)[0]['id']
        before = deepcopy(state)
        result = self.engine.mulligan(state, 0, [chosen])
        self.assertEqual(state, before)
        self.assertEqual(result['phase'], 'MULLIGAN')
        self.assertEqual(result['decks'], state['decks'])
        self.assertEqual(result['rng'], state['rng'])
        self.assertEqual(self.get(result, chosen)['zone'], 'HAND')
        self.assertFalse(any(e.get('cardId') == 'GAME_005' for e in result['entities']))

    def test_mulligan_excludes_rejected_instances_and_returns_them_to_deck(self):
        state = self.setup()
        marked = [e['id'] for e in self.hand(state, 0)]
        result = self.engine.mulligan(self.engine.mulligan(state, 0, marked), 1, [])
        hand_ids = {e['id'] for e in self.hand(result, 0)}
        self.assertTrue(set(marked).isdisjoint(hand_ids))
        self.assertTrue(set(marked) <= set(result['decks'][0]))
        # Another physical copy of the same definition is allowed back.
        self.assertTrue(all(e['cardId'] == 'CS2_182' for e in self.hand(result, 0)))
        self.assertEqual(len(hand_ids), 4)  # Three replacements + first turn draw.

    def test_submission_order_does_not_change_replacements_or_rng(self):
        state = self.setup()
        choices = [[e['id'] for e in self.hand(state, p)][:2] for p in (0, 1)]
        a = self.engine.mulligan(self.engine.mulligan(state, 0, choices[0]), 1, choices[1])
        b = self.engine.mulligan(self.engine.mulligan(state, 1, list(reversed(choices[1]))),
                                 0, list(reversed(choices[0])))
        self.assertEqual(a['decks'], b['decks'])
        self.assertEqual(a['rng'], b['rng'])
        self.assertEqual([self.hand(a, p) for p in (0, 1)], [self.hand(b, p) for p in (0, 1)])

    def test_bad_mulligans_are_atomic(self):
        state = self.setup()
        owned = self.hand(state, 0)[0]['id']
        enemy = self.hand(state, 1)[0]['id']
        for selection in ([owned, owned], [enemy], ['unknown'], 'all', [False]):
            before = deepcopy(state)
            with self.assertRaises(ValueError): self.engine.mulligan(state, 0, selection)
            self.assertEqual(state, before)
        state = self.engine.mulligan(state, 0, [])
        with self.assertRaises(ValueError): self.engine.mulligan(state, 0, [])

    def test_minimal_fixture_deck_cannot_replace_more_than_remaining_pool(self):
        state = self.setup(size=4)
        with self.assertRaises(ValueError):
            self.engine.mulligan(state, 1, [self.hand(state, 1)[0]['id']])

    def test_keep_hands_coin_and_turn_one_draw(self):
        state = self.main()
        self.assertEqual(state['phase'], 'MAIN')
        self.assertEqual((state['activePlayer'], state['turn'], state['playerTurns']), (0, 1, [1, 0]))
        self.assertEqual(state['mana'], [1, 0])
        self.assertEqual([len(self.hand(state, p)) for p in (0, 1)], [4, 5])
        self.assertEqual(self.get(state, 'setup-coin')['controller'], 1)
        self.assertEqual(self.get(state, 'setup-coin')['zone'], 'HAND')
        self.assertEqual(state['resources'][0]['permanent'], 1)

    def test_player_one_can_be_first(self):
        state = self.main(first=1)
        self.assertEqual(state['activePlayer'], 1)
        self.assertEqual(state['mana'], [0, 1])
        self.assertEqual(self.get(state, 'setup-coin')['controller'], 0)

    def test_main_actions_and_fixture_shortcuts_blocked_during_mulligan(self):
        state = self.setup()
        source = self.hand(state, 0)[0]['id']
        calls = [lambda: self.engine.play(state, 0, source),
                 lambda: self.engine.attack(state, 0, 'hero-0', 'hero-1'),
                 lambda: self.engine.end_turn(state, 0),
                 lambda: self.engine.begin_combat_turn(state, 0),
                 lambda: self.engine.draw(state, 0),
                 lambda: self.engine.resolve_deaths(state)]
        before = deepcopy(state)
        for call in calls:
            with self.assertRaises(ValueError): call()
            self.assertEqual(state, before)

    def test_end_turn_handover_refill_and_draw(self):
        state = self.main()
        before = deepcopy(state)
        result = self.engine.end_turn(state, 0)
        self.assertEqual(state, before)
        self.assertEqual((result['turn'], result['activePlayer'], result['phase']), (2, 1, 'MAIN'))
        self.assertEqual(result['mana'], [0, 1])
        self.assertEqual(len(self.hand(result, 1)), 6)
        result = self.engine.end_turn(result, 1)
        self.assertEqual(result['mana'], [2, 0])
        self.assertEqual(result['playerTurns'], [2, 1])

    def test_mana_growth_stops_at_cap(self):
        state = self.main(size=30)
        for _ in range(20): state = self.engine.end_turn(state, state['activePlayer'])
        self.assertEqual(state['resources'][0]['permanent'], 10)
        self.assertEqual(state['mana'][0], 10)
        self.assertEqual(state['resources'][1]['permanent'], 10)

    def test_summoning_exhaustion_refreshes_on_next_own_turn_only(self):
        state = self.main()
        self.add(state, 'doctor', 'EX1_011')
        state = self.engine.play(state, 0, 'doctor', 'hero-0')
        self.assertEqual(self.engine.attack_targets(state, 'doctor'), [])
        state = self.engine.end_turn(state, 0)
        self.assertFalse(self.get(state, 'doctor')['ready'])
        state = self.engine.end_turn(state, 1)
        self.assertIn('hero-1', self.engine.attack_targets(state, 'doctor'))
        state = self.engine.attack(state, 0, 'doctor', 'hero-1')
        self.assertEqual(self.engine.attack_targets(state, 'doctor'), [])

    def test_end_turn_full_hand_burn_uses_existing_draw_logic(self):
        state = self.main()
        for i in range(5): self.add(state, f'extra-{i}', 'CS2_182', player=1)
        before_deck = len(state['decks'][1])
        result = self.engine.end_turn(state, 0)
        self.assertEqual(len(self.hand(result, 1)), 10)
        self.assertEqual(len(result['decks'][1]), before_deck - 1)
        self.assertEqual(len(self.events(result, 'BURN')), 1)

    def test_automatic_draw_fatigue_can_end_game_before_main(self):
        state = self.main(size=4)
        self.get(state, 'hero-1')['damage'] = 29
        result = self.engine.end_turn(state, 0)
        self.assertEqual(result['result'], 'PLAYER_0_WINS')
        self.assertEqual(result['phase'], 'FINISHED')
        self.assertEqual(result['fatigue'], [0, 1])
        self.assertNotEqual(self.events(result, 'PHASE')[-1]['phase'], 'MAIN')

    def test_turn_limit_precedes_next_refill_and_draw(self):
        state = self.main(turn_limit=4)
        state = self.engine.end_turn(state, 0)
        state = self.engine.end_turn(state, 1)
        deck_sizes = [len(d) for d in state['decks']]
        result = self.engine.end_turn(state, 0)
        self.assertEqual((result['turn'], result['result'], result['phase']), (4, 'DRAW', 'FINISHED'))
        self.assertEqual([len(d) for d in result['decks']], deck_sizes)
        self.assertEqual(result['playerTurns'], [2, 1])

    def test_concession_allowed_during_mulligan_and_main(self):
        for state in (self.setup(), self.main()):
            result = self.engine.concede(state, 1)
            self.assertEqual((result['phase'], result['result']), ('FINISHED', 'PLAYER_0_WINS'))
            with self.assertRaises(ValueError): self.engine.concede(result, 0)

    def test_invalid_main_actions_are_atomic(self):
        state = self.main()
        before = deepcopy(state)
        for player in (1, -1, True):
            with self.assertRaises(ValueError): self.engine.end_turn(state, player)
        for action in ({'type': 'draw'}, {'type': 'end_turn', 'extra': 1},
                       {'type': 'play'}, {'type': 'unknown'}, []):
            with self.assertRaises(ValueError): self.engine.apply(state, 0, action)
            self.assertEqual(state, before)

    def test_apply_dispatches_valid_actions(self):
        state = self.setup()
        state = self.engine.apply(state, 0, {'type': 'mulligan', 'replace': []})
        state = self.engine.apply(state, 1, {'type': 'mulligan', 'replace': []})
        self.add(state, 'doctor', 'EX1_011')
        state = self.engine.apply(state, 0, {'type': 'play', 'source': 'doctor', 'target': 'hero-0'})
        state = self.engine.apply(state, 0, {'type': 'end_turn'})
        state = self.engine.apply(state, 1, {'type': 'concede'})
        self.assertEqual(state['result'], 'PLAYER_0_WINS')

    def test_phase_queue_is_ordered_and_owner_scoped(self):
        catalog = load()
        definition(catalog, 'CS2_182')['abilities'] = [{'kind': 'END_OF_TURN', 'effects': [draw_effect()]}]
        self.engine = MatchEngine(catalog)
        state = self.main()
        self.add(state, 'newer', 'CS2_182', zone='PLAY')['playOrder'] = 20
        self.add(state, 'older', 'CS2_182', zone='PLAY')['playOrder'] = 10
        self.add(state, 'enemy', 'CS2_182', player=1, zone='PLAY')['playOrder'] = 1
        result = self.engine.end_turn(state, 0)
        self.assertEqual([e['source'] for e in self.events(result, 'TURN_TRIGGER')], ['older', 'newer'])
        attempts = self.events(result, 'DRAW_ATTEMPT')
        self.assertEqual([e['source'] for e in attempts[-3:]], ['older', 'newer', None])

    def test_start_triggers_run_after_refill_before_draw(self):
        catalog = load()
        definition(catalog, 'CS2_182')['abilities'] = [{'kind': 'START_OF_TURN', 'effects': [draw_effect()]}]
        self.engine = MatchEngine(catalog)
        state = self.main()
        self.add(state, 'source', 'CS2_182', player=1, zone='PLAY')
        result = self.engine.end_turn(state, 0)
        events = result['events'][len(state['events']):]
        types = [e['type'] for e in events]
        self.assertLess(types.index('MANA_REFILL'), types.index('TURN_TRIGGER'))
        self.assertEqual([e['source'] for e in events if e['type'] == 'DRAW_ATTEMPT'], ['source', None])

    def test_dead_queued_turn_source_is_skipped(self):
        catalog = load()
        effect = {'op': 'DESTROY', 'recipient': {'kind': 'QUERY', 'capture': 'EFFECT_START',
                  'selector': {'zone': 'PLAY', 'entityKind': 'MINION', 'controller': 'ANY'}}, 'missingRecipient': 'SKIP'}
        definition(catalog, 'CS2_182')['abilities'] = [{'kind': 'END_OF_TURN', 'effects': [effect]}]
        self.engine = MatchEngine(catalog)
        state = self.main()
        self.add(state, 'first', 'CS2_182', zone='PLAY')['playOrder'] = 1
        self.add(state, 'second', 'CS2_182', zone='PLAY')['playOrder'] = 2
        result = self.engine.end_turn(state, 0)
        self.assertEqual([e['source'] for e in self.events(result, 'TURN_TRIGGER')], ['first'])
        self.assertEqual(self.get(result, 'second')['zone'], 'GRAVEYARD')

    def test_lethal_end_trigger_prevents_handover(self):
        catalog = load()
        effect = {'op': 'DEAL_DAMAGE', 'amount': {'kind': 'CONSTANT', 'value': 40},
                  'recipient': {'kind': 'QUERY', 'capture': 'EFFECT_START',
                    'selector': {'zone': 'PLAY', 'entityKind': 'CHARACTER', 'controller': 'OPPONENT_OF_EFFECT_CONTROLLER'}},
                  'missingRecipient': 'SKIP', 'damageClass': 'ABILITY', 'application': 'SINGLE_DAMAGE_BATCH'}
        definition(catalog, 'CS2_182')['abilities'] = [{'kind': 'END_OF_TURN', 'effects': [effect]}]
        self.engine = MatchEngine(catalog)
        state = self.main()
        self.add(state, 'source', 'CS2_182', zone='PLAY')
        result = self.engine.end_turn(state, 0)
        self.assertEqual((result['result'], result['turn']), ('PLAYER_0_WINS', 1))
        self.assertEqual(self.events(result, 'MANA_EXPIRE'), [])

    def test_mulligan_and_main_resume_from_json(self):
        state = self.setup()
        marked = [self.hand(state, 0)[0]['id']]
        state = self.engine.mulligan(state, 0, marked)
        restored = json.loads(json.dumps(state))
        self.assertEqual(self.engine.mulligan(state, 1, []), self.engine.mulligan(restored, 1, []))
        state = self.engine.mulligan(state, 1, [])
        restored = json.loads(json.dumps(state))
        self.assertEqual(self.engine.end_turn(state, 0), self.engine.end_turn(restored, 0))

    def test_full_pass_only_game_finishes_by_fatigue(self):
        state = self.main(size=8)
        for _ in range(89):
            if state['result'] is not None: break
            state = self.engine.end_turn(state, state['activePlayer'])
        self.assertIsNotNone(state['result'])
        self.assertNotEqual(state['turn'], 90)
        self.assertTrue(any(state['fatigue']))

    def test_overload_locks_next_own_turn_then_clears(self):
        state = self.main()
        self.add(state, 'bolt', 'EX1_238')
        state = self.engine.play(state, 0, 'bolt', 'hero-1')
        self.assertEqual(state['resources'][0]['pendingOverload'], 1)
        self.assertEqual(state['mana'][0], 0)
        self.assertEqual(self.get(state, 'hero-1')['damage'], 3)
        state = self.engine.end_turn(self.engine.end_turn(state, 0), 1)
        self.assertEqual((state['resources'][0]['permanent'], state['resources'][0]['locked'], state['mana'][0]), (2, 1, 1))
        self.assertEqual(state['resources'][0]['pendingOverload'], 0)
        state = self.engine.end_turn(self.engine.end_turn(state, 0), 1)
        self.assertEqual((state['resources'][0]['locked'], state['mana'][0]), (0, 3))

    def test_failed_bolt_does_not_spend_or_overload(self):
        state = self.main()
        self.add(state, 'bolt', 'EX1_238')
        before = deepcopy(state)
        with self.assertRaises(ValueError): self.engine.play(state, 0, 'bolt')
        self.assertEqual(state, before)

    def test_coin_expiration_and_temporary_first_spending(self):
        state = self.engine.end_turn(self.main(), 0)
        state = self.engine.play(state, 1, 'setup-coin')
        self.assertEqual((state['resources'][1]['filled'], state['resources'][1]['temporary']), (1, 1))
        self.add(state, 'doctor', 'EX1_011', player=1)
        state = self.engine.play(state, 1, 'doctor', 'hero-1')
        self.assertEqual((state['resources'][1]['filled'], state['resources'][1]['temporary']), (1, 0))
        self.assertEqual(self.events(state, 'MANA_SPENT')[-1]['temporary'], 1)
        self.assertEqual(state['cardsPlayedThisTurn'][1], 2)
        state = self.engine.end_turn(self.engine.end_turn(state, 1), 0)
        self.assertEqual((state['resources'][1]['permanent'], state['mana'][1]), (2, 2))
        self.assertEqual(state['cardsPlayedThisTurn'][1], 0)

    def test_unused_coin_mana_expires_without_permanent_growth(self):
        state = self.engine.end_turn(self.main(), 0)
        state = self.engine.play(state, 1, 'setup-coin')
        state = self.engine.end_turn(state, 1)
        self.assertEqual((state['resources'][1]['temporary'], state['resources'][1]['permanent'], state['mana'][1]), (0, 1, 0))

    def test_forged_mana_mirror_cannot_pay_for_cards(self):
        state = self.main()
        state['mana'][0] = 10
        source = self.hand(state, 0)[0]['id']
        before = deepcopy(state)
        with self.assertRaises(ValueError): self.engine.play(state, 0, source)
        self.assertEqual(state, before)

    def test_managed_engine_rejects_legacy_free_mana_fixture_states(self):
        from hearthstone.prototype import Prototype
        state = Prototype.state()
        self.add(state, 'source', 'CS2_182')
        with self.assertRaises(ValueError): self.engine.play(state, 0, 'source')
        with self.assertRaises(ValueError): self.engine.end_turn(state, 0)

    def test_complete_sandbox_game_uses_setup_play_combat_and_turns(self):
        from examples.play_match import run
        state, actions = run(17)
        self.assertEqual(state['phase'], 'FINISHED')
        self.assertTrue(state['result'].endswith('_WINS'))
        kinds = {entry['action']['type'] for entry in actions}
        self.assertTrue({'mulligan', 'play', 'attack', 'end_turn'} <= kinds)
        self.assertLess(state['turn'], 90)
        # Replay the public action sequence from the same seed, with no fixture
        # mutations, to establish an end-to-end deterministic match.
        replay = self.engine.new_game([['CS2_182'] * 30] * 2, 17)
        for entry in actions:
            replay = self.engine.apply(replay, entry['player'], entry['action'])
        self.assertEqual(replay, state)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.state = {'resources': [resources.fresh(), resources.fresh()], 'events': [], 'mana': [0, 0]}
        self.resource = self.state['resources'][0]

    def change(self, op='GAIN_MANA', count=1, kind='TEMPORARY'):
        effect = {'op': op, 'targetPlayer': 'EFFECT_CONTROLLER'}
        if op != 'UNLOCK_MANA': effect['count'] = count
        if op == 'GAIN_MANA': effect['kind'] = kind
        resources.change(self.state, 0, effect)

    def test_empty_and_filled_crystals_differ(self):
        self.change(kind='EMPTY', count=2)
        self.assertEqual((self.resource['permanent'], self.state['mana'][0]), (2, 0))
        self.change(kind='FILLED', count=2)
        self.assertEqual((self.resource['permanent'], self.state['mana'][0]), (4, 2))

    def test_crystal_and_temporary_gains_are_capped_without_hidden_mana(self):
        self.change(kind='FILLED', count=20)
        self.change(count=20)
        self.assertEqual((self.resource['permanent'], self.resource['temporary'], self.state['mana'][0]), (10, 0, 10))
        resources.spend(self.state, 0, 1)
        self.assertEqual(self.state['mana'][0], 9)

    def test_temp_can_restore_spent_mana_at_permanent_cap(self):
        self.resource.update(permanent=10, filled=8)
        self.change(count=1)
        self.assertEqual(self.state['mana'][0], 9)
        self.assertEqual(self.resource['permanent'], 10)

    def test_overload_beyond_permanent_offsets_temporary_mana(self):
        self.resource.update(permanent=3, filled=0, locked=4)
        self.change()
        self.assertEqual(self.state['mana'][0], 0)
        self.change()
        self.assertEqual(self.state['mana'][0], 1)

    def test_destroy_removes_empty_before_filled_and_floors_at_zero(self):
        self.resource.update(permanent=4, filled=2)
        self.change('DESTROY_MANA', 2)
        self.assertEqual((self.resource['permanent'], self.resource['filled']), (2, 2))
        self.change('DESTROY_MANA', 1)
        self.assertEqual((self.resource['permanent'], self.resource['filled']), (1, 1))
        self.change('DESTROY_MANA', 99)
        self.assertEqual((self.resource['permanent'], self.resource['filled']), (0, 0))

    def test_destruction_preserves_overload_counters(self):
        self.resource.update(permanent=4, filled=2, locked=2, pendingOverload=3)
        self.change('DESTROY_MANA', 3)
        self.assertEqual((self.resource['locked'], self.resource['pendingOverload']), (2, 3))
        self.assertEqual(self.state['mana'][0], 0)

    def test_unlock_refills_locked_and_clears_pending(self):
        self.resource.update(permanent=5, filled=1, locked=2, pendingOverload=3)
        self.change('UNLOCK_MANA')
        self.assertEqual((self.resource['filled'], self.resource['locked'], self.resource['pendingOverload']), (3, 0, 0))

    def test_unlock_does_not_create_hidden_over_cap_mana(self):
        self.resource.update(permanent=10, filled=8, temporary=2, locked=2)
        self.change('UNLOCK_MANA')
        self.assertEqual(self.state['mana'][0], 10)
        resources.spend(self.state, 0, 1)
        self.assertEqual(self.state['mana'][0], 9)

    def test_zero_cost_can_be_paid_when_fully_locked(self):
        self.resource.update(permanent=1, filled=0, locked=20)
        resources.spend(self.state, 0, 0)
        self.assertEqual(self.state['mana'][0], 0)
        with self.assertRaises(ValueError): resources.spend(self.state, 0, 1)

    def test_payment_must_be_available_in_full(self):
        self.resource.update(permanent=2, filled=1, temporary=1)
        before = deepcopy(self.state)
        with self.assertRaises(ValueError): resources.spend(self.state, 0, 3)
        self.assertEqual(self.state, before)

    def test_custom_cap_and_bad_caps(self):
        self.assertEqual(resources.fresh(3)['cap'], 3)
        for cap in (0, 100, True, 1.5):
            with self.assertRaises(ValueError): resources.fresh(cap)


if __name__ == '__main__':
    unittest.main()
