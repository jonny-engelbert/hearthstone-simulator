"""Pinned build facts and choice-prefix visibility/persistence regressions."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from hearthstone.catalog import load, validate
from hearthstone.choices import request_hash
from hearthstone.contracts import Session
from test_zones import ZoneFixture, card

ROOT = Path(__file__).resolve().parents[1]


def encoded(state):
    return json.dumps(state, sort_keys=True, separators=(',', ':')).encode()


class ProfileTests(unittest.TestCase):
    def test_every_definition_matches_pinned_facts(self):
        catalog = load()
        source = json.loads((ROOT / 'docs/sources/card-profile.json').read_text())
        manifest = json.loads((ROOT / 'cards/manifest.json').read_text())
        self.assertEqual(source['revision'], 'af94b04fdff91a1900f4adfc873d89c76aa298cd')
        self.assertEqual(source['build'], '11.0.0.24118')
        self.assertEqual(manifest['targetClientBuild'], source['build'])
        self.assertEqual(manifest['cardDataSource']['revision'], source['revision'])
        self.assertEqual(manifest['cardDataSource']['sha256'], source['sha256'])
        self.assertEqual(catalog['rulesProfile'], source['profile'])
        facts = {c['cardId']: c for c in source['cards']}
        self.assertEqual(len(facts), 60)
        self.assertEqual(sum(c['collectible'] for c in facts.values()), 49)
        self.assertEqual({c['cardId'] for c in catalog['cards']}, set(facts))
        for definition in catalog['cards']:
            expected = facts[definition['cardId']]
            for field in ('name', 'type', 'baseStats', 'rarity', 'collectible'):
                self.assertEqual(
                    definition[field], expected[field], (definition['cardId'], field)
                )
            self.assertEqual(
                sorted(definition['keywords']), sorted(expected['keywords'])
            )
            self.assertEqual(definition['text']['enUS'], expected['text'])
        self.assertEqual(facts['CS2_188']['name'], 'Abusive Sergeant')
        self.assertEqual(facts['GIL_113']['name'], 'Rabid Worgen')

    def test_validation_cache_cannot_hide_mutation_or_non_json_types(self):
        catalog = load()
        self.assertEqual(validate(catalog), [])
        catalog['cards'][0]['baseStats']['health'] = -1
        self.assertTrue(validate(catalog))
        catalog = load()
        catalog['cards'][0]['classes'] = tuple(catalog['cards'][0]['classes'])
        self.assertTrue(validate(catalog))
        self.assertEqual(validate(load()), [])


class PrefixTests(ZoneFixture):
    def pending(self, cid='UNG_072', target=None):
        self.add(cid, 'source', zone='HAND')
        start = deepcopy(self.state)
        action = dict(type='play', source='source')
        if target is not None:
            action['target'] = target
        return start, action, self.engine.apply(start, 0, action)

    def final_matches_uninterrupted_replay(self, start, action, pending):
        request = pending['pendingChoice']
        answer = dict(
            option=request['options'][0]['id'], requestHash=request_hash(request)
        )
        # The old executor's final path: run once from the committed start with
        # the complete saved answer; no suspension/projection is visited.
        expected = self.engine._run_decision(start, 0, action, [answer])
        final = self.engine.choose(pending, 0, request['id'], answer['option'])
        self.assertEqual(encoded(final), encoded(expected))
        self.assertNotIn('continuation', final)
        return final

    def test_discover_both_views_show_placed_minion_spend_hand_and_prefix_events(self):
        start, action, pending = self.pending()
        self.assertEqual(
            start['entities'], pending['entities']
        )  # private committed root
        for player in (0, 1):
            view = self.engine.view(pending, player)
            entity = next(e for e in view['entities'] if e['id'] == 'source')
            self.assertEqual(entity['zone'], 'PLAY')
            self.assertEqual(view['mana'][0], 7)
            self.assertEqual(view['players'][0]['hand']['count'], 4)
            self.assertEqual(view['phase'], 'CHOICE')
            self.assertEqual(
                len(
                    [
                        e
                        for e in view['events']
                        if e['type'] == 'PLAY' and e.get('source') == 'source'
                    ]
                ),
                1,
            )
            self.assertTrue(
                any(
                    e['type'] == 'MANA_SPENT' and e['amount'] == 3
                    for e in view['events']
                )
            )
            self.assertTrue(
                any(
                    e['type'] == 'SUMMON' and e.get('entity') == 'source'
                    for e in view['events']
                )
            )
        own = self.engine.view(pending, 0)
        other = self.engine.view(pending, 1)
        self.assertEqual(len(own['choice']['options']), 3)
        self.assertEqual(other['choice'], dict(player=0, kind='DISCOVER'))
        for option in own['choice']['options']:
            if option['definition']['cardId'] != 'UNG_072':
                self.assertNotIn(option['definition']['cardId'], json.dumps(other))
            self.assertNotIn(option['id'], json.dumps(other))
        self.final_matches_uninterrupted_replay(start, action, pending)

    def test_choose_one_is_preplay_private_and_final_bytes_match(self):
        self.add(eid='enemy', player=1)
        start, action, pending = self.pending('EX1_154', 'enemy')
        self.assertEqual(self.engine.view(pending, 1), self.engine.view(start, 1))
        own = self.engine.view(pending, 0)
        self.assertEqual(own['mana'][0], 10)
        self.assertEqual(
            next(e for e in own['entities'] if e['id'] == 'source')['zone'], 'HAND'
        )
        self.assertEqual(len(own['choice']['options']), 2)
        self.assertEqual(self.engine.legal_actions(pending, 1), [{'type': 'concede'}])
        self.final_matches_uninterrupted_replay(start, action, pending)

    def test_earlier_effects_are_visible_at_discover_and_restore_is_exact(self):
        stone = card(self.catalog, 'UNG_072')
        stone['abilities'][0]['effects'].insert(
            0, dict(op='DRAW_CARD', count=1, targetPlayer='EFFECT_CONTROLLER')
        )
        self.restart()
        start, action, pending = self.pending()
        for player in (0, 1):
            view = self.engine.view(pending, player)
            self.assertEqual(
                view['players'][0]['deckCount'], len(start['decks'][0]) - 1
            )
            self.assertEqual(view['players'][0]['hand']['count'], 5)
        session = Session(self.engine, pending)
        restored = Session.resume(
            self.engine, json.loads(json.dumps(session.checkpoint()))
        )
        self.assertEqual(encoded(session.checkpoint()), encoded(restored.checkpoint()))
        for player in (0, 1):
            self.assertEqual(session.observe(player), restored.observe(player))
        command = dict(
            apiVersion='2.0',
            sequence=0,
            action=self.engine.legal_actions(pending, 0)[0],
        )
        self.assertEqual(session.submit(0, command), restored.submit(0, command))
        self.final_matches_uninterrupted_replay(start, action, pending)

    def test_forged_provisional_state_is_rejected_after_checksum_update(self):
        from hearthstone.contracts import digest

        _, _, pending = self.pending()
        checkpoint = self.engine.checkpoint(pending)
        checkpoint['state']['continuation']['prefix']['mana'][0] = 999
        checkpoint['stateHash'] = digest(checkpoint['state'])
        with self.assertRaisesRegex(ValueError, 'does not replay'):
            self.engine.restore(checkpoint)

    def test_concede_keeps_visible_discover_board_and_checkpoint_roundtrips(self):
        _, _, pending = self.pending()
        for player in (0, 1):
            result = self.engine.concede(pending, player)
            self.assertEqual(self.get('source', result)['zone'], 'PLAY')
            self.assertEqual(result['mana'][0], 7)
            self.assertEqual(result['result'], f'PLAYER_{1-player}_WINS')
            self.assertEqual(
                self.engine.restore(self.engine.checkpoint(result)), result
            )

    def test_nested_choice_shows_the_prefix_after_the_first_answer(self):
        stone = card(self.catalog, 'UNG_072')
        stone['abilities'][0]['effects'] *= 2
        self.restart()
        _, _, pending = self.pending()
        first = pending['pendingChoice']
        second = self.engine.choose(pending, 0, first['id'], first['options'][0]['id'])
        own = self.engine.view(second, 0)
        self.assertTrue(any(e['type'] == 'GENERATED' for e in own['events']))
        self.assertEqual(own['mana'][0], 7)
        checkpoint = self.engine.checkpoint(second)
        self.assertEqual(self.engine.restore(checkpoint), second)
        other = json.dumps(self.engine.view(second, 1))
        generated = next(
            e
            for e in second['continuation']['prefix']['entities']
            if e.get('createdBy') == 'source'
        )
        self.assertNotIn(generated['id'], other)

    def test_resolving_discover_spell_is_public_but_resolving_secret_stays_hidden(self):
        discover = deepcopy(card(self.catalog, 'UNG_072')['abilities'][0]['effects'][0])
        fireball = card(self.catalog, 'CS2_029')
        fireball['mechanics'] = ['DISCOVER']
        fireball['abilities'][0]['effects'] = [discover]
        self.restart()
        start, action, pending = self.pending('CS2_029', 'hero-1')
        for player in (0, 1):
            view = self.engine.view(pending, player)
            self.assertEqual(
                next(e for e in view['entities'] if e['id'] == 'source')['zone'],
                'RESOLVING',
            )
            self.assertTrue(
                any(
                    e.get('source') == 'source' and e['type'] == 'PLAY'
                    for e in view['events']
                )
            )
        self.final_matches_uninterrupted_replay(start, action, pending)
        counter = card(self.catalog, 'EX1_287')
        counter['mechanics'].append('DISCOVER')
        counter['abilities'][0]['effects'] = [discover]
        self.restart()
        self.add('EX1_287', 'counter', 1, 'SECRET')
        _, _, pending = self.pending('EX1_130')
        self.assertEqual(pending['pendingChoice']['player'], 1)
        other = json.dumps(self.engine.view(pending, 1))
        self.assertNotIn('EX1_130', other)
        self.assertNotIn('"id": "source"', other)
        self.assertEqual(self.engine.restore(self.engine.checkpoint(pending)), pending)

    def test_offturn_start_prompt_projects_new_active_player_and_resource_refill(self):
        discover = deepcopy(card(self.catalog, 'UNG_072')['abilities'][0]['effects'][0])
        yeti = card(self.catalog, 'CS2_182')
        yeti['mechanics'] = ['DISCOVER']
        yeti['abilities'] = [dict(kind='START_OF_TURN', effects=[discover])]
        self.restart()
        self.add(eid='listener', player=1)
        pending = self.engine.end_turn(self.state, 0)
        self.assertEqual(pending['activePlayer'], 0)  # private committed root
        self.assertEqual(pending['pendingChoice']['player'], 1)
        for player in (0, 1):
            view = self.engine.view(pending, player)
            self.assertEqual(view['activePlayer'], 1)
            self.assertEqual(view['turn'], 2)
            self.assertTrue(
                any(
                    e['type'] == 'MANA_REFILL' and e['player'] == 1
                    for e in view['events']
                )
            )
        session = Session(self.engine, pending)
        restored = Session.resume(
            self.engine, json.loads(json.dumps(session.checkpoint()))
        )
        self.assertEqual(restored.observe(1), session.observe(1))
