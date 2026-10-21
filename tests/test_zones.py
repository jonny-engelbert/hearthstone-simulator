"""Stage 8: generated instances, ordered boards, zone cleanup and death slots."""
from copy import deepcopy
import json
import unittest

from hearthstone.catalog import ROOT, load, validate
from hearthstone.manifest import verify
from hearthstone.match import MatchEngine
from hearthstone.prototype import Prototype, ResolutionLimitError
from hearthstone import resources


def card(catalog, cid):
    return next(c for c in catalog['cards'] if c['cardId'] == cid)


def summon(cid, revision='foundation-v8', count=1, placement='RIGHT_END', player='EFFECT_CONTROLLER'):
    return dict(op='SUMMON', definition=dict(cardId=cid, revision=revision), count=count,
                placement=placement, targetPlayer=player)


class ZoneCatalogTests(unittest.TestCase):
    def test_eight_catalogs_and_manifests_remain_valid(self):
        current = load(ROOT / 'cards/foundation-v8.json')
        self.assertEqual(len(current['cards']), 37)
        for version in range(1, 9):
            old = load(ROOT / f'cards/foundation-v{version}.json')
            self.assertEqual(current['cards'][:len(old['cards'])], old['cards'])
            manifest = 'manifest.json' if version == 1 else f'manifest-v{version}.json'
            self.assertEqual(verify(json.loads((ROOT / 'cards' / manifest).read_text())), [])

    def test_tokens_cannot_be_used_as_starting_deck_cards(self):
        for cid in ('EX1_506a', 'CS2_mirror', 'FP1_002t', 'EX1_014t', 'CS2_101t'):
            self.assertFalse(card(load(), cid)['collectible'])
            with self.assertRaises(ValueError): MatchEngine().new_game([[cid] * 30] * 2, 0)

    def test_unknown_or_wrong_definition_references(self):
        for cid, rev in [('missing','foundation-v8'), ('EX1_506a','wrong'), ('CS2_027','foundation-v8')]:
            catalog = load()
            card(catalog, 'EX1_506')['abilities'][0]['effects'][0]['definition'] = dict(cardId=cid,revision=rev)
            self.assertTrue(validate(catalog))
        catalog = load()
        card(catalog, 'EX1_014')['abilities'][0]['effects'][0]['definition'] = dict(cardId='CS2_101',revision='foundation-v8')
        self.assertTrue(validate(catalog))

    def test_bad_generation_count_placement_and_extra_fields(self):
        for key, value in [('count',0),('count',True),('count',8),('placement','ANYWHERE'),('extra',1)]:
            catalog = load()
            card(catalog, 'CS2_027')['abilities'][0]['effects'][0][key] = value
            self.assertTrue(validate(catalog))

    def test_source_and_death_placement_are_context_checked(self):
        for cid, placement in [('CS2_027','RIGHT_OF_SOURCE'),('CS2_027','DEATH_POSITION'),('FP1_002','RIGHT_OF_SOURCE')]:
            catalog = load()
            card(catalog,cid)['abilities'][0]['effects'][0]['placement'] = placement
            self.assertTrue(validate(catalog))
        catalog = load()
        card(catalog,'EX1_014')['abilities'][0]['effects'][0]['targetPlayer']='CONTROLLER_AT_DEATH'
        self.assertTrue(validate(catalog))

    def test_moves_and_copies_require_minions_and_explicit_policy(self):
        for cid in ('EX1_581','BRM_007','GVG_031'):
            catalog=load(); card(catalog,cid)['abilities'][0]['targeting']['selector']['entityKind']='CHARACTER'
            self.assertTrue(validate(catalog))
        for key,value in [('copyPolicy','BOARD_STATE'),('count',0),('count',100),('targetPlayer','OWNER')]:
            catalog=load(); card(catalog,'BRM_007')['abilities'][0]['effects'][0][key]=value
            self.assertTrue(validate(catalog))

    def test_previous_schema_rejects_new_operation(self):
        catalog=load(ROOT / 'cards/foundation-v7.json')
        card(catalog,'GAME_005')['abilities'][0]['effects']=[summon('CS2_tk1','foundation-v1')]
        self.assertTrue(validate(catalog))


class ZoneFixture(unittest.TestCase):
    def setUp(self):
        self.catalog=load()
        self.counter=0
        self.restart()

    def restart(self, powers=None, budget=1000):
        self.engine=MatchEngine(self.catalog,max_deathrattles=budget)
        self.state=self.engine.new_game([['CS2_182']*30]*2,0,first_player=0,hero_powers=powers)
        self.state=self.engine.mulligan(self.state,0,[])
        self.state=self.engine.mulligan(self.state,1,[])
        self.refill()

    def refill(self):
        for r in self.state['resources']:
            r.update(permanent=10,filled=10,temporary=0,locked=0,pendingOverload=0)
        resources.sync(self.state)

    def add(self,cid='CS2_182',eid=None,player=0,zone='PLAY',**fields):
        self.counter+=1
        e=self.engine.entity(eid or f'fixture-{self.counter}',cid,player,zone)
        e.update(fields); self.state['entities'].append(e)
        if zone=='DECK': self.state['decks'][player].append(e['id'])
        return e

    def get(self,eid,state=None): return self.engine._entity(self.state if state is None else state,eid)
    def ids(self,player=0): return [e['id'] for e in self.engine.board(self.state,player)]
    def events(self,kind): return [e for e in self.state['events'] if e['type']==kind]
    def play(self,cid,target=None,eid=None,position=None):
        e=self.add(cid,eid,self.state['activePlayer'],'HAND')
        self.state=self.engine.play(self.state,self.state['activePlayer'],e['id'],target,position)
        return e['id']
    def end(self): self.state=self.engine.end_turn(self.state,self.state['activePlayer'])
    def hand(self,p): return [e for e in self.state['entities'] if e['zone']=='HAND' and e['controller']==p]
    def fill_hand(self,p):
        while len(self.hand(p))<10: self.add(player=p,zone='HAND')
    def failure(self,fn,error=ValueError):
        before=deepcopy(self.state)
        with self.assertRaises(error): fn()
        self.assertEqual(before,self.state)


class SummonTests(ZoneFixture):
    def test_play_position_and_source_adjacent_summon(self):
        self.add(eid='left'); self.add(eid='right')
        self.play('EX1_506',eid='tide',position=1)
        scout=self.events('GENERATED')[0]['entity']
        self.assertEqual(self.ids(),['left','tide',scout,'right'])
        self.assertFalse(self.get(scout)['ready'])
        self.assertEqual(self.get(scout)['owner'],0)
        self.assertEqual([e['reason'] for e in self.events('SUMMON')],['PLAY','CARD_EFFECT'])
        self.assertLess(self.get('tide')['playOrder'],self.get(scout)['playOrder'])

    def test_default_and_boundary_positions(self):
        self.play('CS2_182',eid='a'); self.play('EX1_015',eid='b',position=0)
        self.refill(); self.play('CS2_179',eid='c',position=2)
        self.assertEqual(self.ids(),['b','a','c'])
        before=deepcopy(self.state)
        self.assertEqual(self.ids(),['b','a','c'])
        self.assertEqual(before,self.state)

    def test_bad_positions_and_full_board_are_atomic(self):
        self.add('CS2_182','source',zone='HAND')
        for position in (-1,1,True,0.5,'0'):
            self.failure(lambda:self.engine.play(self.state,0,'source',position=position))
        self.add('CS2_027','spell',zone='HAND')
        self.failure(lambda:self.engine.play(self.state,0,'spell',position=0))
        for i in range(7): self.add(eid=f'board-{i}')
        self.failure(lambda:self.engine.play(self.state,0,'source'))

    def test_dispatcher_position_and_generated_operations_are_not_free_actions(self):
        self.add('EX1_506','tide',zone='HAND')
        self.state=self.engine.apply(self.state,0,dict(type='play',source='tide',position=0))
        self.assertEqual(self.get(self.ids()[1])['cardId'],'EX1_506a')
        for action in ({'type':'summon','cardId':'EX1_506a'},{'type':'add_card'},{'type':'shuffle'}):
            self.failure(lambda:self.engine.apply(self.state,0,action))

    def test_spell_multi_summon_is_rightmost_without_battlecries(self):
        self.add(eid='left'); self.play('CS2_027',eid='mirror')
        tokens=self.ids()[1:]
        self.assertEqual(len(tokens),2)
        self.assertTrue(all(self.get(i)['keywords']==['TAUNT'] for i in tokens))
        self.assertEqual(self.get('mirror')['zone'],'GRAVEYARD')
        self.assertEqual(self.state['cardsPlayedThisTurn'][0],1)
        self.assertEqual(len(self.events('PLAY')),1)

    def test_summoning_novice_does_not_trigger_battlecry(self):
        card(self.catalog,'CS2_027')['abilities'][0]['effects']=[summon('EX1_015','foundation-v2')]
        self.restart(); before=list(self.state['decks'][0])
        self.play('CS2_027')
        self.assertEqual(self.state['decks'][0],before)
        self.assertEqual(self.get(self.ids()[0])['cardId'],'EX1_015')

    def test_summoning_overload_minion_does_not_charge_overload(self):
        card(self.catalog,'CS2_182')['overload']=2
        card(self.catalog,'CS2_027')['abilities'][0]['effects']=[summon('CS2_182','foundation-v1')]
        self.restart(); self.play('CS2_027')
        self.assertEqual(self.state['resources'][0]['pendingOverload'],0)

    def test_full_board_summon_fails_without_generation_or_rng(self):
        for i in range(7): self.add(eid=f'b{i}')
        before=deepcopy(self.state['rng']); self.play('CS2_027')
        self.assertEqual(len(self.ids()),7)
        self.assertEqual(len(self.events('SUMMON_FAILED')),2)
        self.assertEqual(self.events('GENERATED'),[])
        self.assertEqual(self.state['rng'],before)

    def test_partial_multi_summon_and_battlecry_lost_at_capacity(self):
        for i in range(6): self.add(eid=f'b{i}')
        self.play('CS2_027')
        self.assertEqual(len(self.events('GENERATED')),1)
        self.assertEqual(len(self.events('SUMMON_FAILED')),1)
        self.restart()
        for i in range(6): self.add(eid=f'b{i}')
        self.play('EX1_506')
        self.assertEqual(self.events('GENERATED'),[])
        self.assertEqual(len(self.ids()),7)

    def test_auras_apply_to_generated_tokens_without_accumulation(self):
        self.add('CS2_222','champ'); self.play('CS2_027')
        for e in self.engine.board(self.state,0)[1:]:
            self.assertEqual(self.engine.current_attack(self.state,e),1)
            self.assertEqual(self.engine.current_health(self.state,e),3)

    def test_generated_charge_and_rush_follow_normal_attack_rules(self):
        card(self.catalog,'CS2_027')['abilities'][0]['effects']=[summon('CS2_124','foundation-v7'),summon('GIL_580','foundation-v7')]
        self.restart(); self.add('EX1_015','enemy',1)
        self.play('CS2_027')
        wolf,rush=self.ids()
        self.assertIn('hero-1',self.engine.attack_targets(self.state,wolf))
        self.assertEqual(self.engine.attack_targets(self.state,rush),['enemy'])

    def test_summoning_hero_power_capacity_usage_and_default_position(self):
        self.restart(['CS2_101',None]); self.add(eid='left')
        self.state=self.engine.hero_power(self.state,0)
        recruit=self.ids()[-1]
        self.assertEqual(self.get(recruit)['cardId'],'CS2_101t')
        self.assertEqual(self.state['cardsPlayedThisTurn'][0],0)
        self.failure(lambda:self.engine.hero_power(self.state,0))
        self.end(); self.end()
        while len(self.ids())<7: self.add()
        self.failure(lambda:self.engine.hero_power(self.state,0))
        self.assertEqual(self.state['heroPowerUsesThisTurn'][0],0)

    def test_generated_ids_skip_collisions_and_survive_json_restore(self):
        self.add(eid='generated-1',zone='GRAVEYARD')
        self.play('CS2_027')
        self.assertEqual(self.ids(),['generated-2','generated-3'])
        self.assertEqual(self.state['nextEntityId'],4)
        self.state=json.loads(json.dumps(self.state))
        self.play('CS2_027')
        self.assertEqual(self.ids()[-2:],['generated-4','generated-5'])
        self.assertEqual(len({e['id'] for e in self.state['entities']}),len(self.state['entities']))

    def test_multiple_source_summons_preserve_rightward_order(self):
        card(self.catalog,'EX1_506')['abilities'][0]['effects'][0]['count']=2
        self.restart(); self.add(eid='left'); self.add(eid='right')
        self.play('EX1_506',eid='tide',position=1)
        tokens=[e['entity'] for e in self.events('GENERATED')]
        self.assertEqual(self.ids(),['left','tide',*tokens,'right'])

    def test_bad_generated_counter_rolls_back_entire_play(self):
        self.add('CS2_027','mirror',zone='HAND'); self.state['nextEntityId']=True
        self.failure(lambda:self.engine.play(self.state,0,'mirror'))


class GeneratedHandTests(ZoneFixture):
    def test_mukla_adds_two_fresh_bananas_to_opponent(self):
        before=list(self.state['decks'][1]); draws=len(self.events('DRAW'))
        self.play('EX1_014',eid='mukla')
        bananas=[e for e in self.hand(1) if e['cardId']=='EX1_014t']
        self.assertEqual(len(bananas),2)
        self.assertTrue(all(e['owner']==1 and e['createdBy']=='mukla' for e in bananas))
        self.assertEqual(self.state['decks'][1],before)
        self.assertEqual(len(self.events('DRAW')),draws)
        self.assertEqual(len(self.events('ADD_TO_HAND')),3)  # includes setup Coin

    def test_full_hand_generated_cards_discard_without_deathrattle(self):
        self.fill_hand(1); self.play('EX1_014')
        self.assertEqual(len(self.hand(1)),10)
        self.assertEqual(len(self.events('DISCARD')),2)
        self.assertEqual(self.events('BURN'),[])
        self.assertEqual(self.events('DEATHRATTLE'),[])
        for e in self.events('DISCARD'): self.assertEqual(self.get(e['entity'])['zone'],'GRAVEYARD')

    def test_partial_hand_capacity_adds_one_discards_one(self):
        while len(self.hand(1))<9: self.add(player=1,zone='HAND')
        self.play('EX1_014')
        self.assertEqual(len(self.hand(1)),10)
        self.assertEqual(len(self.events('DISCARD')),1)

    def test_generated_banana_is_playable_and_modifies_minion(self):
        self.play('EX1_014',eid='mukla'); self.end(); self.refill()
        banana=next(e['id'] for e in self.hand(1) if e['cardId']=='EX1_014t')
        self.state=self.engine.play(self.state,1,banana,'mukla')
        self.assertEqual(self.engine.current_attack(self.state,self.get('mukla')),6)
        self.assertEqual(self.get(banana)['zone'],'GRAVEYARD')


class BounceTests(ZoneFixture):
    def test_play_from_full_hand_frees_room_for_battlecry_return(self):
        self.add(eid='target'); self.add('EX1_049','brew',zone='HAND'); self.fill_hand(0)
        self.state=self.engine.play(self.state,0,'brew','target')
        self.assertEqual(len(self.hand(0)),10)
        self.assertEqual(self.get('target')['zone'],'HAND')
        self.assertEqual(self.events('ZONE_MOVE_FAILED'),[])

    def test_bounced_zero_cost_token_can_be_replayed_without_mana(self):
        self.play('CS2_027')
        token=self.ids()[0]
        self.play('EX1_049',token,'brew')
        self.state['resources'][0].update(filled=0,temporary=0)
        resources.sync(self.state)
        self.state=self.engine.play(self.state,0,token,position=0)
        self.assertEqual(self.state['mana'][0],0)
        self.assertEqual(self.ids()[0],token)
        self.assertEqual(self.get(token)['keywords'],['TAUNT'])

    def test_bounce_retains_id_owner_and_definition_but_clears_board_state(self):
        e=self.add('CS2_179','target',damage=2,ready=True,attacksThisTurn=1,owner=1,
                   keywords=['FROZEN'],silenced=True,freezeUntil={'player':0,'playerTurn':2},
                   enchantments=[dict(kind='STAT_BUFF',source='fixture',attack=4,health=4)])
        self.play('EX1_049','target','brew')
        target=self.get('target')
        self.assertEqual((target['zone'],target['owner'],target['controller'],target['cardId']),('HAND',1,0,'CS2_179'))
        self.assertEqual((target['damage'],target['enchantments'],target['keywords'],target['silenced']),(0,[],['TAUNT'],False))
        self.assertNotIn('freezeUntil',target); self.assertNotIn('playOrder',target)
        self.assertFalse(target['ready']); self.assertEqual(target['attacksThisTurn'],0)
        self.assertEqual(self.events('DEATHRATTLE'),[])

    def test_replaying_bounced_novice_reexecutes_battlecry_and_gets_new_stamp(self):
        self.play('EX1_015',eid='novice'); old=self.get('novice')['playOrder']
        self.play('EX1_049','novice','brew')
        before=len(self.state['decks'][0])
        self.state=self.engine.play(self.state,0,'novice',position=0)
        self.assertEqual(len(self.state['decks'][0]),before-1)
        self.assertGreater(self.get('novice')['playOrder'],old)
        self.assertEqual(self.ids()[0],'novice')

    def test_brewmaster_without_target_and_target_legality(self):
        self.play('EX1_049',eid='alone')
        self.add('EX1_049','brew',zone='HAND'); self.add(eid='enemy',player=1)
        self.failure(lambda:self.engine.play(self.state,0,'brew'))
        self.failure(lambda:self.engine.play(self.state,0,'brew','enemy'))
        self.state=self.engine.play(self.state,0,'brew','alone')
        self.assertEqual(self.get('alone')['zone'],'HAND')

    def test_sap_returns_to_current_controller_hand_even_with_different_owner(self):
        self.add(eid='stolen',player=1,owner=0)
        self.play('EX1_581','stolen')
        self.assertEqual((self.get('stolen')['zone'],self.get('stolen')['controller'],self.get('stolen')['owner']),('HAND',1,0))

    def test_full_hand_bounce_destroys_and_resolves_deathrattle(self):
        self.fill_hand(1); self.add('FP1_002','creeper',1)
        self.play('EX1_581','creeper')
        self.assertEqual(self.get('creeper')['zone'],'GRAVEYARD')
        self.assertEqual(len(self.engine.board(self.state,1)),2)
        self.assertEqual(len(self.events('DEATHRATTLE')),1)
        self.assertEqual(self.events('ZONE_MOVE_FAILED')[-1]['reason'],'FULL_HAND')

    def test_silenced_full_hand_bounce_has_no_deathrattle(self):
        self.fill_hand(1); self.add('FP1_002','creeper',1,silenced=True)
        self.play('EX1_581','creeper')
        self.assertEqual(self.events('DEATHRATTLE'),[])

    def test_bounce_aura_source_removes_aura_and_bounced_token_stays_token(self):
        self.add('CS2_222','champ'); self.add(eid='yeti')
        self.play('EX1_049','champ','brew')
        self.assertEqual(self.engine.current_attack(self.state,self.get('yeti')),4)
        self.refill(); self.play('CS2_027')
        token=next(e['id'] for e in self.engine.board(self.state,0) if e['cardId']=='CS2_mirror')
        self.play('EX1_049',token,'brew2')
        self.assertEqual(self.get(token)['cardId'],'CS2_mirror')
        self.assertEqual(self.get(token)['zone'],'HAND')

    def test_transform_preserves_board_slot_and_bounce_uses_transformed_definition(self):
        self.add(eid='left'); self.add('EX1_096','middle'); self.add(eid='right')
        self.play('CS2_022','middle','poly')
        self.assertEqual(self.ids(),['left','middle','right'])
        self.assertEqual(self.events('SUMMON'),[])
        self.play('EX1_049','middle','brew')
        self.assertEqual(self.get('middle')['cardId'],'CS2_tk1')
        self.assertEqual(self.get('middle')['zone'],'HAND')

    def test_temporary_buff_and_freeze_timers_do_not_follow_bounce(self):
        self.add(eid='yeti',ready=True)
        self.play('EX1_046','yeti'); self.play('CS2_024','yeti')
        self.play('EX1_049','yeti')
        self.end(); self.end(); self.end()
        self.assertEqual(self.events('BUFF_EXPIRED'),[])
        self.assertEqual(self.events('THAW'),[])


class ShuffleTests(ZoneFixture):
    def test_gang_up_makes_three_clean_independent_copies_without_moving_source(self):
        self.add('CS2_179','original',player=1,damage=2,silenced=True,keywords=['FROZEN'],
                 enchantments=[dict(kind='STAT_BUFF',source='x',attack=4,health=4)])
        before=deepcopy(self.get('original')); size=len(self.state['decks'][0])
        self.play('BRM_007','original')
        copies=[self.get(e['entity']) for e in self.events('COPY')]
        self.assertEqual(len(copies),3)
        self.assertEqual(len(self.state['decks'][0]),size+3)
        self.assertEqual(self.get('original')['zone'],'PLAY')
        self.assertEqual(self.get('original')['enchantments'],before['enchantments'])
        self.assertTrue(all(e['owner']==0 and e['controller']==0 and e['zone']=='DECK' for e in copies))
        self.assertTrue(all(e['damage']==0 and not e['silenced'] and e['keywords']==['TAUNT'] and not e['enchantments'] for e in copies))
        copies[0]['keywords'].clear()
        self.assertEqual(copies[1]['keywords'],['TAUNT'])

    def test_copy_after_transform_uses_current_exact_definition(self):
        self.add(eid='original'); self.play('CS2_022','original')
        self.play('BRM_007','original')
        self.assertTrue(all(self.get(e['entity'])['cardId']=='CS2_tk1' and self.get(e['entity'])['revision']=='foundation-v1' for e in self.events('COPY')))

    def test_recycle_moves_same_entity_clears_buffs_without_death(self):
        self.add('EX1_096','loot',1,damage=0,keywords=['FROZEN'],
                 enchantments=[dict(kind='STAT_BUFF',source='x',attack=4,health=4)])
        size=len(self.state['decks'][1]); self.play('GVG_031','loot')
        e=self.get('loot')
        self.assertEqual((e['zone'],e['damage'],e['enchantments'],e['keywords']),('DECK',0,[],[]))
        self.assertEqual(len(self.state['decks'][1]),size+1)
        self.assertEqual(self.events('DEATHRATTLE'),[])
        self.assertNotIn('loot',self.ids(1))
        self.assertNotIn('playOrder',e)

    def test_shuffle_is_seeded_atomic_and_json_reproducible(self):
        self.add(eid='original',player=1); self.add('BRM_007','gang',zone='HAND')
        before=deepcopy(self.state)
        result=self.engine.play(self.state,0,'gang','original')
        restored=self.engine.play(json.loads(json.dumps(self.state)),0,'gang','original')
        self.assertEqual(result,restored); self.assertEqual(before,self.state)
        self.assertGreater(result['rng']['draws'],before['rng']['draws'])
        self.assertEqual(len([e for e in result['events'] if e['type']=='SHUFFLE']),1)

    def test_drawing_shuffled_copy_can_replay_its_battlecry(self):
        self.add('EX1_015','novice',1)
        # Empty the existing deck consistently, so each shuffled card is a copy.
        for eid in self.state['decks'][0]: self.get(eid)['zone']='GRAVEYARD'
        self.state['decks'][0]=[]
        self.play('BRM_007','novice'); self.end(); self.end()
        drawn=next(e for e in self.hand(0) if e['id'].startswith('generated-'))
        size=len(self.state['decks'][0]); self.refill()
        self.state=self.engine.play(self.state,0,drawn['id'])
        self.assertEqual(len(self.state['decks'][0]),size-1)

    def test_shuffle_does_not_reset_fatigue(self):
        self.state['fatigue'][0]=4
        self.add(eid='original'); self.play('BRM_007','original')
        self.assertEqual(self.state['fatigue'][0],4)

    def test_copy_deck_capacity_is_partial_and_then_fails_without_ids(self):
        while len(self.state['decks'][0])<98: self.add(zone='DECK')
        self.add(eid='original'); self.play('BRM_007','original')
        self.assertEqual(len(self.state['decks'][0]),99)
        self.assertEqual(len(self.events('COPY')),1)
        self.assertEqual(len(self.events('COPY_FAILED')),2)
        self.assertEqual(self.state['nextEntityId'],2)

    def test_full_deck_recycle_destroys_in_play_and_runs_deathrattle(self):
        while len(self.state['decks'][1])<99: self.add(player=1,zone='DECK')
        self.add('FP1_002','creeper',1); self.play('GVG_031','creeper')
        self.assertEqual(self.get('creeper')['zone'],'GRAVEYARD')
        self.assertEqual(len(self.ids(1)),2)
        self.assertEqual(len(self.state['decks'][1]),99)
        self.assertEqual(self.events('ZONE_MOVE_FAILED')[-1]['reason'],'FULL_DECK')

    def test_shuffle_requires_rng_and_failure_rolls_back(self):
        self.add(eid='original'); self.add('BRM_007','gang',zone='HAND')
        del self.state['rng']
        self.failure(lambda:self.engine.play(self.state,0,'gang','original'))


class DeathSummonTests(ZoneFixture):
    def test_creeper_tokens_fill_original_gap_in_order(self):
        self.add(eid='left'); self.add('FP1_002','creeper'); self.add(eid='right')
        self.play('CS2_029','creeper')
        tokens=[e['entity'] for e in self.events('GENERATED')]
        self.assertEqual(self.ids(),['left',*tokens,'right'])
        self.assertEqual(len(tokens),2)
        self.assertEqual(self.get('creeper')['zone'],'GRAVEYARD')
        self.assertEqual(self.state['deathHistory'][-1]['position'],1)

    def test_simultaneous_deaths_keep_gaps_even_with_reverse_death_order(self):
        self.add(eid='left',player=1,playOrder=3)
        self.add('FP1_002','a',player=1,playOrder=2)
        self.add('FP1_002','b',player=1,playOrder=1)
        # Add friendly neighbors on the actual dying board.
        self.add(eid='right',player=1,playOrder=4)
        self.play('CS2_032')
        self.assertEqual([e['source'] for e in self.events('DEATHRATTLE')],['b','a'])
        self.assertEqual([e.get('createdBy',e['id']) for e in self.engine.board(self.state,1)],['left','a','a','b','b','right'])

    def test_all_full_board_deaths_free_slots_then_apply_partial_summons(self):
        for i in range(7): self.add('FP1_002',f'c{i}',player=1)
        self.play('CS2_032')
        self.assertEqual(len(self.ids(1)),7)
        self.assertEqual(len(self.events('GENERATED')),7)
        self.assertEqual(len(self.events('SUMMON_FAILED')),7)
        self.assertEqual([e['createdBy'] for e in self.engine.board(self.state,1)],['c0','c0','c1','c1','c2','c2','c3'])

    def test_stolen_creeper_summons_for_controller_at_death(self):
        self.add('FP1_002','creeper',1,owner=0)
        self.play('CS2_029','creeper')
        self.assertEqual(len(self.ids(0)),0); self.assertEqual(len(self.ids(1)),2)
        self.assertTrue(all(e['owner']==1 for e in self.engine.board(self.state,1)))

    def nested_fixture(self,budget=1000):
        creep=card(self.catalog,'FP1_002')['abilities'][0]['effects']
        creep.append(dict(op='DEAL_DAMAGE',amount=dict(kind='CONSTANT',value=1),recipient=dict(kind='QUERY',capture='EFFECT_START',selector=dict(zone='PLAY',entityKind='MINION',controller='FRIENDLY')),missingRecipient='SKIP',application='SINGLE_DAMAGE_BATCH',damageClass='ABILITY'))
        spider=card(self.catalog,'FP1_002t'); spider['mechanics']=['DEATHRATTLE']
        spider['abilities']=[dict(kind='DEATHRATTLE',effects=[summon('EX1_506a',placement='DEATH_POSITION',player='CONTROLLER_AT_DEATH')])]
        self.restart(budget=budget)
        self.add('FP1_002','creeper',1)
        self.add('CS2_029','kill',zone='HAND')

    def test_nested_summon_deaths_are_next_wave_and_tokens_get_new_stamps(self):
        self.nested_fixture()
        self.state=self.engine.play(self.state,0,'kill','creeper')
        batches=self.events('DEATH_BATCH')
        self.assertEqual(len(batches),2)
        self.assertEqual(batches[0]['targets'],['creeper'])
        self.assertEqual(len(batches[1]['targets']),2)
        self.assertEqual([e['cardId'] for e in self.engine.board(self.state,1)],['EX1_506a','EX1_506a'])
        self.assertEqual(len({e['playOrder'] for e in self.engine.board(self.state,1)}),2)

    def test_nested_generation_budget_failure_is_atomic(self):
        self.nested_fixture(budget=2)
        self.failure(lambda:self.engine.play(self.state,0,'kill','creeper'),ResolutionLimitError)
        self.assertNotIn('nextEntityId',self.state)

    def test_death_snapshot_retains_buffs_but_graveyard_loses_timers(self):
        self.add('FP1_002','creeper',1,enchantments=[dict(kind='STAT_BUFF',source='x',attack=2,health=0)],keywords=['FROZEN'],freezeUntil=dict(player=1,playerTurn=2))
        self.play('CS2_029','creeper')
        snap=self.state['deathHistory'][-1]['entity']
        self.assertEqual(len(snap['enchantments']),1)
        self.assertEqual(snap['keywords'],['FROZEN'])
        self.assertEqual(self.get('creeper')['enchantments'],[])
        self.assertNotIn('freezeUntil',self.get('creeper'))

    def test_weapon_departure_clears_operative_modifiers(self):
        self.play('CS2_106',eid='old')
        self.get('old')['keywords']=['WINDFURY']
        self.get('old')['enchantments']=['fixture-annotation']
        self.play('CS2_106',eid='new')
        self.assertEqual(self.get('old')['zone'],'GRAVEYARD')
        self.assertEqual(self.get('old')['keywords'],[])
        self.assertEqual(self.get('old')['enchantments'],[])


class ZoneGameTests(unittest.TestCase):
    def test_complete_public_game_replays_through_json_and_keeps_zone_invariants(self):
        from examples.play_zones import run
        final,actions=run(1)
        engine=MatchEngine(load(ROOT / 'cards/foundation-v8.json'))
        pool=['EX1_506','FP1_002','EX1_014','CS2_027','EX1_049',
              'BRM_007','GVG_031','EX1_581','EX1_015','CS2_124']*3
        state=engine.new_game([pool,list(reversed(pool))],1,hero_powers=['CS2_101','CS2_034'])
        for entry in actions:
            before=json.loads(json.dumps(state))
            state=engine.apply(before,entry['player'],entry['action'])
            for p in (0,1):
                self.assertLessEqual(len(engine.board(state,p)),7)
                self.assertLessEqual(sum(e['zone']=='HAND' and e['controller']==p for e in state['entities']),10)
                self.assertLessEqual(len(state['decks'][p]),99)
            self.assertEqual(len({e['id'] for e in state['entities']}),len(state['entities']))
            ordered={i for deck in state['decks'] for i in deck}
            self.assertEqual(ordered,{e['id'] for e in state['entities'] if e['zone']=='DECK'})
        self.assertEqual(state,final)
        self.assertEqual((final['result'],final['turn'],len(actions)),('PLAYER_0_WINS',32,177))
        kinds={e['type'] for e in final['events']}
        self.assertTrue({'SUMMON','GENERATED','ZONE_CHANGE','COPY','SHUFFLE','DEATHRATTLE','ADD_TO_HAND'} <= kinds)


if __name__=='__main__': unittest.main()
