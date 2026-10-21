"""Stage 10: seeded outcomes, private offers, atomic prompts and JSON resume."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from fixtures import assert_invalid
from hearthstone import rng
from hearthstone.catalog import load, validate
from hearthstone.match import MatchEngine
from hearthstone.prototype import ResolutionLimitError
from test_zones import ZoneFixture, card
from tools.bench import check_invariants


def damage(amount=1):
    return dict(
        op='DEAL_DAMAGE',
        amount=dict(kind='CONSTANT', value=amount),
        recipient=dict(kind='CONTROLLER_HERO'),
        missingRecipient='SKIP',
        application='SINGLE_HIT',
        damageClass='ABILITY',
    )


def nested_choice():
    return dict(
        op='CHOOSE_ONE',
        options=[
            dict(id='option-0', label='One', effects=[damage(1)]),
            dict(id='option-1', label='Two', effects=[damage(2)]),
        ],
    )


class Stage10CatalogTests(unittest.TestCase):
    def test_new_cards_and_verified_stats(self):
        catalog = load()
        self.assertEqual(len(catalog['cards']), 60)
        self.assertEqual(
            card(catalog, 'KAR_009')['baseStats'], dict(manaCost=1, attack=1, health=2)
        )
        self.assertEqual(
            card(catalog, 'UNG_072')['baseStats'], dict(manaCost=3, attack=1, health=5)
        )
        self.assertEqual(card(catalog, 'CS2_125')['keywords'], ['TAUNT'])
        self.assertEqual(card(catalog, 'CS1_042')['keywords'], ['TAUNT'])
        self.assertEqual(validate(catalog), [])

    def test_nested_effects_receive_normal_semantic_validation(self):
        catalog = load()
        option = card(catalog, 'EX1_154')['abilities'][0]['effects'][0]['options'][0]
        option['effects'][0]['damageClass'] = 'ABILITY'
        assert_invalid(self, catalog, 'EX1_154: incompatible damage class')
        option['effects'][0]['damageClass'] = 'SPELL'
        option['effects'][0]['recipient']['name'] = 'unbound'
        assert_invalid(self, catalog, 'EX1_154: unbound target unbound')

    def test_choice_ids_and_labels_are_strict(self):
        for mutation in ('duplicate', 'label', 'extra'):
            catalog = load()
            options = card(catalog, 'EX1_154')['abilities'][0]['effects'][0]['options']
            if mutation == 'duplicate':
                options[1]['id'] = options[0]['id']
                expected = 'EX1_154: duplicate choice option ID'
            elif mutation == 'label':
                options[0]['label'] = ''
                expected = ('label', 'should be non-empty')
            else:
                options[0]['unknown'] = 1
                expected = ('unknown', 'Additional properties')
            assert_invalid(self, catalog, expected)

    def test_choice_mechanic_labels_must_match_effects(self):
        for cid, mechanic in [('EX1_154', 'CHOOSE_ONE'), ('UNG_072', 'DISCOVER')]:
            catalog = load()
            card(catalog, cid)['mechanics'].remove(mechanic)
            assert_invalid(
                self, catalog, f'{cid}: {mechanic} label and effect disagree'
            )

    def test_pools_random_hits_and_recipients_are_strict(self):
        for cid, key, value, message in [
            ('KAR_009', 'pool', {'cardType': 'HERO'}, "'HERO' is not one of"),
            ('EX1_277', 'hits', 0, 'less than the minimum'),
            ('EX1_277', 'hits', True, "not of type 'integer'"),
            ('EX1_277', 'hits', 31, 'greater than the maximum'),
            ('EX1_277', 'damageClass', 'ABILITY', 'incompatible damage class'),
        ]:
            catalog = load()
            card(catalog, cid)['abilities'][0]['effects'][0][key] = value
            assert_invalid(self, catalog, message)
        catalog = load()
        card(catalog, 'EX1_617')['abilities'][0]['effects'][0]['recipient']['selector'][
            'entityKind'
        ] = 'CHARACTER'
        assert_invalid(self, catalog, 'EX1_617: destroy requires minion recipients')

    def test_excessive_nested_effects_fail_before_recursive_schema_validation(self):
        catalog = load()
        effect = nested_choice()
        for _ in range(10):
            effect = dict(
                op='CHOOSE_ONE',
                options=[
                    dict(id='option-0', label='Nested', effects=[effect]),
                    dict(id='option-1', label='Simple', effects=[damage()]),
                ],
            )
        card(catalog, 'EX1_154')['abilities'][0]['effects'] = [effect]
        assert_invalid(self, catalog, 'effect nesting exceeds eight levels')

    def test_budgets_are_positive_integers(self):
        for field in ('max_choices', 'max_random_steps'):
            for value in (0, -1, True, 1.5):
                with self.assertRaisesRegex(ValueError, field):
                    MatchEngine(**{field: value})


class RandomEffectTests(ZoneFixture):
    def test_arcane_missiles_bonus_adds_hits_not_damage_per_hit(self):
        self.add('CS2_142', 'kobold')
        self.play('EX1_277')
        hits = self.events('DAMAGE')
        self.assertEqual(len(hits), 4)
        self.assertEqual([hit['amount'] for hit in hits], [1] * 4)
        self.assertEqual(self.get('hero-1')['damage'], 4)
        self.assertEqual(self.get('kobold')['damage'], 0)

    def test_mad_bomber_excludes_self_and_ignores_spell_damage(self):
        self.add('CS2_142', 'kobold')
        self.play('EX1_082', eid='bomber')
        hits = self.events('DAMAGE')
        self.assertEqual(len(hits), 3)
        self.assertEqual(sum(hit['amount'] for hit in hits), 3)
        self.assertNotIn('bomber', [hit['target'] for hit in hits])
        self.assertEqual(self.get('bomber')['damage'], 0)

    def test_each_hit_retargets_after_deaths_and_token_summons(self):
        self.add('FP1_002', 'creeper', 1, damage=1)
        with patch('hearthstone.rng.randbelow', side_effect=[1, 1, 1]):
            self.play('EX1_277')
        hits = self.events('DAMAGE')
        self.assertEqual(hits[0]['target'], 'creeper')
        self.assertEqual(len({hit['target'] for hit in hits}), 3)
        kinds = [event['type'] for event in self.state['events']]
        self.assertLess(
            kinds.index('DEATH_BATCH'), kinds.index('DAMAGE', kinds.index('DAMAGE') + 1)
        )
        self.assertEqual(self.ids(1), [])

    def test_random_destroy_ignores_selected_target_restrictions(self):
        self.add(eid='stealth', player=1, keywords=['STEALTH', 'ELUSIVE'])
        self.play('EX1_617')
        self.assertEqual(self.get('stealth')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get('hero-1')['damage'], 0)

    def test_empty_random_target_set_spends_cost_without_rng(self):
        before = deepcopy(self.state['rng'])
        self.play('EX1_617')
        self.assertEqual(self.state['rng'], before)
        self.assertEqual(self.state['mana'][0], 7)
        self.assertEqual(self.events('DESTROY'), [])

    def test_random_damage_shield_and_immunity_use_common_pipeline(self):
        self.get('hero-1')['keywords'] = ['IMMUNE']
        self.add(eid='shield', player=1, keywords=['DIVINE_SHIELD'])
        with patch('hearthstone.rng.randbelow', side_effect=[1, 0, 1]):
            self.play('EX1_277')
        self.assertEqual([hit['amount'] for hit in self.events('DAMAGE')], [0, 0, 1])
        self.assertNotIn('DIVINE_SHIELD', self.get('shield')['keywords'])
        self.assertEqual(self.get('hero-1')['damage'], 0)

    def test_seeded_book_outcome_is_repeatable_and_catalog_order_independent(self):
        self.add('KAR_009', 'book', zone='HAND')
        other = deepcopy(self.catalog)
        other['cards'].reverse()
        first = self.engine.play(self.state, 0, 'book')
        second = MatchEngine(other).play(json.loads(json.dumps(self.state)), 0, 'book')
        self.assertEqual(first, second)
        generated = next(e for e in first['entities'] if e.get('createdBy') == 'book')
        self.assertEqual(self.engine.definition(generated)['classes'], ['MAGE'])
        self.assertEqual(generated['kind'], 'SPELL')
        self.assertEqual(generated['privateTo'], 0)

    def test_seed_changes_random_outcomes(self):
        outcomes = set()
        for seed in range(8):
            state = deepcopy(self.state)
            state['rng'] = rng.new(seed)
            state['entities'].append(self.engine.entity('book', 'KAR_009', 0, 'HAND'))
            result = self.engine.play(state, 0, 'book')
            outcomes.add(
                next(
                    e['cardId']
                    for e in result['entities']
                    if e.get('createdBy') == 'book'
                )
            )
        self.assertGreater(len(outcomes), 1)

    def test_random_budget_failure_is_atomic(self):
        engine = MatchEngine(self.catalog, max_random_steps=2)
        self.add('EX1_277', 'missiles', zone='HAND')
        before = deepcopy(self.state)
        with self.assertRaisesRegex(ResolutionLimitError, 'random'):
            engine.play(self.state, 0, 'missiles')
        self.assertEqual(self.state, before)

    def test_countered_random_spell_consumes_no_rng(self):
        self.add('EX1_287', 'counter', 1, 'SECRET')
        before = deepcopy(self.state['rng'])
        self.play('EX1_277')
        self.assertEqual(before, self.state['rng'])
        self.assertEqual(self.events('DAMAGE'), [])


class ChoiceTests(ZoneFixture):
    def choose(self, index=0, state=None, player=0):
        state = self.state if state is None else state
        request = state['pendingChoice']
        return self.engine.choose(
            state, player, request['id'], request['options'][index]['id']
        )

    def test_discover_pauses_on_a_committed_board_then_commits_once(self):
        self.add('UNG_072', 'stone', zone='HAND')
        original = deepcopy(self.state)
        self.state = self.engine.play(self.state, 0, 'stone')
        self.assertEqual(self.state['phase'], 'CHOICE')
        for key in ('mana', 'resources', 'rng', 'entities', 'events'):
            self.assertEqual(self.state[key], original[key])
        check_invariants(self.engine, self.state)
        request = self.state['pendingChoice']
        self.assertEqual(request['kind'], 'DISCOVER')
        refs = [option['definition'] for option in request['options']]
        self.assertEqual(len(refs), 3)
        self.assertEqual(len({json.dumps(ref, sort_keys=True) for ref in refs}), 3)
        for ref in refs:
            self.assertIn(
                'TAUNT', self.engine.cards[(ref['cardId'], ref['revision'])]['keywords']
            )
        self.state = self.choose()
        self.assertEqual(self.state['phase'], 'MAIN')
        self.assertEqual(self.state['mana'][0], 7)
        self.assertEqual(self.get('stone')['zone'], 'PLAY')
        self.assertEqual(len(self.events('PLAY')), 1)
        self.assertEqual(len(self.events('GENERATED')), 1)
        self.assertNotIn('continuation', self.state)
        self.assertNotIn('_choiceTransaction', self.state)

    def test_checkpoint_resume_and_branching_are_deterministic(self):
        self.play('UNG_072', eid='stone')
        saved = json.loads(json.dumps(self.state))
        first = self.choose()
        self.assertEqual(first, self.choose(state=saved))
        alternate = self.choose(index=1, state=saved)
        first_card = next(e for e in first['entities'] if e.get('createdBy') == 'stone')
        other_card = next(
            e for e in alternate['entities'] if e.get('createdBy') == 'stone'
        )
        self.assertNotEqual(first_card['cardId'], other_card['cardId'])
        self.assertEqual(first['rng'], alternate['rng'])
        self.assertEqual(self.state, saved)

    def test_only_chooser_has_choose_actions_both_can_concede(self):
        self.play('UNG_072')
        own = self.engine.legal_actions(self.state, 0)
        self.assertEqual([a['type'] for a in own], ['choose'] * 3 + ['concede'])
        self.assertEqual(
            self.engine.legal_actions(self.state, 1), [{'type': 'concede'}]
        )
        for action in own:
            result = self.engine.apply(self.state, 0, action)
            check_invariants(self.engine, result)
        for player in (0, 1):
            result = self.engine.concede(self.state, player)
            self.assertNotIn('pendingChoice', result)
            self.assertNotIn('continuation', result)
            self.assertEqual(self.engine.legal_actions(result, player), [])

    def test_invalid_choices_and_interleaved_actions_are_atomic(self):
        self.play('UNG_072')
        request = self.state['pendingChoice']
        for player, cid, oid in [
            (1, request['id'], 'option-0'),
            (0, 'stale', 'option-0'),
            (0, request['id'], 'missing'),
            (0, request['id'], True),
        ]:
            before = deepcopy(self.state)
            with self.assertRaises(ValueError):
                self.engine.choose(self.state, player, cid, oid)
            self.assertEqual(self.state, before)
        for action in [
            dict(type='end_turn'),
            dict(type='hero_power', target='hero-1'),
            dict(type='play', source='stone'),
            dict(type='attack', attacker='hero-0', defender='hero-1'),
        ]:
            self.failure(lambda: self.engine.apply(self.state, 0, action))

    def test_wrath_branches_use_shared_target_and_spell_damage(self):
        self.add(eid='enemy', player=1)
        self.add('CS2_142', 'kobold')
        self.play('EX1_154', 'enemy')
        pending = deepcopy(self.state)
        first = self.choose(index=0)
        self.assertEqual(self.get('enemy', first)['damage'], 4)
        original_deck = len(pending['decks'][0])
        second = self.choose(index=1, state=pending)
        self.assertEqual(self.get('enemy', second)['damage'], 2)
        self.assertEqual(len(second['decks'][0]), original_deck - 1)
        self.assertEqual(second['mana'][0], 8)

    def test_counterspell_skips_choose_one_without_a_prompt(self):
        self.add(eid='enemy', player=1)
        self.add('EX1_287', 'counter', 1, 'SECRET')
        self.play('EX1_154', 'enemy')
        self.assertEqual(self.state['phase'], 'MAIN')
        self.assertNotIn('pendingChoice', self.state)
        self.assertEqual(self.get('enemy')['damage'], 0)
        self.assertEqual(self.state['mana'][0], 8)

    def test_nested_choices_use_unique_ids_and_resume_remaining_effects(self):
        stone = card(self.catalog, 'UNG_072')
        stone['mechanics'] = ['BATTLECRY', 'CHOOSE_ONE']
        outer = nested_choice()
        outer['options'][0]['effects'] = [nested_choice(), damage(3)]
        stone['abilities'][0]['effects'] = [outer, damage(4)]
        self.restart()
        self.play('UNG_072', eid='stone')
        first_id = self.state['pendingChoice']['id']
        self.state = self.choose()
        self.assertNotEqual(first_id, self.state['pendingChoice']['id'])
        self.assertEqual(self.get('hero-0')['damage'], 0)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.engine.choose(self.state, 0, first_id, 'option-0')
        self.state = self.choose(index=1)
        self.assertEqual(self.get('hero-0')['damage'], 9)
        self.assertEqual(len(self.events('CHOICE_RESOLVED')), 2)
        self.assertEqual(len(self.events('PLAY')), 1)
        self.assertEqual(self.state['nextChoiceId'], 3)

    def test_choice_budget_and_tampered_checkpoint_fail_atomically(self):
        stone = card(self.catalog, 'UNG_072')
        stone['mechanics'] = ['BATTLECRY', 'CHOOSE_ONE']
        outer = nested_choice()
        outer['options'][0]['effects'] = [nested_choice()]
        stone['abilities'][0]['effects'] = [outer]
        self.restart()
        self.engine = MatchEngine(self.catalog, max_choices=1)
        self.play('UNG_072')
        self.failure(lambda: self.choose(), ResolutionLimitError)
        self.state['pendingChoice']['options'][1]['label'] = 'Tampered'
        self.failure(lambda: self.choose(index=1))

    def test_empty_and_small_discover_pools(self):
        for cost, expected in [(99, 0), (1, 1)]:
            card(self.catalog, 'UNG_072')['abilities'][0]['effects'][0]['pool'][
                'manaCost'
            ] = cost
            self.restart()
            before_rng = deepcopy(self.state['rng'])
            self.play('UNG_072')
            if expected:
                self.assertEqual(len(self.state['pendingChoice']['options']), expected)
                self.state = self.choose()
            else:
                self.assertEqual(self.state['phase'], 'MAIN')
                self.assertEqual(self.state['rng'], before_rng)
                self.assertEqual(self.events('GENERATED'), [])


class PrivateGenerationTests(ZoneFixture):
    def single_book_spell(self, count=1):
        effect = card(self.catalog, 'KAR_009')['abilities'][0]['effects'][0]
        effect['pool'][
            'manaCost'
        ] = 7  # Flamestrike is the only current 7-mana Mage spell.
        card(self.catalog, 'KAR_009')['abilities'][0]['effects'] = [
            deepcopy(effect) for _ in range(count)
        ]
        self.restart()

    def test_random_card_is_hidden_until_public_play(self):
        self.single_book_spell()
        self.play('KAR_009', eid='book')
        entity = next(e for e in self.state['entities'] if e.get('createdBy') == 'book')
        self.assertIn(entity['id'], json.dumps(self.engine.view(self.state, 0)))
        hidden = json.dumps(self.engine.view(self.state, 1))
        self.assertNotIn(entity['id'], hidden)
        self.assertNotIn('CS2_032', hidden)
        self.state = self.engine.play(self.state, 0, entity['id'])
        public = json.dumps(self.engine.view(self.state, 1))
        self.assertIn(entity['id'], public)
        self.assertIn('CS2_032', public)
        private_events = [
            e
            for e in self.engine.view(self.state, 1)['events']
            if e['type'] == 'GENERATED'
        ]
        self.assertEqual(private_events, [dict(type='GENERATED', player=0)])

    def test_full_hand_private_generation_does_not_reveal_discarded_identity(self):
        self.single_book_spell(count=2)
        self.add('KAR_009', 'book', zone='HAND')
        self.fill_hand(0)
        self.state = self.engine.play(self.state, 0, 'book')
        generated = [e for e in self.state['entities'] if e.get('createdBy') == 'book']
        self.assertEqual([e['zone'] for e in generated], ['HAND', 'GRAVEYARD'])
        opponent = json.dumps(self.engine.view(self.state, 1))
        for entity in generated:
            self.assertNotIn(entity['id'], opponent)
        self.assertNotIn('CS2_032', opponent)
        self.assertEqual(len(self.events('DISCARD')), 1)
        check_invariants(self.engine, self.state)

    def test_discover_offers_and_continuation_are_private(self):
        self.play('UNG_072', eid='stone')
        own = self.engine.view(self.state, 0)
        other = self.engine.view(self.state, 1)
        self.assertEqual(len(own['choice']['options']), 3)
        self.assertEqual(other['choice'], dict(player=0, kind='DISCOVER'))
        for key in (
            'continuation',
            'pendingChoice',
            'requestHash',
            'effects',
            'rng',
            'nextChoiceId',
        ):
            self.assertNotIn(key, json.dumps(other))
        for option in own['choice']['options']:
            self.assertNotIn(option['definition']['cardId'], json.dumps(other))
        before = deepcopy(self.state)
        own['choice']['options'][0]['definition']['cardId'] = 'MODIFIED'
        self.assertEqual(before, self.state)

    def test_pending_offer_identity_changes_do_not_change_opponent_view(self):
        self.play('UNG_072')
        other = deepcopy(self.state)
        for index, option in enumerate(other['pendingChoice']['options']):
            option['id'] = f'PRIVATE-{index}'
            option['definition'] = dict(
                cardId='PRIVATE_CARD', revision='PRIVATE_REVISION'
            )
        other['pendingChoice']['id'] = 'PRIVATE_REQUEST'
        other['continuation']['action']['source'] = 'PRIVATE_SOURCE'
        self.assertEqual(self.engine.view(self.state, 1), self.engine.view(other, 1))

    def test_generated_secret_stays_hidden_and_becomes_public_when_triggered(self):
        effect = card(self.catalog, 'KAR_009')['abilities'][0]['effects'][0]
        # Add a minion-free pool discriminator through an exact cost and class;
        # choose a deterministic seed which generates Counterspell.
        self.restart()
        for seed in range(30):
            original = deepcopy(self.state)
            original['rng'] = rng.new(seed)
            original['entities'].append(
                self.engine.entity('book', 'KAR_009', 0, 'HAND')
            )
            result = self.engine.play(original, 0, 'book')
            secret = next(e for e in result['entities'] if e.get('createdBy') == 'book')
            if secret['cardId'] == 'EX1_287':
                break
        else:
            self.fail('fixed seed sample must contain Counterspell')
        self.state = self.engine.play(result, 0, secret['id'])
        self.assertNotIn(secret['id'], json.dumps(self.engine.view(self.state, 1)))
        self.end()
        self.refill()
        self.play('GAME_005')
        self.assertEqual(self.get(secret['id'])['zone'], 'GRAVEYARD')
        public = json.dumps(self.engine.view(self.state, 1))
        self.assertIn(secret['id'], public)
        self.assertIn('EX1_287', public)

    def test_full_hand_discover_discard_remains_private(self):
        stone = card(self.catalog, 'UNG_072')
        stone['abilities'][0]['effects'].insert(
            0, dict(op='DRAW_CARD', count=1, targetPlayer='EFFECT_CONTROLLER')
        )
        self.restart()
        self.add('UNG_072', 'stone', zone='HAND')
        self.fill_hand(0)
        self.state = self.engine.play(self.state, 0, 'stone')
        request = self.state['pendingChoice']
        self.state = self.engine.choose(
            self.state, 0, request['id'], request['options'][0]['id']
        )
        generated = next(
            e for e in self.state['entities'] if e.get('createdBy') == 'stone'
        )
        self.assertEqual(generated['zone'], 'GRAVEYARD')
        self.assertNotIn(generated['id'], json.dumps(self.engine.view(self.state, 1)))
        self.assertEqual(len(self.events('DISCARD')), 1)
        self.assertEqual(self.events('BURN'), [])


class SchedulerChoiceTests(ZoneFixture):
    def resolve(self, index=0):
        request = self.state['pendingChoice']
        self.state = self.engine.choose(
            self.state,
            request['player'],
            request['id'],
            request['options'][index]['id'],
        )

    def test_opponent_listener_can_pause_original_players_action(self):
        cult = card(self.catalog, 'EX1_595')
        cult['mechanics'] = ['CHOOSE_ONE']
        cult['abilities'][0]['effects'] = [nested_choice()]
        self.restart()
        self.add('EX1_595', 'cult', 1)
        self.add('EX1_015', 'victim', 1)
        self.play('CS2_029', 'victim')
        self.assertEqual(self.state['activePlayer'], 0)
        self.assertEqual(self.state['pendingChoice']['player'], 1)
        self.assertEqual(
            self.engine.legal_actions(self.state, 0), [{'type': 'concede'}]
        )
        check_invariants(self.engine, self.state)
        self.resolve(index=1)
        self.assertEqual(self.get('victim')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get('hero-1')['damage'], 2)
        self.assertEqual(self.state['mana'][0], 6)
        self.assertEqual(self.state['mana'][1], 10)
        self.assertEqual(len(self.events('PLAY')), 1)
        self.assertEqual(len(self.events('REACTION')), 1)

    def test_deathrattle_choice_resumes_following_effect_once(self):
        loot = card(self.catalog, 'EX1_096')
        loot['mechanics'].append('CHOOSE_ONE')
        loot['abilities'][0]['effects'].insert(0, nested_choice())
        self.restart()
        self.add('EX1_096', 'loot')
        deck_count = len(self.state['decks'][0])
        self.state = self.engine.hero_power(self.state, 0, 'loot')
        self.assertEqual(self.state['phase'], 'CHOICE')
        check_invariants(self.engine, self.state)
        self.resolve()
        self.assertEqual(self.get('loot')['zone'], 'GRAVEYARD')
        self.assertEqual(len(self.state['decks'][0]), deck_count - 1)
        self.assertEqual(self.state['heroPowerUsesThisTurn'][0], 1)
        self.assertEqual(len(self.events('DEATHRATTLE')), 1)
        self.assertEqual(self.get('hero-0')['damage'], 1)

    def test_start_of_turn_choice_resumes_handover_and_draw(self):
        yeti = card(self.catalog, 'CS2_182')
        yeti['mechanics'] = ['CHOOSE_ONE']
        yeti['abilities'] = [dict(kind='START_OF_TURN', effects=[nested_choice()])]
        self.restart()
        self.add(eid='trigger', player=1)
        before = len(self.state['decks'][1])
        self.end()
        self.assertEqual(self.state['pendingChoice']['player'], 1)
        self.assertEqual(self.state['activePlayer'], 0)
        self.resolve()
        self.assertEqual(self.state['activePlayer'], 1)
        self.assertEqual(self.state['phase'], 'MAIN')
        self.assertEqual(len(self.state['decks'][1]), before - 1)
        self.assertEqual(self.get('hero-1')['damage'], 1)


class CompleteStage10GameTests(unittest.TestCase):
    def test_complete_demo_replays_through_choice_checkpoints(self):
        import random
        from examples.play_random_choices import run

        final, actions = run(8)
        engine = MatchEngine()
        driver = random.Random(8)
        pool = sorted(c['cardId'] for c in engine.cards.values() if c['collectible'])
        decks = [[driver.choice(pool) for _ in range(16)] for _ in (0, 1)]
        state = engine.new_game(
            decks, 8, deck_size=16, turn_limit=50, hero_powers=['CS2_034', 'CS1h_001']
        )
        pauses = 0
        for entry in actions:
            if state['phase'] == 'CHOICE':
                pauses += 1
            state = engine.apply(
                json.loads(json.dumps(state)), entry['player'], entry['action']
            )
            check_invariants(engine, state)
        self.assertEqual(state, final)
        self.assertGreater(pauses, 0)
        self.assertEqual(
            {e['choice'] for e in final['events'] if e['type'] == 'CHOICE_RESOLVED'},
            {'DISCOVER', 'CHOOSE_ONE'},
        )
        self.assertEqual(final['result'], 'PLAYER_0_WINS')
