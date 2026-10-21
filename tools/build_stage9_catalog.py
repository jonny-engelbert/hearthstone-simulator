"""Rebuild the stage-9 fixture artifacts from the frozen stage-8 inputs."""
import json
from copy import deepcopy as cp
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
s=json.loads((ROOT/'schemas/catalog-v1.8.schema.json').read_text())
s['title']='Foundation catalog 1.9 (reactions and interruption windows)'
s['properties']['schemaVersion']['const']='1.9';s['properties']['catalogId']['const']='foundation-v9'
s['properties']['reactionPolicy']={'const':'DEPTH_FIRST_REACTIONS_DEATH_WAVES_V1'};s['required'].append('reactionPolicy')
d=s['$defs'];c=d['card']['properties'];c['schemaVersion']['enum'].append('1.9')
c['classes']['items']['enum']+=['HUNTER','WARLOCK'];c['set']['enum'].append('OG');c['mechanics']['items']['enum'].append('SECRET')
trigger=dict(type='object',properties={'event':{'enum':['ON_CARD_PLAY','AFTER_CARD_PLAY','BEFORE_SPELL','AFTER_SPELL','AFTER_SUMMON','DAMAGE','HEAL','MINION_DIED','BEFORE_ATTACK','AFTER_ATTACK']},'relation':{'enum':['ANY','FRIENDLY','ENEMY','SELF']},'subjectKind':{'enum':['ANY','MINION','HERO','SPELL','WEAPON','CHARACTER']},'actorKind':{'enum':['ANY','MINION','HERO','CHARACTER']},'excludeSelf':{'type':'boolean'}},required=['event','relation','subjectKind'],additionalProperties=False)
react=cp(d['ability']['oneOf'][0]);react['properties']['kind']={'enum':['TRIGGER','SECRET']};react['properties'].pop('targeting');react['properties']['trigger']=trigger;react['required'].append('trigger');d['ability']['oneOf'].append(react)
r=dict(type='object',properties={'kind':{'enum':['SELF','EVENT_TARGET','ATTACKER','DEFENDER','CONTROLLER_HERO','OPPONENT_HERO']}},required=['kind'],additionalProperties=False)
for e in d['effect']['oneOf']:
 p=e['properties']
 if 'recipient' in p:
  old=p['recipient'];p['recipient']={'oneOf':old['oneOf']+[cp(r)] if 'oneOf' in old else [old,cp(r)]}
 if 'amount' in p:p['amount']={'oneOf':[p['amount'],dict(type='object',properties={'kind':{'const':'EVENT_AMOUNT'}},required=['kind'],additionalProperties=False)]}
for name,fields in [('COUNTER_SPELL',{}),('REDIRECT_ATTACK',{'definition':{'$ref':'#/$defs/definitionReference'}})]:
 d['effect']['oneOf'].append(dict(type='object',properties=dict(op={'const':name},**fields),required=['op',*fields],additionalProperties=False))
w=d['card']['allOf'][2]['then']['properties'];w['abilities']={'type':'array','items':{'$ref':'#/$defs/ability'}};w['mechanics']={'type':'array','items':{'const':'DEATHRATTLE'},'uniqueItems':True}
(ROOT/'schemas/catalog-v1.9.schema.json').write_text(json.dumps(s,indent=2)+'\n')
cat=json.loads((ROOT/'cards/foundation-v8.json').read_text());cat.update(schemaVersion='1.9',catalogId='foundation-v9',reactionPolicy='DEPTH_FIRST_REACTIONS_DEATH_WAVES_V1')
def t(event,relation='FRIENDLY',subject='MINION',**kw):return dict(event=event,relation=relation,subjectKind=subject,**kw)
def e(op,recipient='SELF',**kw):return dict(op=op,recipient={'kind':recipient},missingRecipient='SKIP',**kw)
def buff(a,h):return e('BUFF',modifiers={'attack':a,'health':h},duration='PERMANENT')
def damage(n,recipient=None):
 return dict(op='DEAL_DAMAGE',amount=dict(kind='CONSTANT',value=n),recipient={'kind':recipient} if recipient else dict(kind='QUERY',capture='EFFECT_START',selector=dict(zone='PLAY',entityKind='MINION',controller='ANY')),missingRecipient='SKIP',application='SINGLE_HIT' if recipient else 'SINGLE_DAMAGE_BATCH',damageClass='ABILITY')
def card(cid,name,typ,cls,cost,attack=None,health=None,*,kind='TRIGGER',trigger=None,effects=(),exp='EXPERT1',rarity='COMMON',text='',durability=None,url='https://hearthstone.blizzard.com/en-us/cards/',collectible=True):
 stats={'manaCost':cost}
 if attack is not None:stats['attack']=attack
 if health is not None:stats['health']=health
 if durability is not None:stats['durability']=durability
 ability={'kind':kind,'effects':list(effects)}
 if trigger:ability['trigger']=trigger
 return dict(schemaVersion='1.9',cardId=cid,revision='foundation-v9',name=name,type=typ,classes=[cls],baseStats=stats,collectible=collectible,set=exp,rarity=rarity,tribes=[],spellSchool=None,keywords=[],mechanics=[kind] if kind in ('SECRET','DEATHRATTLE') else [],text={'enUS':text},playConditions=[],abilities=[ability] if effects else [],sources=[url])
draw=dict(op='DRAW_CARD',count=1,targetPlayer='EFFECT_CONTROLLER')
cat['cards'] += [
card('EX1_007','Acolyte of Pain','MINION','NEUTRAL',3,1,3,trigger=t('DAMAGE','SELF'),effects=[draw],text='Whenever this minion takes damage, draw a card.'),
card('CS2_235','Northshire Cleric','MINION','PRIEST',1,1,3,trigger=t('HEAL','ANY'),effects=[draw],exp='BASIC',rarity='FREE',text='Whenever a minion is healed, draw a card.'),
card('EX1_595','Cult Master','MINION','NEUTRAL',4,4,2,trigger=t('MINION_DIED',excludeSelf=True),effects=[draw],text='Whenever one of your other minions dies, draw a card.'),
card('NEW1_020','Wild Pyromancer','MINION','NEUTRAL',2,3,2,trigger=t('AFTER_SPELL',subject='SPELL'),effects=[damage(1)],rarity='RARE',text='After you cast a spell, deal 1 damage to ALL minions.'),
card('EX1_044','Questing Adventurer','MINION','NEUTRAL',3,2,2,trigger=t('ON_CARD_PLAY',subject='ANY',excludeSelf=True),effects=[buff(1,1)],rarity='RARE',text='Whenever you play a card, gain +1/+1.'),
card('OG_113','Darkshire Councilman','MINION','WARLOCK',3,1,5,trigger=t('AFTER_SUMMON',excludeSelf=True),effects=[buff(1,0)],exp='OG',text='After you summon a minion, gain +1 Attack.'),
card('EX1_287','Counterspell','SPELL','MAGE',3,kind='SECRET',trigger=t('BEFORE_SPELL','ENEMY','SPELL'),effects=[{'op':'COUNTER_SPELL'}],rarity='RARE',text='Secret: When your opponent casts a spell, Counter it.',url='https://hearthstone.blizzard.com/en-us/cards/113/'),
card('EX1_594','Vaporize','SPELL','MAGE',3,kind='SECRET',trigger=t('BEFORE_ATTACK',subject='HERO',actorKind='MINION'),effects=[e('DESTROY','ATTACKER')],rarity='RARE',text='Secret: When a minion attacks your hero, destroy it.'),
card('EX1_610','Explosive Trap','SPELL','HUNTER',2,kind='SECRET',trigger=t('BEFORE_ATTACK',subject='HERO'),effects=[dict(damage(2),recipient=dict(kind='QUERY',capture='EFFECT_START',selector=dict(zone='PLAY',entityKind='CHARACTER',controller='OPPONENT_OF_EFFECT_CONTROLLER')))],text='Secret: When your hero is attacked, deal 2 damage to all enemies.'),
card('EX1_130','Noble Sacrifice','SPELL','PALADIN',1,kind='SECRET',trigger=t('BEFORE_ATTACK',subject='CHARACTER'),effects=[dict(op='REDIRECT_ATTACK',definition=dict(cardId='EX1_130a',revision='foundation-v9'))],text='Secret: When an enemy attacks, summon a 2/1 Defender as the new target.'),
card('EX1_130a','Defender','MINION','PALADIN',1,2,1,effects=[],collectible=False),
card('CS2_097','Truesilver Champion','WEAPON','PALADIN',4,4,durability=2,trigger=t('BEFORE_ATTACK','SELF','HERO'),effects=[e('HEAL','CONTROLLER_HERO',amount=dict(kind='CONSTANT',value=2))],exp='BASIC',rarity='FREE',text='Whenever your hero attacks, restore 2 Health to it.'),
card('FP1_021',"Death's Bite",'WEAPON','WARRIOR',4,4,durability=2,kind='DEATHRATTLE',effects=[damage(1)],exp='NAXX',text='Deathrattle: Deal 1 damage to all minions.'),
card('EX1_132','Eye for an Eye','SPELL','PALADIN',1,kind='SECRET',trigger=t('DAMAGE',subject='HERO'),effects=[dict(damage(1,'OPPONENT_HERO'),amount={'kind':'EVENT_AMOUNT'})],text='Secret: When your hero takes damage, deal that much damage to the enemy hero.')]
for definition in cat['cards']:
 if definition['revision']=='foundation-v9' and 'SECRET' in definition['mechanics']:
  for effect in definition['abilities'][0]['effects']:
   if effect['op']=='DEAL_DAMAGE': effect['damageClass']='SPELL'
 if definition['cardId']=='EX1_132': definition['sources']=['https://hearthstone.blizzard.com/en-us/cards/462-eye-for-an-eye/']
(ROOT/'cards/foundation-v9.json').write_text(json.dumps(cat,indent=2)+'\n')
