"""Stage 11: pinned deck construction, detached transport and persistence."""

from copy import deepcopy
import json
import unittest

from examples.play_client import deck, run
from hearthstone.catalog import load
from hearthstone.contracts import Session, digest, validate
from hearthstone.decks import FORMAT
from hearthstone.match import MatchEngine
from test_zones import ZoneFixture
from tools.bench import random_game


class ConstructedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MatchEngine()

    def test_each_supported_class_and_exact_normalized_references(self):
        for cls, power, class_card in [
            ('MAGE', 'CS2_034', 'CS2_029'),
            ('PRIEST', 'CS1h_001', 'CS2_235'),
            ('PALADIN', 'CS2_101', 'CS2_097'),
        ]:
            cards = deck()
            cards[:2] = [class_card] * 2
            before = deepcopy(cards)
            exact = self.engine.validate_deck(cards, cls)
            self.assertTrue(all(set(ref) == {'cardId', 'revision'} for ref in exact))
            state = self.engine.new_constructed_game([cards, exact], [cls, cls], 1)
            self.assertEqual(cards, before)
            self.assertEqual(state['match']['profile'], FORMAT)
            self.assertEqual(state['match']['classes'], [cls, cls])
            self.assertEqual(
                self.engine._entity(state, 'hero-power-0')['cardId'], power
            )
            self.assertEqual(self.engine.restore(self.engine.checkpoint(state)), state)
            self.assertNotIn('classes', self.engine.view(state, 0))

    def test_size_class_copy_and_noncollectible_rejection(self):
        cases = [(deck()[:-1], 'exactly 30'), (deck() + ['CS2_182'], 'exactly 30')]
        for cid, message in [
            ('CS2_106', 'wrong class'),
            ('EX1_238', 'wrong class'),
            ('CS2_182', 'copy limit'),
            ('CS2_tk1', 'collectible'),
            ('GAME_005', 'collectible'),
            ('CS2_034', 'collectible'),
        ]:
            cards = deck()
            cards[-1] = cid
            cases.append((cards, message))
        legendary = deck()
        legendary[-2:] = ['EX1_014'] * 2
        cases.append((legendary, 'copy limit'))
        for cards, message in cases:
            with self.subTest(message=message, cards=cards):
                with self.assertRaisesRegex(ValueError, message):
                    self.engine.validate_deck(cards, 'MAGE')
        legendary[-1] = 'CS2_142'
        self.engine.validate_deck(legendary, 'MAGE')

    def test_unknown_format_class_reference_and_malformed_input(self):
        for cls in ('WARRIOR', 'NEUTRAL', '', None, True, []):
            with self.assertRaisesRegex(ValueError, 'hero class'):
                self.engine.validate_deck(deck(), cls)
        for fmt in ('STANDARD', 'WILD', 'FOUNDATION_CONSTRUCTED_V2', None):
            with self.assertRaisesRegex(ValueError, 'format'):
                self.engine.validate_deck(deck(), 'MAGE', fmt)
        for ref in (
            'missing',
            {'cardId': 'CS2_182', 'revision': 'missing'},
            {'cardId': 'CS2_182'},
            {'cardId': True, 'revision': 1},
            None,
        ):
            cards = deck()
            cards[-1] = ref
            with self.assertRaises(ValueError):
                self.engine.validate_deck(cards, 'MAGE')
        for decks, classes in [
            (None, ['MAGE'] * 2),
            ([deck()], ['MAGE'] * 2),
            ([deck()] * 2, ['MAGE']),
            ([deck()] * 2, 'MAGE'),
        ]:
            with self.assertRaises(ValueError):
                self.engine.new_constructed_game(decks, classes, 0)

    def test_copies_count_across_revisions_and_ambiguous_shorthand_rejected(self):
        catalog = load()
        original = next(c for c in catalog['cards'] if c['cardId'] == 'CS2_182')
        alternate = deepcopy(original)
        alternate['revision'] = 'alternate-test-revision'
        catalog['cards'].append(alternate)
        engine = MatchEngine(catalog)
        cards = deck()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            engine.validate_deck(cards, 'MAGE')
        cards[:2] = [
            dict(cardId=original['cardId'], revision=original['revision']),
            dict(cardId=alternate['cardId'], revision=alternate['revision']),
        ]
        engine.validate_deck(cards, 'MAGE')
        cards[-1] = cards[1]
        with self.assertRaisesRegex(ValueError, 'copy limit'):
            engine.validate_deck(cards, 'MAGE')

    def test_catalog_fingerprint_also_guards_direct_managed_states(self):
        state = self.engine.new_game([['CS2_182'] * 4] * 2, 0, deck_size=4)
        catalog = load()
        catalog['cards'][0]['baseStats']['attack'] += 1
        other = MatchEngine(catalog)
        with self.assertRaisesRegex(ValueError, 'managed state'):
            other.apply(state, 0, {'type': 'concede'})
        with self.assertRaisesRegex(ValueError, 'managed state'):
            other.checkpoint(state)

    def test_sandbox_still_permits_fixture_decks(self):
        state = self.engine.new_game([['CS2_182'] * 4] * 2, 0, deck_size=4)
        self.assertEqual(state['match']['profile'], 'FOUNDATION_SANDBOX')

    def test_format_description_detaches_and_pins_pool(self):
        info = self.engine.contract()
        fmt = info['formats'][0]
        self.assertEqual(fmt['catalogHash'], self.engine.catalog_hash)
        reordered = load()
        reordered['cards'].reverse()
        self.assertEqual(MatchEngine(reordered).catalog_hash, self.engine.catalog_hash)
        self.assertEqual(fmt['deckSize'], 30)
        self.assertEqual(set(fmt['heroPowers']), {'MAGE', 'PRIEST', 'PALADIN'})
        self.assertEqual(len(fmt['pool']), 49)
        fmt['pool'].clear()
        self.assertEqual(len(self.engine.contract()['formats'][0]['pool']), 49)


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MatchEngine()

    def setUp(self):
        self.state = self.engine.new_constructed_game(
            [deck()] * 2, ['MAGE', 'PRIEST'], 7
        )
        self.session = Session(self.engine, self.state)

    def command(self, action, sequence=None):
        return dict(
            apiVersion='1.0',
            sequence=self.session.sequence if sequence is None else sequence,
            action=action,
        )

    def test_schema_and_detached_observations(self):
        for player in (0, 1):
            observation = self.session.observe(player)
            validate('observation', observation)
            validate('view', observation['view'])
            for action in observation['legalActions']:
                validate('action', action)
            serialized = json.dumps(observation)
            for private in (
                'catalogHash',
                'continuation',
                'initialHands',
                'privateTo',
                'rng',
                'playOrder',
            ):
                self.assertNotIn('"' + private + '"', serialized)
            observation['view']['entities'].clear()
            observation['legalActions'].clear()
            self.assertTrue(self.session.observe(player)['legalActions'])
        self.state['entities'].clear()
        self.assertTrue(self.session.observe(0)['view']['entities'])

    def test_sequence_guards_and_failed_submission_are_atomic(self):
        before = self.session.checkpoint()
        command = self.command({'type': 'mulligan', 'replace': []})
        self.session.submit(0, command)
        self.assertEqual(self.session.sequence, 1)
        committed = self.session.checkpoint()
        for player, bad in [
            (1, command),
            (1, self.command({'type': 'play', 'source': 'missing'})),
            (True, self.command({'type': 'concede'})),
        ]:
            with self.assertRaises(ValueError):
                self.session.submit(player, bad)
            self.assertEqual(self.session.checkpoint(), committed)
        self.assertNotEqual(before, committed)

    def test_unknown_versions_extra_fields_and_noninteger_sequences(self):
        before = self.session.checkpoint()
        for change in (
            {'apiVersion': '2.0'},
            {'sequence': True},
            {'sequence': 0.0},
            {'player': 1},
            {'sequence': -1},
            {'action': {'type': 'concede', 'extra': 1}},
        ):
            command = self.command({'type': 'concede'})
            command.update(change)
            with self.assertRaisesRegex(ValueError, 'command contract'):
                self.session.submit(0, command)
            self.assertEqual(before, self.session.checkpoint())

    def test_checkpoint_restore_and_finished_session(self):
        self.session.submit(0, self.command({'type': 'mulligan', 'replace': []}))
        checkpoint = json.loads(json.dumps(self.session.checkpoint()))
        self.assertIsNot(checkpoint['state'], self.session._state)
        restored = Session.resume(MatchEngine(), checkpoint)
        self.assertEqual(restored.sequence, 1)
        with self.assertRaises(TypeError):
            restored._state['events'][0]['firstPlayer'] = 1
        checkpoint['state']['entities'].clear()
        self.assertTrue(restored.observe(0)['view']['entities'])
        self.assertEqual(restored.observe(1), self.session.observe(1))
        command = self.command({'type': 'concede'})
        self.assertEqual(restored.submit(1, command), self.session.submit(1, command))
        self.assertEqual(restored.observe(0)['legalActions'], [])
        validate('checkpoint', restored.checkpoint())
        with self.assertRaises(ValueError):
            restored.submit(0, dict(command, sequence=2))

    def test_checkpoint_versions_catalog_limits_and_checksum(self):
        original = self.session.checkpoint()
        for change, message in [
            ({'checkpointVersion': '2.0'}, 'checkpoint contract'),
            ({'rulesVersion': 'other'}, 'checkpoint contract'),
            ({'catalogHash': '0' * 64}, 'catalog fingerprint'),
            ({'sequence': True}, 'checkpoint contract'),
        ]:
            changed = deepcopy(original)
            changed.update(change)
            with self.assertRaisesRegex(ValueError, message):
                self.engine.restore(changed)
        changed = deepcopy(original)
        changed['state']['turn'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.engine.restore(changed)
        with self.assertRaisesRegex(ValueError, 'resolution limits'):
            MatchEngine(max_choices=4).restore(original)
        catalog = load()
        catalog['cards'][0]['name'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'catalog fingerprint'):
            MatchEngine(catalog).restore(original)
        with self.assertRaisesRegex(ValueError, 'checkpoint contract'):
            self.engine.restore(self.session.observe(0)['view'])

    def test_checkpoint_semantic_damage_rejected_even_with_updated_checksum(self):
        def reject(edit):
            checkpoint = self.session.checkpoint()
            edit(checkpoint['state'])
            checkpoint['stateHash'] = digest(checkpoint['state'])
            with self.assertRaises(ValueError):
                self.engine.restore(checkpoint)

        reject(lambda s: s['entities'].append(deepcopy(s['entities'][0])))
        reject(lambda s: s['decks'][0].append('missing'))
        reject(lambda s: s['mana'].__setitem__(0, 10))
        reject(lambda s: s.update(phase='MAIN', result='DRAW'))
        reject(lambda s: s.update(_reactionFrames=[]))
        reject(lambda s: s['entities'][-1].update(revision='missing'))
        reject(lambda s: s['entities'][0].update(owner=True))
        reject(lambda s: s['resources'][0].update(filled=50))
        reject(lambda s: s['mulligan']['initialHands'][0].append('missing'))
        reject(lambda s: s['match'].update(classes=['MAGE', 'PALADIN']))

    def test_json_replay_during_complete_seeded_game(self):
        seen = set()

        def inspect(state, player, actions):
            checkpoint = self.engine.checkpoint(state)
            restored = self.engine.restore(json.loads(json.dumps(checkpoint)))
            self.assertEqual(state, restored)
            for owner in (0, 1):
                view = self.engine.view(state, owner)
                validate('view', view)
                self.assertEqual(view, self.engine.view(restored, owner))
            seen.add(state['phase'])
            validate(
                'observation',
                dict(
                    apiVersion='1.0',
                    sequence=0,
                    view=self.engine.view(state, player),
                    legalActions=actions,
                ),
            )

        for seed in (0, 3, 8, 17):
            random_game(self.engine, seed, inspect=inspect)
        self.assertIn('CHOICE', seen)

    def test_complete_view_only_client_and_exact_replay(self):
        result, trace, resumed = run()
        self.assertTrue(resumed)
        self.assertTrue(result)
        session = Session(
            self.engine,
            self.engine.new_constructed_game([deck(), deck()], ['MAGE', 'PRIEST'], 3),
        )
        for item in trace:
            session.submit(item['player'], item['command'])
        self.assertEqual(session.observe(0)['view']['result'], result)


class ChoiceCheckpointTests(ZoneFixture):
    def test_restore_pending_choice_and_reject_mutated_continuation(self):
        self.add('UNG_072', 'stonehill', zone='HAND')
        state = self.engine.play(self.state, 0, 'stonehill', position=0)
        self.assertEqual(state['phase'], 'CHOICE')
        checkpoint = self.engine.checkpoint(state)
        restored = self.engine.restore(json.loads(json.dumps(checkpoint)))
        action = next(
            a for a in self.engine.legal_actions(state, 0) if a['type'] == 'choose'
        )
        self.assertEqual(
            self.engine.apply(state, 0, action), self.engine.apply(restored, 0, action)
        )
        for mutate in (
            lambda s: s['pendingChoice']['options'].pop(),
            lambda s: s['pendingChoice'].update(player=1),
            lambda s: s['continuation']['start'].update(phase='CHOICE'),
            lambda s: s['continuation']['action'].update(source='missing'),
        ):
            changed = deepcopy(checkpoint)
            mutate(changed['state'])
            changed['stateHash'] = digest(changed['state'])
            with self.assertRaises(ValueError):
                self.engine.restore(changed)


class ActionContractTests(ZoneFixture):
    def test_schema_execution_agree_on_malformed_field_types(self):
        invalid = [
            {'type': 'play', 'source': []},
            {'type': 'play', 'source': True},
            {'type': 'play', 'source': ''},
            {'type': 'play', 'source': 'x', 'target': []},
            {'type': 'play', 'source': 'x', 'position': 1.0},
            {'type': 'play', 'source': 'x', 'position': True},
            {'type': 'play', 'source': 'x', 'position': 8},
            {'type': 'attack', 'attacker': {}, 'defender': 'hero-1'},
            {'type': 'mulligan', 'replace': ['x', 'x']},
            {'type': 'mulligan', 'replace': [True]},
            {'type': 'mulligan', 'replace': ()},
            {'type': 'choose', 'choice': 'choice-1', 'option': 1},
        ]
        before = deepcopy(self.state)
        for action in invalid:
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    validate('action', action)
                with self.assertRaises(ValueError):
                    self.engine.apply(self.state, 0, action)
                self.assertEqual(before, self.state)

    def test_null_option_spellings_and_closed_public_schema(self):
        self.add('CS2_182', 'null-yeti', zone='HAND')
        action = dict(type='play', source='null-yeti', target=None, position=None)
        validate('action', action)
        self.assertEqual(
            self.engine.apply(self.state, 0, action),
            self.engine.play(self.state, 0, 'null-yeti'),
        )
        for kind, value in [
            ('event', {'type': 'UNKNOWN'}),
            ('event', {'type': 'DRAW', 'entity': 'hidden', 'rng': {}}),
            ('view', dict(self.engine.view(self.state, 0), decks=[])),
        ]:
            with self.assertRaises(ValueError):
                validate(kind, value)
