from fixtures import assert_invalid, invalid_field
from fixtures import spell_bonus

"""Stage 9: snapshotted reaction queues and automatic interruption windows."""
from copy import deepcopy
import json
import unittest
from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.match import MatchEngine
from hearthstone.prototype import ResolutionLimitError
from test_zones import ZoneFixture, card


def query(op, **kw):
    return dict(
        op=op,
        recipient=dict(
            kind='QUERY',
            capture='EFFECT_START',
            selector=dict(zone='PLAY', entityKind='MINION', controller='FRIENDLY'),
        ),
        missingRecipient='SKIP',
        **kw,
    )


class ReactionCatalogTests(unittest.TestCase):

    def test_listener_conditions_are_strict(self):
        for key, value in [
            ('event', 'UNKNOWN'),
            ('relation', 'OWNER'),
            ('subjectKind', 'LOCATION'),
            ('actorKind', 'SPELL'),
            ('excludeSelf', 1),
            ('extra', 1),
        ]:
            catalog = load()
            card(catalog, 'EX1_007')['abilities'][0]['trigger'][key] = value
            assert_invalid(
                self,
                catalog,
                (
                    ('extra', 'Additional properties')
                    if key == 'extra'
                    else (
                        (key, "1 is not of type 'boolean'")
                        if key == 'excludeSelf'
                        else (key, f"'{value}' is not one of")
                    )
                ),
            )

    def test_event_amount_requires_damage_or_heal(self):
        catalog = load()
        card(catalog, 'EX1_044')['abilities'][0]['effects'][0] = deepcopy(
            card(catalog, 'EX1_132')['abilities'][0]['effects'][0]
        )
        assert_invalid(
            self, catalog, 'EX1_044: event amount requires a damage/heal listener'
        )

    def test_event_recipients_require_matching_context(self):
        for recipient in ('ATTACKER', 'DEFENDER', 'EVENT_TARGET'):
            catalog = load()
            card(catalog, 'CS2_029')['abilities'][0]['effects'][0]['recipient'] = {
                'kind': recipient
            }
            assert_invalid(
                self, catalog, 'CS2_029: event recipient requires a listener'
            )

    def test_counter_and_redirect_are_interrupt_only(self):
        for cid in ('EX1_287', 'EX1_130'):
            catalog = load()
            card(catalog, cid)['abilities'][0]['trigger']['event'] = 'HEAL'
            assert_invalid(
                self,
                catalog,
                (
                    f'{cid}: counter requires a before-spell Secret'
                    if cid == 'EX1_287'
                    else f'{cid}: redirect requires a before-attack Secret'
                ),
            )
        catalog = load()
        card(catalog, 'EX1_130')['abilities'][0]['effects'][0]['definition'][
            'revision'
        ] = 'unknown'
        assert_invalid(
            self, catalog, 'EX1_130: redirect requires a resolved minion definition'
        )

    def test_secret_metadata_and_weapon_abilities_are_checked(self):
        catalog = load()
        card(catalog, 'EX1_287')['mechanics'] = []
        assert_invalid(self, catalog, 'EX1_287: SECRET label and ability disagree')
        catalog = load()
        card(catalog, 'CS2_097')['abilities'][0]['kind'] = 'BATTLECRY'
        del card(catalog, 'CS2_097')['abilities'][0]['trigger']
        assert_invalid(self, catalog, 'CS2_097: incompatible ability kind')
        catalog = load()
        card(catalog, 'NEW1_020')['abilities'][0]['effects'][0]['damageClass'] = 'SPELL'
        assert_invalid(self, catalog, 'NEW1_020: incompatible damage class')

    def test_unknown_reaction_policy_rejected(self):

        catalog = load()
        catalog['reactionPolicy'] = 'UNKNOWN'
        assert_invalid(
            self,
            catalog,
            ("'reactionPolicy'", "'DEPTH_FIRST_REACTIONS_DEATH_WAVES_V1' was expected"),
        )

    def test_invalid_budgets(self):
        for value in (0, -1, True, 0.5):
            with self.assertRaises(ValueError):
                MatchEngine(max_reactions=value)


class ReactionFixture(ZoneFixture):
    def restart(self, powers=None, budget=1000, limit=1000):
        super().restart(powers, budget)
        self.engine = MatchEngine(
            self.catalog, max_reactions=limit, max_deathrattles=budget
        )
        self.state['events'] = []

    def secret(self, cid, eid='secret', player=1):
        return self.add(cid, eid, player, 'SECRET')

    def reaction_sources(self):
        return [e['source'] for e in self.events('REACTION')]


class ListenerTests(ReactionFixture):
    def test_acolyte_draws_on_damage_even_lethal_before_death(self):
        self.add('EX1_007', 'pain', 1)
        before = len(self.state['decks'][1])
        self.play('CS2_029', 'pain')
        self.assertEqual(len(self.state['decks'][1]), before - 1)
        self.assertEqual(self.get('pain')['zone'], 'GRAVEYARD')
        kinds = [e['type'] for e in self.state['events']]
        self.assertLess(kinds.index('DRAW'), kinds.index('DEATH_BATCH'))

    def test_zero_shielded_and_immune_damage_do_not_trigger(self):
        for keywords in (['IMMUNE'], ['DIVINE_SHIELD']):
            self.restart()
            self.add('EX1_007', 'pain', keywords=keywords)
            self.play('CS2_024', 'pain')
            self.assertEqual(self.reaction_sources(), [])

    def test_hero_power_damage_uses_same_listener_pipeline(self):
        self.add('EX1_007', 'pain', 1)
        before = len(self.state['decks'][1])
        self.state = self.engine.hero_power(self.state, 0, 'pain')
        self.assertEqual(len(self.state['decks'][1]), before - 1)
        self.assertEqual(self.get('pain')['damage'], 1)

    def test_cleric_counts_real_minion_heals_only(self):
        self.add('CS2_235', 'cleric')
        self.add(eid='yeti', damage=2)
        self.play('EX1_011', 'yeti', 'doctor')
        self.assertEqual(self.reaction_sources(), ['cleric'])
        self.refill()
        self.play('EX1_011', 'yeti', 'doctor2')
        self.get('hero-0')['damage'] = 3
        self.play('EX1_011', 'hero-0', 'doctor3')
        self.assertEqual(self.reaction_sources(), ['cleric'])

    def test_questing_play_trigger_precedes_battlecry_and_does_not_count_itself(self):
        self.play('EX1_044', eid='quest')
        self.assertEqual(self.engine.current_attack(self.state, self.get('quest')), 2)
        self.play('EX1_015', eid='novice')
        self.assertEqual(self.engine.current_attack(self.state, self.get('quest')), 3)
        kinds = [e['type'] for e in self.state['events']]
        self.assertLess(kinds.index('BUFF'), kinds.index('DRAW'))

    def test_councilman_counts_generated_minions_not_own_arrival(self):
        self.play('OG_113', eid='council')
        self.play('CS2_027')
        self.assertEqual(self.engine.current_attack(self.state, self.get('council')), 3)
        self.assertEqual(self.reaction_sources(), ['council', 'council'])

    def test_pyromancer_is_after_spell_and_ability_damage(self):
        self.add('NEW1_020', 'pyro')
        self.add(eid='yeti')
        spell_bonus(self.engine, self.state, 0, 3)
        self.play('GAME_005')
        self.assertEqual(self.get('yeti')['damage'], 1)
        self.assertEqual(self.get('pyro')['damage'], 1)
        self.assertEqual(self.reaction_sources(), ['pyro'])

    def test_countered_spell_has_no_after_spell_trigger(self):
        self.add('NEW1_020', 'pyro')
        self.secret('EX1_287')
        self.play('GAME_005')
        self.assertNotIn('pyro', self.reaction_sources())
        self.assertEqual(self.get('pyro')['damage'], 0)

    def test_nested_reactions_complete_before_next_parent_listener(self):
        card(self.catalog, 'EX1_044')['abilities'][0]['effects'] = [
            query('HEAL', amount={'kind': 'CONSTANT', 'value': 1})
        ]
        council = card(self.catalog, 'OG_113')['abilities'][0]
        council['trigger'] = deepcopy(
            card(self.catalog, 'EX1_044')['abilities'][0]['trigger']
        )
        self.restart()
        self.add('EX1_044', 'a', playOrder=1)
        self.add('OG_113', 'b', playOrder=2)
        self.add('CS2_235', 'nested', playOrder=3)
        self.add(eid='wounded', damage=1)
        self.play('GAME_005')
        self.assertEqual(self.reaction_sources(), ['a', 'nested', 'b'])

    def test_queued_listener_is_revalidated_after_silence(self):
        card(self.catalog, 'EX1_044')['abilities'][0]['effects'] = [query('SILENCE')]
        self.restart()
        self.add('EX1_044', 'a', playOrder=1)
        self.add('EX1_044', 'b', playOrder=2)
        self.play('GAME_005')
        self.assertEqual(self.reaction_sources(), ['a'])
        self.assertTrue(self.get('b')['silenced'])

    def test_queued_listener_is_revalidated_after_bounce(self):
        card(self.catalog, 'EX1_044')['abilities'][0]['effects'] = [
            query('RETURN_TO_HAND', targetPlayer='RECIPIENT_CONTROLLER')
        ]
        self.restart()
        self.add('EX1_044', 'a', playOrder=1)
        self.add('EX1_044', 'b', playOrder=2)
        self.play('GAME_005')
        self.assertEqual(self.reaction_sources(), ['a'])
        self.assertEqual(self.get('b')['zone'], 'HAND')

    def test_new_listener_does_not_join_an_existing_event(self):
        card(self.catalog, 'EX1_044')['abilities'][0]['effects'] = [
            dict(
                op='SUMMON',
                definition=dict(cardId='EX1_044', revision='foundation-v9'),
                count=1,
                placement='RIGHT_END',
                targetPlayer='EFFECT_CONTROLLER',
            )
        ]
        self.restart()
        self.add('EX1_044', 'old')
        self.play('GAME_005')
        self.assertEqual(self.reaction_sources(), ['old'])
        self.assertEqual(len(self.ids()), 2)

    def test_after_card_play_uses_preexisting_listener_barrier(self):
        q = card(self.catalog, 'EX1_044')['abilities'][0]
        q['trigger']['event'] = 'AFTER_CARD_PLAY'
        self.restart()
        self.play('EX1_044', eid='new')
        self.assertEqual(self.reaction_sources(), [])
        self.play('GAME_005')
        self.assertEqual(self.reaction_sources(), ['new'])

    def test_cult_master_and_deathrattle_share_chronology(self):
        for cult_order, loot_order, expected in [
            (1, 2, ['cult', 'loot']),
            (2, 1, ['loot', 'cult']),
        ]:
            self.restart()
            self.add('EX1_595', 'cult', playOrder=cult_order)
            self.add('EX1_096', 'loot', playOrder=loot_order)
            self.play('CS2_029', 'loot')
            self.assertEqual(self.reaction_sources(), expected)

    def test_cult_master_dying_in_same_batch_cannot_observe(self):
        self.add('EX1_595', 'cult', 1)
        self.add('EX1_096', 'loot', 1)
        self.play('CS2_032')
        self.assertEqual(self.reaction_sources(), ['loot'])

    def test_damage_batch_applies_all_hits_before_reactions(self):
        self.add('EX1_007', 'a', 1)
        self.add('EX1_007', 'b', 1)
        self.play('CS2_032')
        types = [e['type'] for e in self.state['events']]
        damages = [i for i, t in enumerate(types) if t == 'DAMAGE']
        self.assertLess(max(damages), types.index('REACTION'))
        self.assertEqual(self.reaction_sources(), ['a', 'b'])


class SecretTests(ReactionFixture):
    def test_counterspell_pays_and_discards_without_text_or_overload(self):
        self.secret('EX1_287')
        self.play('EX1_238', 'hero-1', 'bolt')
        self.assertEqual(self.get('bolt')['zone'], 'GRAVEYARD')
        self.assertEqual(self.state['mana'][0], 9)
        self.assertEqual(self.state['cardsPlayedThisTurn'][0], 1)
        self.assertEqual(self.state['resources'][0]['pendingOverload'], 0)
        self.assertEqual(self.events('OVERLOAD'), [])
        self.assertEqual(self.get('hero-1')['damage'], 0)
        self.assertEqual(self.get('secret')['zone'], 'GRAVEYARD')

    def test_secret_can_be_played_and_only_triggers_off_turn(self):
        self.play('EX1_287', eid='counter')
        self.play('GAME_005')
        self.assertEqual(self.get('counter')['zone'], 'SECRET')
        self.end()
        self.refill()
        self.play('GAME_005', eid='enemycoin')
        self.assertEqual(self.get('counter')['zone'], 'GRAVEYARD')

    def test_duplicate_secret_is_rejected_atomically(self):
        self.secret('EX1_287', player=0)
        self.add('EX1_287', 'duplicate', zone='HAND')
        self.failure(lambda: self.engine.play(self.state, 0, 'duplicate'))

    def test_five_secret_slots_and_no_minion_board_slots_used(self):
        for i, cid in enumerate(
            ('EX1_287', 'EX1_594', 'EX1_610', 'EX1_130', 'EX1_132')
        ):
            self.secret(cid, f's{i}', 0)
        self.assertEqual(self.ids(), [])
        extra = deepcopy(card(self.catalog, 'EX1_287'))
        extra['cardId'] = 'TEST_COUNTER'
        self.catalog['cards'].append(extra)
        self.engine = MatchEngine(self.catalog)
        self.add('TEST_COUNTER', 'extra', zone='HAND')
        self.failure(lambda: self.engine.play(self.state, 0, 'extra'))

    def test_counterspell_ignores_minions_and_hero_powers(self):
        self.secret('EX1_287')
        self.play('CS2_182')
        self.state = self.engine.hero_power(self.state, 0, 'hero-1')
        self.assertEqual(self.get('secret')['zone'], 'SECRET')

    def test_second_counter_stays_when_first_has_already_countered(self):
        alt = deepcopy(card(self.catalog, 'EX1_287'))
        alt['cardId'] = 'TEST_COUNTER'
        self.catalog['cards'].append(alt)
        self.restart()
        self.secret('EX1_287', 'first')
        self.secret('TEST_COUNTER', 'second')
        self.play('GAME_005')
        self.assertEqual(self.get('first')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get('second')['zone'], 'SECRET')

    def test_vaporize_cancels_attack_without_hero_damage(self):
        self.secret('EX1_594')
        self.add('CS2_124', 'wolf')
        self.state = self.engine.attack(self.state, 0, 'wolf', 'hero-1')
        self.assertEqual(self.get('wolf')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get('hero-1')['damage'], 0)
        self.assertEqual(self.get('wolf')['attacksThisTurn'], 0)
        self.assertEqual(len(self.events('ATTACK_CANCELLED')), 1)

    def test_vaporize_does_not_trigger_on_a_hero_attacker(self):
        self.secret('EX1_594')
        self.play('CS2_106')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get('secret')['zone'], 'SECRET')
        self.assertEqual(self.get('hero-1')['damage'], 3)

    def test_explosive_trap_kills_attacker_before_combat(self):
        self.secret('EX1_610')
        self.add('CS2_124', 'wolf')
        self.state = self.engine.attack(self.state, 0, 'wolf', 'hero-1')
        self.assertEqual(self.get('hero-0')['damage'], 2)
        self.assertEqual(self.get('hero-1')['damage'], 0)
        self.assertEqual(self.events('ATTACK'), [])

    def test_noble_sacrifice_redirects_and_counterdamages(self):
        self.secret('EX1_130')
        self.add(eid='yeti', ready=True)
        self.state = self.engine.attack(self.state, 0, 'yeti', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 0)
        self.assertEqual(self.get('yeti')['damage'], 2)
        defender = self.events('ATTACK_REDIRECTED')[0]['after']
        self.assertEqual(self.get(defender)['cardId'], 'EX1_130a')
        self.assertEqual(self.get(defender)['zone'], 'GRAVEYARD')
        self.assertEqual(self.get('yeti')['attacksThisTurn'], 1)

    def test_noble_stays_hidden_with_no_room(self):
        self.secret('EX1_130')
        for i in range(7):
            self.add(player=1)
        self.add(eid='yeti', ready=True)
        self.state = self.engine.attack(self.state, 0, 'yeti', 'hero-1')
        self.assertEqual(self.get('secret')['zone'], 'SECRET')
        self.assertEqual(self.get('hero-1')['damage'], 4)

    def test_redirect_rechecks_later_hero_attack_secrets(self):
        self.secret('EX1_130', 'noble')
        self.secret('EX1_594', 'vapor')
        self.add(eid='yeti', ready=True)
        self.state = self.engine.attack(self.state, 0, 'yeti', 'hero-1')
        self.assertEqual(self.get('vapor')['zone'], 'SECRET')
        self.assertEqual(self.get('yeti')['zone'], 'PLAY')

    def test_targetless_secret_still_resolves_after_attacker_destroyed(self):
        self.secret('EX1_594', 'vapor')
        self.secret('EX1_610', 'explosive')
        self.add('CS2_124', 'wolf')
        self.state = self.engine.attack(self.state, 0, 'wolf', 'hero-1')
        self.assertEqual(self.reaction_sources(), ['vapor', 'explosive'])
        self.assertEqual(self.get('hero-0')['damage'], 2)

    def test_later_targeted_secret_skips_mortally_wounded_attacker(self):
        self.secret('EX1_610', 'explosive')
        self.secret('EX1_594', 'vapor')
        self.add('CS2_124', 'wolf')
        self.state = self.engine.attack(self.state, 0, 'wolf', 'hero-1')
        self.assertEqual(self.get('vapor')['zone'], 'SECRET')

    def test_eye_for_an_eye_can_produce_draw_before_result(self):
        self.secret('EX1_132')
        self.get('hero-0')['damage'] = 24
        self.get('hero-1')['damage'] = 24
        self.play('CS2_029', 'hero-1')
        self.assertEqual(
            (self.state['result'], self.state['phase']), ('DRAW', 'FINISHED')
        )
        self.assertEqual(self.get('hero-0')['damage'], 30)
        self.assertEqual(self.get('secret')['zone'], 'GRAVEYARD')

    def test_eye_does_not_react_to_absorbed_shield_or_zero_damage(self):
        self.secret('EX1_132')
        self.get('hero-1')['keywords'] = ['DIVINE_SHIELD']
        self.play('CS2_029', 'hero-1')
        self.assertEqual(self.get('secret')['zone'], 'SECRET')
        self.assertEqual(self.get('hero-0')['damage'], 0)

    def test_secret_spell_play_triggers_existing_after_spell_listener(self):
        self.add('NEW1_020', 'pyro')
        self.play('EX1_287', eid='counter')
        self.assertEqual(self.get('pyro')['damage'], 1)
        self.assertEqual(self.get('counter')['zone'], 'SECRET')

    def test_secret_damage_uses_spell_damage_at_trigger_time(self):
        self.secret('EX1_610')
        spell_bonus(self.engine, self.state, 1, 3)
        self.add(eid='yeti', ready=True)
        self.state = self.engine.attack(self.state, 0, 'yeti', 'hero-1')
        self.assertEqual(self.get('hero-0')['damage'], 5)
        self.assertEqual(self.get('yeti')['zone'], 'GRAVEYARD')

    def test_eye_event_amount_is_captured_and_spell_damage_applies(self):
        self.secret('EX1_132')
        spell_bonus(self.engine, self.state, 1, 2)
        self.get('hero-1')['armor'] = 4
        self.play('CS2_029', 'hero-1')
        self.assertEqual(self.get('hero-1')['damage'], 2)
        self.assertEqual(self.get('hero-0')['damage'], 8)


class WeaponAndInterruptTests(ReactionFixture):
    def test_truesilver_heals_before_combat_return_damage(self):
        self.get('hero-0')['damage'] = 5
        self.add(eid='enemy', player=1)
        self.play('CS2_097', eid='silver')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'enemy')
        self.assertEqual(self.get('hero-0')['damage'], 7)
        self.assertEqual(self.get('silver')['durability'], 1)
        types = [e['type'] for e in self.state['events']]
        self.assertLess(types.index('HEAL'), types.index('DAMAGE'))

    def test_deaths_bite_replacement_runs_once_with_new_weapon_equipped(self):
        self.add(eid='yeti')
        self.play('FP1_021', eid='bite')
        self.play('CS2_106', eid='axe')
        self.assertEqual(self.get('yeti')['damage'], 1)
        self.assertEqual([e['source'] for e in self.events('DEATHRATTLE')], ['bite'])
        self.assertEqual(self.engine.equipped_weapon(self.state, 0)['id'], 'axe')

    def test_deaths_bite_break_triggers_deaths_and_cult_master(self):
        self.add('EX1_595', 'cult')
        self.add('EX1_096', 'loot')
        self.play('FP1_021', eid='bite')
        self.get('bite')['durability'] = 1
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.get('bite')['zone'], 'GRAVEYARD')
        self.assertEqual(self.get('loot')['zone'], 'GRAVEYARD')
        self.assertEqual(self.reaction_sources(), ['bite', 'cult', 'loot'])

    def test_declared_attack_cancelled_by_defender_bounce_refunds_count_and_durability(
        self,
    ):
        watcher = card(self.catalog, 'EX1_007')['abilities'][0]
        watcher['trigger'] = dict(
            event='BEFORE_ATTACK', relation='ANY', subjectKind='MINION'
        )
        watcher['effects'] = [
            dict(
                op='RETURN_TO_HAND',
                recipient={'kind': 'DEFENDER'},
                missingRecipient='SKIP',
                targetPlayer='RECIPIENT_CONTROLLER',
            )
        ]
        self.restart()
        self.add('EX1_007', 'watcher', 1)
        self.add(eid='target', player=1)
        self.play('CS2_106', eid='axe')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'target')
        self.assertEqual(self.get('target')['zone'], 'HAND')
        self.assertEqual(self.get('hero-0')['attacksThisTurn'], 0)
        self.assertEqual(self.get('axe')['durability'], 2)
        self.assertIn('hero-1', self.engine.attack_targets(self.state, 'hero-0'))

    def test_preparation_lethal_ends_match_before_combat(self):
        self.secret('EX1_610')
        self.get('hero-0')['damage'] = 29
        self.play('CS2_106', eid='axe')
        self.state = self.engine.attack(self.state, 0, 'hero-0', 'hero-1')
        self.assertEqual(self.state['result'], 'PLAYER_1_WINS')
        self.assertEqual(self.get('axe')['durability'], 2)
        self.assertEqual(self.events('ATTACK'), [])


class SchedulerSafetyTests(ReactionFixture):
    def test_self_nested_reaction_budget_is_atomic(self):
        ability = card(self.catalog, 'EX1_007')['abilities'][0]
        ability['effects'] = [
            dict(
                op='DEAL_DAMAGE',
                amount=dict(kind='CONSTANT', value=1),
                recipient={'kind': 'SELF'},
                missingRecipient='SKIP',
                application='SINGLE_HIT',
                damageClass='ABILITY',
            )
        ]
        self.restart(limit=5)
        self.add('EX1_007', 'loop')
        self.add('CS2_029', 'fire', zone='HAND')
        self.failure(
            lambda: self.engine.play(self.state, 0, 'fire', 'loop'),
            ResolutionLimitError,
        )

    def test_reaction_budget_spans_nested_death_waves(self):
        ability = card(self.catalog, 'CS2_235')['abilities'][0]
        ability['trigger'] = dict(
            event='MINION_DIED', relation='FRIENDLY', subjectKind='MINION'
        )
        ability['effects'] = [
            dict(
                op='SUMMON',
                definition=dict(cardId='EX1_506a', revision='foundation-v8'),
                count=1,
                placement='RIGHT_END',
                targetPlayer='EFFECT_CONTROLLER',
            ),
            query(
                'DEAL_DAMAGE',
                amount=dict(kind='CONSTANT', value=1),
                application='SINGLE_DAMAGE_BATCH',
                damageClass='ABILITY',
            ),
        ]
        self.restart(limit=2)
        self.add('CS2_235', 'loop')
        self.add('EX1_506a', 'victim')
        self.add('CS2_029', 'fire', zone='HAND')
        self.failure(
            lambda: self.engine.play(self.state, 0, 'fire', 'victim'),
            ResolutionLimitError,
        )

    def test_resolved_actions_have_no_private_queue_and_replay_identically(self):
        self.add('EX1_007', 'pain', 1)
        self.add('CS2_029', 'fire', zone='HAND')
        before = deepcopy(self.state)
        a = self.engine.play(self.state, 0, 'fire', 'pain')
        b = self.engine.play(json.loads(json.dumps(self.state)), 0, 'fire', 'pain')
        self.assertEqual(a, b)
        self.assertEqual(before, self.state)
        self.assertFalse(any(k.startswith('_reaction') for k in a))
        self.assertEqual(a, json.loads(json.dumps(a)))


class ReactionGameTests(unittest.TestCase):
    def test_public_reaction_game_replays_across_json_checkpoints(self):
        from examples.play_reactions import run

        final, actions = run(1)
        engine = MatchEngine()
        pool = [
            'EX1_007',
            'CS2_235',
            'EX1_595',
            'NEW1_020',
            'EX1_044',
            'OG_113',
            'EX1_287',
            'EX1_594',
            'EX1_610',
            'EX1_130',
            'EX1_132',
            'CS2_097',
            'FP1_021',
            'EX1_506',
            'CS2_029',
        ] * 2
        state = engine.new_game(
            [pool, list(reversed(pool))], 1, hero_powers=['CS2_034', 'CS1h_001']
        )
        for entry in actions:
            state = engine.apply(
                json.loads(json.dumps(state)), entry['player'], entry['action']
            )
            self.assertFalse(any(k.startswith('_reaction') for k in state))
            for player in (0, 1):
                self.assertLessEqual(len(engine.board(state, player)), 7)
                secrets = [
                    e['cardId']
                    for e in state['entities']
                    if e['zone'] == 'SECRET' and e['controller'] == player
                ]
                self.assertLessEqual(len(secrets), 5)
                self.assertEqual(len(secrets), len(set(secrets)))
        self.assertEqual(state, final)
        self.assertEqual(
            (final['result'], final['turn'], len(actions)), ('PLAYER_0_WINS', 47, 192)
        )
        events = {e['type'] for e in state['events']}
        self.assertTrue(
            {
                'REACTION',
                'SPELL_COUNTERED',
                'ATTACK_REDIRECTED',
                'ATTACK_CANCELLED',
                'DEATHRATTLE',
            }
            <= events
        )


if __name__ == '__main__':
    unittest.main()
