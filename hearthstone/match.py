"""Managed matches for the supported foundation catalog; no UI or clocks."""
from copy import deepcopy

from .catalog import load
from .prototype import Prototype
from . import resources, rng


class MatchEngine(Prototype):
    def __init__(self, catalog=None, **kwargs):
        catalog = load() if catalog is None else catalog
        super().__init__(catalog, **kwargs)
        self.catalog_id = catalog['catalogId']

    @staticmethod
    def _player(player):
        if type(player) is not int or player not in (0, 1):
            raise ValueError('invalid player')

    def _managed(self, state):
        if not isinstance(state, dict) or state.get('match', {}).get('catalogId') != self.catalog_id:
            raise ValueError('use a managed state from new_game with this catalog')

    def play(self, state, player, source_id, target_id=None, position=None):
        self._managed(state)
        return super().play(state, player, source_id, target_id, position)

    def attack(self, state, player, attacker_id, defender_id):
        self._managed(state)
        return super().attack(state, player, attacker_id, defender_id)

    def new_game(self, decks, seed, first_player=None, deck_size=30, turn_limit=90, mana_cap=10,
                 hero_powers=None):
        """Set up a sandbox match; stop at both mulligan decisions.

        Deck size and collectible definitions are validated here. Constructed
        class/copy/format legality is a later stage; the profile records this.
        """
        if type(deck_size) is not int or not 4 <= deck_size <= 99:
            raise ValueError('deck_size must be an integer from 4 to 99')
        if type(turn_limit) is not int or turn_limit < 2:
            raise ValueError('turn_limit must be at least two')
        if not isinstance(decks, list) or len(decks) != 2:
            raise ValueError('provide two deck lists')
        if first_player is not None:
            self._player(first_player)
        state = self.state()
        state['rng'] = rng.new(seed)
        first = rng.randbelow(state['rng'], 2) if first_player is None else first_player
        state.update(match=dict(catalogId=self.catalog_id, profile='FOUNDATION_SANDBOX',
                                seed=seed, deckSize=deck_size, turnLimit=turn_limit,
                                resourcePolicy='CAPPED_TEMPORARY_MANA'),
                     phase='MULLIGAN', activePlayer=first, firstPlayer=first, turn=0,
                     playerTurns=[0, 0], cardsPlayedThisTurn=[0, 0],
                     resources=[resources.fresh(mana_cap), resources.fresh(mana_cap)])
        resources.sync(state)
        # Ensure setup's generated Coin can resolve before starting any game.
        self.entity('coin-check', 'GAME_005', 1 - first, 'HAND')
        # Old frozen catalogs remain usable without introducing new definitions.
        if hero_powers is None:
            hero_powers = ['CS2_034', 'CS2_034'] if any(k[0] == 'CS2_034' for k in self.cards) else [None, None]
        if not isinstance(hero_powers, list) or len(hero_powers) != 2:
            raise ValueError('provide two hero powers')
        state['heroPowers'] = [None, None]
        state['heroPowerUsesThisTurn'] = [0, 0]
        for player, reference in enumerate(hero_powers):
            if reference is None:
                continue
            if isinstance(reference, str):
                card_id, revision = reference, None
            elif isinstance(reference, dict) and set(reference) == {'cardId', 'revision'}:
                card_id, revision = reference['cardId'], reference['revision']
                if not isinstance(card_id, str) or not isinstance(revision, str):
                    raise ValueError('invalid hero power reference')
            else:
                raise ValueError('invalid hero power reference')
            power = self.entity(f'hero-power-{player}', card_id, player, revision=revision)
            if power['kind'] != 'HERO_POWER':
                raise ValueError('configured definition is not a hero power')
            state['heroPowers'][player] = power['id']
            state['entities'].append(power)
        for player, deck in enumerate(decks):
            if not isinstance(deck, list) or len(deck) != deck_size:
                raise ValueError('deck has the wrong size')
            for index, reference in enumerate(deck):
                if isinstance(reference, str):
                    card_id, revision = reference, None
                elif isinstance(reference, dict) and set(reference) == {'cardId', 'revision'}:
                    card_id, revision = reference['cardId'], reference['revision']
                    if not isinstance(card_id, str) or not isinstance(revision, str):
                        raise ValueError('invalid definition reference')
                else:
                    raise ValueError('invalid deck entry')
                entity_id = f'p{player}-card-{index}'
                entity = self.entity(entity_id, card_id, player, 'DECK', revision)
                if not self.definition(entity)['collectible']:
                    raise ValueError('starting decks require collectible cards')
                state['entities'].append(entity)
                state['decks'][player].append(entity_id)
            rng.shuffle(state['rng'], state['decks'][player])
        state['events'].append(dict(type='MATCH_SETUP', firstPlayer=first))
        for player in (first, 1 - first):
            self._draw(state, player, 3 if player == first else 4, None)
        hands = [[e['id'] for e in state['entities'] if e['zone'] == 'HAND' and e['controller'] == p]
                 for p in (0, 1)]
        state['mulligan'] = dict(initialHands=hands, choices=[None, None])
        return state

    def mulligan(self, state, player, replace):
        self._managed(state)
        self._player(player)
        if state['result'] is not None or state['phase'] != 'MULLIGAN':
            raise ValueError('not a mulligan decision')
        if state['mulligan']['choices'][player] is not None:
            raise ValueError('mulligan already submitted')
        if not isinstance(replace, list) or any(not isinstance(i, str) for i in replace) or len(set(replace)) != len(replace):
            raise ValueError('invalid mulligan selections')
        hand = state['mulligan']['initialHands'][player]
        if not set(replace) <= set(hand) or len(replace) > len(state['decks'][player]):
            raise ValueError('invalid mulligan selections or too few replacement cards')
        next_state = deepcopy(state)
        # Canonical hand order makes replacement-list order irrelevant.
        next_state['mulligan']['choices'][player] = [i for i in hand if i in replace]
        next_state['events'].append(dict(type='MULLIGAN_SUBMITTED', player=player, count=len(replace)))
        if any(c is None for c in next_state['mulligan']['choices']):
            return self._finish_reactions(next_state)
        for owner in (0, 1):
            marked = next_state['mulligan']['choices'][owner]
            for entity_id in marked:
                self._entity(next_state, entity_id)['zone'] = 'SET_ASIDE'
            if marked:
                self._draw(next_state, owner, len(marked), None)
                for entity_id in marked:
                    self._entity(next_state, entity_id)['zone'] = 'DECK'
                    next_state['decks'][owner].append(entity_id)
                rng.shuffle(next_state['rng'], next_state['decks'][owner])
        second = 1 - next_state['firstPlayer']
        coin = self.entity('setup-coin', 'GAME_005', second, 'HAND')
        next_state['entities'].append(coin)
        next_state['events'].append(dict(type='ADD_TO_HAND', player=second, entity=coin['id'], reason='SECOND_PLAYER_COIN'))
        self._start_turn(next_state, next_state['firstPlayer'])
        return self._finish_reactions(next_state)

    @staticmethod
    def _phase(state, phase):
        state['phase'] = phase
        state['events'].append(dict(type='PHASE', phase=phase, player=state['activePlayer'], turn=state['turn']))

    def _turn_triggers(self, state, player, kind):
        self._prepare_play_order(state)
        queue = []
        for entity in sorted((e for e in state['entities'] if e['kind'] == 'MINION'
                              and e['zone'] == 'PLAY' and e['controller'] == player
                              and not e.get('silenced', False)), key=lambda e: e['playOrder']):
            for ability in self.definition(entity)['abilities']:
                if ability['kind'] == kind:
                    queue.append((entity['id'], entity['playOrder'], entity['cardId'],
                                  entity['revision'], deepcopy(ability)))
        for entity_id, stamp, card_id, revision, ability in queue:
            source = self._entity(state, entity_id)
            if (source['zone'] != 'PLAY' or source.get('silenced', False)
                    or source['controller'] != player or source.get('playOrder') != stamp
                    or (source['cardId'], source['revision']) != (card_id, revision)):
                continue
            state['events'].append(dict(type='TURN_TRIGGER', phase=kind, source=entity_id, player=player))
            self._execute_effects(state, ability['effects'], player, entity_id)
            self._deaths(state)
            self._result(state)
            if state['result'] is not None:
                return

    def _start_turn(self, state, player):
        state['activePlayer'] = player
        state['turn'] += 1
        if state['turn'] >= state['match']['turnLimit']:
            state['result'] = 'DRAW'
            state['phase'] = 'FINISHED'
            state['events'].append(dict(type='TURN_LIMIT', turn=state['turn']))
            return
        self._phase(state, 'TURN_START')
        state['playerTurns'][player] += 1
        state['cardsPlayedThisTurn'][player] = 0
        state['heroPowerUsesThisTurn'][player] = 0
        self._expire_buffs(state, 'START_OF_TURN', player)
        if state['result'] is not None:
            return
        for entity in state['entities']:
            if entity['zone'] == 'PLAY' and entity['kind'] in ('HERO', 'MINION') and entity['controller'] == player:
                entity['ready'] = True
                entity['attacksThisTurn'] = 0
        resources.start_turn(state, player)
        self._turn_triggers(state, player, 'START_OF_TURN')
        if state['result'] is not None:
            return
        self._draw(state, player, 1, None)
        self._deaths(state)
        self._result(state)
        if state['result'] is None:
            self._phase(state, 'MAIN')

    def end_turn(self, state, player):
        self._managed(state)
        self._player(player)
        if state['result'] is not None or state['phase'] != 'MAIN' or state['activePlayer'] != player:
            raise ValueError('not an active decision point')
        next_state = deepcopy(state)
        self._phase(next_state, 'TURN_END')
        self._begin_reactions(next_state)
        self._turn_triggers(next_state, player, 'END_OF_TURN')
        if next_state['result'] is not None:
            return self._finish_reactions(next_state)
        self._expire_buffs(next_state, 'END_OF_TURN', player)
        if next_state['result'] is not None:
            return self._finish_reactions(next_state)
        resources.end_turn(next_state, player)
        for entity in next_state['entities']:
            until = entity.get('freezeUntil')
            if (entity['zone'] == 'PLAY' and until and until['player'] == player
                    and until['playerTurn'] <= next_state['playerTurns'][player]):
                if 'FROZEN' in entity['keywords']:
                    entity['keywords'].remove('FROZEN')
                entity.pop('freezeUntil')
                next_state['events'].append(dict(type='THAW', target=entity['id']))
        self._start_turn(next_state, 1 - player)
        return self._finish_reactions(next_state)

    def _expire_buffs(self, state, phase, player):
        for entity in state['entities']:
            kept = []
            for enchantment in entity['enchantments']:
                expiration = enchantment.get('expiration') if isinstance(enchantment, dict) else None
                due = expiration and expiration['phase'] == phase and (
                    expiration.get('turn', state['turn'] + 1) <= state['turn']
                    if phase == 'END_OF_TURN' else
                    expiration['player'] == player and expiration['playerTurn'] <= state['playerTurns'][player])
                if due:
                    state['events'].append(dict(type='BUFF_EXPIRED', target=entity['id'],
                                               source=enchantment['source'], phase=phase))
                else:
                    kept.append(enchantment)
            entity['enchantments'] = kept
        self._deaths(state)
        self._result(state)

    def hero_power(self, state, player, target_id=None):
        """Activate the configured power once per own turn; it is not a card play."""
        self._managed(state)
        self._player(player)
        if state['result'] is not None or state['phase'] != 'MAIN' or state['activePlayer'] != player:
            raise ValueError('not an active decision point')
        if state['heroPowerUsesThisTurn'][player] >= 1:
            raise ValueError('hero power already used this turn')
        power_id = state['heroPowers'][player]
        if power_id is None:
            raise ValueError('no hero power configured')
        next_state = deepcopy(state)
        self._refresh_stats(next_state)
        self._prepare_play_order(next_state)
        self._begin_reactions(next_state)
        power = self._entity(next_state, power_id)
        if power['kind'] != 'HERO_POWER' or power['zone'] != 'PLAY' or power['controller'] != player:
            raise ValueError('invalid hero power entity')
        card = self.definition(power)
        ability = card['abilities'][0]
        if any(e['op'] == 'SUMMON' and e['targetPlayer'] == 'EFFECT_CONTROLLER'
               for e in ability['effects']) and len(self.board(next_state, player)) >= 7:
            raise ValueError('hero power requires board space')
        target = self._bind_target(next_state, ability.get('targeting'), player, power_id, target_id)
        cost = card['baseStats']['manaCost']
        if resources.available(next_state['resources'][player]) < cost:
            raise ValueError('insufficient mana')
        resources.spend(next_state, player, cost)
        next_state['heroPowerUsesThisTurn'][player] += 1
        next_state['events'].append(dict(type='HERO_POWER', source=power_id, player=player))
        self._execute_effects(next_state, ability['effects'], player, power_id, target)
        self._deaths(next_state)
        self._result(next_state)
        return self._finish_reactions(next_state)

    def concede(self, state, player):
        self._managed(state)
        self._player(player)
        if state['result'] is not None:
            raise ValueError('match is already over')
        next_state = deepcopy(state)
        next_state['result'] = f'PLAYER_{1-player}_WINS'
        next_state['phase'] = 'FINISHED'
        next_state['events'].append(dict(type='CONCEDE', player=player))
        return self._finish_reactions(next_state)

    def _result(self, state):
        super()._result(state)
        if state['result'] is not None and 'match' in state:
            state['phase'] = 'FINISHED'

    def apply(self, state, player, action):
        if not isinstance(action, dict) or not isinstance(action.get('type'), str):
            raise ValueError('invalid action')
        fields = {'mulligan': ({'replace'}, set()), 'play': ({'source'}, {'target', 'position'}),
                  'hero_power': (set(), {'target'}),
                  'attack': ({'attacker', 'defender'}, set()),
                  'end_turn': (set(), set()), 'concede': (set(), set())}
        kind = action['type']
        if kind not in fields:
            raise ValueError('unsupported action')
        required, optional = fields[kind]
        keys = set(action) - {'type'}
        if not required <= keys or not keys <= required | optional:
            raise ValueError('invalid action fields')
        if kind == 'mulligan': return self.mulligan(state, player, action['replace'])
        if kind == 'play': return self.play(state, player, action['source'], action.get('target'), action.get('position'))
        if kind == 'hero_power': return self.hero_power(state, player, action.get('target'))
        if kind == 'attack': return self.attack(state, player, action['attacker'], action['defender'])
        if kind == 'end_turn': return self.end_turn(state, player)
        return self.concede(state, player)

    def begin_combat_turn(self, state, player):
        raise ValueError('managed matches refresh through end_turn only')

    def draw(self, state, player, count=1):
        raise ValueError('managed matches draw through turns and card effects only')

    def resolve_deaths(self, state):
        raise ValueError('managed matches settle deaths within player actions')
