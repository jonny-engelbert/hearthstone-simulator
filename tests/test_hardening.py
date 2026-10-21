"""Live Spell Damage and public client boundaries."""

from copy import deepcopy
import json
import unittest

from hearthstone.catalog import load, validate
from hearthstone.match import MatchEngine
from test_zones import ZoneFixture, card


class DispatchTests(unittest.TestCase):
    def test_every_schema_operation_has_a_handler(self):
        from hearthstone.catalog import ROOT
        from hearthstone.effects import EffectOperations
        from hearthstone.prototype import Prototype

        schema = json.loads((ROOT / 'schemas/catalog.schema.json').read_text())
        operations = {
            branch['properties']['op']['const']
            for branch in schema['$defs']['effect']['oneOf']
        }
        self.assertEqual(operations, set(EffectOperations.EFFECT_HANDLERS))
        for handler in EffectOperations.EFFECT_HANDLERS.values():
            self.assertTrue(callable(getattr(Prototype, handler)))


class ChronologyTests(unittest.TestCase):
    def test_missing_entry_stamps_and_sequence_are_rejected_atomically(self):
        from hearthstone.prototype import Prototype

        engine = Prototype(load())
        for missing in ('playOrder', 'nextPlayOrder'):
            state = engine.state()
            entity = engine.entity('unstamped', 'CS2_182', 0)
            entity['playOrder'] = 1
            state['nextPlayOrder'] = 2
            state['entities'].append(entity)
            del (entity if missing == 'playOrder' else state)[missing]
            before = deepcopy(state)
            with self.assertRaisesRegex(ValueError, 'playOrder|nextPlayOrder'):
                engine.resolve_deaths(state)
            self.assertEqual(before, state)


class SpellDamageTests(ZoneFixture):
    def test_kobold_fireball_and_stacking(self):
        self.add('CS2_142', 'kobold')
        self.play('CS2_029', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 7)
        self.refill()
        self.add('CS2_142', 'second')
        self.play('CS2_029', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 15)

    def test_flamestrike_bonus_is_applied_to_each_recipient(self):
        self.add('CS2_142', 'kobold')
        self.add(eid='first', player=1)
        self.add(eid='second', player=1)
        self.play('CS2_032')
        # Inspect all damage from this action without relying on fixture IDs.
        self.assertEqual(
            [(e['target'], e['amount']) for e in self.events('DAMAGE')],
            [('first', 5), ('second', 5)],
        )

    def test_silence_death_and_zone_exit_remove_bonus(self):
        for condition in ('silence', 'dead', 'destroy', 'hand', 'deck', 'enemy'):
            with self.subTest(condition=condition):
                self.restart()
                source = self.add('CS2_142', 'kobold')
                if condition == 'silence':
                    self.play('EX1_048', 'kobold')
                    self.refill()
                elif condition == 'dead':
                    source['damage'] = 2
                elif condition == 'destroy':
                    source['pendingDestroy'] = True
                elif condition in ('hand', 'deck'):
                    source['zone'] = condition.upper()
                    if condition == 'deck':
                        self.state['decks'][0].append(source['id'])
                else:
                    source['controller'] = 1
                self.play('CS2_029', 'hero-1')
                self.assertEqual(self.get('hero-1')['damage'], 6)

    def test_power_fatigue_and_battlecry_are_unaffected(self):
        self.add('CS2_142', 'kobold')
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.play('CS2_042', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 4)
        for entity in self.state['entities']:
            if entity['zone'] == 'DECK' and entity['controller'] == 0:
                entity['zone'] = 'SET_ASIDE'
        self.state['decks'][0] = []
        self.play('EX1_015')
        self.assertEqual(self.get('hero-0')['damage'], 1)

    def test_spell_damage_metadata_is_validated(self):
        for value in (0, -1, True, 1.5):
            catalog = load()
            card(catalog, 'CS2_142')['spellDamage'] = value
            self.assertTrue(any('spellDamage' in error for error in validate(catalog)))
        catalog = load()
        del card(catalog, 'CS2_142')['spellDamage']
        self.assertIn(
            'CS2_142: SPELL_DAMAGE keyword and amount must agree', validate(catalog)
        )


class PlayerViewTests(ZoneFixture):
    def test_private_entities_ids_and_bookkeeping_are_absent(self):
        self.add('EX1_287', 'SECRET_CARD_IDENTITY', 1, 'SECRET')
        self.add('CS2_029', 'PRIVATE_HAND_IDENTITY', 1, 'HAND')
        self.add('CS2_042', 'PRIVATE_DECK_IDENTITY', 0, 'DECK')
        before = deepcopy(self.state)
        view = self.engine.view(self.state, 0)
        encoded = json.dumps(view)
        for hidden in (
            'SECRET_CARD_IDENTITY',
            'PRIVATE_HAND_IDENTITY',
            'PRIVATE_DECK_IDENTITY',
            'EX1_287',
            'CS2_029',
            'CS2_042',
            'rng',
            'deathHistory',
            'nextPlayOrder',
            'scheduler',
            'initialHands',
            'choices',
            'playOrder',
        ):
            self.assertNotIn(hidden, encoded)
        self.assertEqual(view['players'][1]['secrets'], [{'name': 'a Secret'}])
        self.assertEqual(self.state, before)
        view['entities'][0]['damage'] = 99
        self.assertEqual(self.get('hero-0')['damage'], 0)

    def test_private_generation_without_a_public_source_stays_hidden(self):
        self.add('CS2_042', 'hidden-generated-id', 1, 'HAND')
        self.state['events'].append(
            dict(
                type='GENERATED',
                entity='hidden-generated-id',
                source=None,
                cardId='CS2_042',
                player=1,
            )
        )
        view = self.engine.view(self.state, 0)
        self.assertNotIn('CS2_042', json.dumps(view))
        self.assertNotIn('hidden-generated-id', json.dumps(view))

    def test_hidden_identity_and_deck_permutations_do_not_change_view(self):
        self.add('EX1_287', 'hidden-secret', 1, 'SECRET')
        self.add('CS2_029', 'hidden-hand', 1, 'HAND')
        original = self.engine.view(self.state, 0)
        other = deepcopy(self.state)
        for eid, cid in [('hidden-secret', 'EX1_594'), ('hidden-hand', 'CS2_042')]:
            old = self.engine._entity(other, eid)
            old.update(cardId=cid, revision=card(self.catalog, cid)['revision'])
            old['id'] = f'private-{cid}'
        other['decks'][0].reverse()
        other['decks'][1].reverse()
        other['rng']['state'] = 123
        self.assertEqual(original, self.engine.view(other, 0))

    def test_opponent_draw_has_no_handle_but_burn_is_public(self):
        self.add('CS2_029', 'private-top', 1, 'DECK')
        self.state['decks'][1].remove('private-top')
        self.state['decks'][1].insert(0, 'private-top')
        self.engine._draw(self.state, 1, 1, None)
        view = self.engine.view(self.state, 0)
        self.assertEqual(view['events'][-1], {'type': 'DRAW', 'player': 1})
        self.assertNotIn('private-top', json.dumps(view))
        self.fill_hand(1)
        self.add('CS2_042', 'burn-top', 1, 'DECK')
        self.state['decks'][1].remove('burn-top')
        self.state['decks'][1].insert(0, 'burn-top')
        self.engine._draw(self.state, 1, 1, None)
        view = self.engine.view(self.state, 0)
        self.assertTrue(
            any(
                e.get('cardId') == 'CS2_042'
                for e in view['events']
                if e['type'] == 'REVEAL'
            )
        )
        self.assertTrue(
            any(
                e.get('entity') == 'burn-top'
                for e in view['events']
                if e['type'] == 'BURN'
            )
        )

    def test_own_hand_visible_and_public_bounce_remains_known(self):
        self.add('CS2_029', 'own-fireball', zone='HAND')
        self.add('CS2_042', 'public-minion', 1)
        self.play('EX1_581', 'public-minion')
        view = self.engine.view(self.state, 0)
        self.assertIn(
            'own-fireball', {c['id'] for c in view['players'][0]['hand']['cards']}
        )
        self.assertEqual(
            [c['cardId'] for c in view['players'][1]['hand']['cards']], ['CS2_042']
        )

    def test_shuffle_clears_public_knowledge_and_redacts_cross_references(self):
        self.add('CS2_042', 'public-minion', 1)
        self.play('GVG_031', 'public-minion')
        view = self.engine.view(self.state, 0)
        self.assertNotIn('public-minion', json.dumps(view))
        self.assertNotIn('CS2_042', json.dumps(view))

    def test_secret_play_hides_handle_and_reveal_exposes_card(self):
        self.play('EX1_287', eid='counterspell-private')
        view = self.engine.view(self.state, 1)
        self.assertNotIn('counterspell-private', json.dumps(view))
        self.assertNotIn('EX1_287', json.dumps(view))
        self.assertIn(
            'counterspell-private', json.dumps(self.engine.view(self.state, 0))
        )
        self.end()
        self.play('GAME_005')
        self.assertIn('EX1_287', json.dumps(self.engine.view(self.state, 1)))
