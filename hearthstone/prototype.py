"""Core rules interpreter used by managed matches and arranged conformance fixtures."""

from copy import deepcopy

from .events import EventLog, copy_state

from .catalog import validate
from . import resources
from .zones import ZoneOperations
from .reactions import ReactionScheduler
from .errors import ResolutionLimitError
from .effects import EffectOperations
from .random_effects import RandomEffects


class Prototype(ZoneOperations, ReactionScheduler, EffectOperations, RandomEffects):
    def __init__(
        self, catalog, max_deathrattles=1000, max_reactions=1000, max_random_steps=1000
    ):
        errors = validate(catalog)
        if errors:
            raise ValueError('\n'.join(errors))
        if type(max_deathrattles) is not int or max_deathrattles < 1:
            raise ValueError('max_deathrattles must be a positive integer')
        self.max_deathrattles = max_deathrattles
        if type(max_reactions) is not int or max_reactions < 1:
            raise ValueError('max_reactions must be a positive integer')
        self.max_reactions = max_reactions
        if type(max_random_steps) is not int or max_random_steps < 1:
            raise ValueError('max_random_steps must be a positive integer')
        self.max_random_steps = max_random_steps

        self.cards = {
            (c['cardId'], c['revision']): deepcopy(c) for c in catalog['cards']
        }

    def definition(self, entity):
        return self.cards[(entity['cardId'], entity['revision'])]

    def entity(self, entity_id, card_id, controller, zone='PLAY', revision=None):
        candidates = [
            c
            for (cid, rev), c in self.cards.items()
            if cid == card_id and (revision is None or rev == revision)
        ]
        if len(candidates) != 1:
            raise ValueError(
                'unknown or ambiguous definition; supply an exact revision'
            )
        card = candidates[0]
        entity = dict(
            id=entity_id,
            cardId=card_id,
            revision=card['revision'],
            owner=controller,
            controller=controller,
            zone=zone,
            kind=card['type'],
            damage=0,
            armor=0,
            ready=False,
            attacksThisTurn=0,
            keywords=list(card['keywords']),
            enchantments=[],
            silenced=False,
            pendingDestroy=False,
        )
        if card['type'] == 'WEAPON':
            entity['durability'] = card['baseStats']['durability']
        return entity

    @staticmethod
    def state():
        heroes = [
            dict(
                id=f'hero-{p}',
                kind='HERO',
                owner=p,
                controller=p,
                zone='PLAY',
                maxHealth=30,
                damage=0,
                armor=0,
                attack=0,
                ready=True,
                attacksThisTurn=0,
                keywords=[],
                enchantments=[],
            )
            for p in (0, 1)
        ]
        return dict(
            activePlayer=0,
            mana=[10, 10],
            entities=heroes,
            decks=[[], []],
            fatigue=[0, 0],
            nextPlayOrder=1,
            deathHistory=[],
            events=EventLog(),
            result=None,
        )

    def max_health(self, entity, state=None):
        if entity['kind'] == 'HERO':
            return entity['maxHealth']
        if state is not None:
            return self._computed_stats(state, entity)['health']
        return entity.get('effectiveStats', self._attached_stats(entity))['health']

    def _attached_stats(self, entity):
        stats = self.definition(entity)['baseStats']
        result = dict(attack=stats['attack'], health=stats['health'])
        for modifier in entity['enchantments']:
            # Earlier fixtures used strings as opaque annotations, not effects.
            if isinstance(modifier, str):
                continue
            if (
                not isinstance(modifier, dict)
                or modifier.get('kind') != 'STAT_BUFF'
                or any(
                    type(modifier.get(k)) is not int or modifier[k] < 0
                    for k in ('attack', 'health')
                )
            ):
                raise ValueError('unsupported stat enchantment')
            for key in result:
                result[key] += modifier[key]
        return result

    def _computed_stats(self, state, entity):
        result = self._attached_stats(entity)
        if entity['zone'] != 'PLAY':
            return result
        for source in state['entities']:
            if (
                source['zone'] != 'PLAY'
                or source['kind'] != 'MINION'
                or source.get('silenced', False)
            ):
                continue
            for aura in self.definition(source)['abilities']:
                if aura['kind'] != 'AURA':
                    continue
                if entity in self.select(
                    state, aura['selector'], source['controller'], source['id']
                ):
                    for key in result:
                        result[key] += aura['modifiers'][key]
        return result

    def spell_damage(self, state, player):
        """Read live friendly sources once per spell damage operation/batch."""
        return sum(
            self.definition(entity)['spellDamage']
            for entity in state['entities']
            if entity['zone'] == 'PLAY'
            and entity['kind'] == 'MINION'
            and entity['controller'] == player
            and not entity.get('silenced', False)
            and not entity.get('pendingDestroy', False)
            and 'SPELL_DAMAGE' in entity['keywords']
            and self.current_health(state, entity) > 0
        )

    def _effective_damage(self, state, entity):
        if entity['kind'] == 'HERO':
            return entity['damage']
        new_max = self.max_health(entity, state)
        old_max = entity.get('effectiveStats', self._attached_stats(entity))['health']
        return max(0, entity['damage'] + min(0, new_max - old_max))

    def current_health(self, state, entity):
        """Read effective Health without modifying caller state."""
        return self.max_health(entity, state) - self._effective_damage(state, entity)

    def _refresh_stats(self, state):
        # All supported auras add flat constants; no recursive stat dependency.
        updates = [
            (e, self._computed_stats(state, e))
            for e in state['entities']
            if e['kind'] == 'MINION' and e['zone'] == 'PLAY'
        ]
        for entity, stats in updates:
            previous = entity.get('effectiveStats', self._attached_stats(entity))
            old_damage = entity['damage']
            if stats['health'] < previous['health']:
                entity['damage'] = max(
                    0, entity['damage'] + stats['health'] - previous['health']
                )
            entity['effectiveStats'] = stats
            if previous != stats:
                state['events'].append(
                    dict(
                        type='STATS_CHANGED',
                        entity=entity['id'],
                        before=deepcopy(previous),
                        after=deepcopy(stats),
                        damageBefore=old_damage,
                        damageAfter=entity['damage'],
                    )
                )

    def select(self, state, selector, controller, source_id, policy=None):
        result = []
        for entity in state['entities']:
            if entity['zone'] != selector['zone']:
                continue
            kind = selector['entityKind']
            if kind == 'MINION' and entity['kind'] != 'MINION':
                continue
            if kind == 'CHARACTER' and entity['kind'] not in ('HERO', 'MINION'):
                continue
            if (
                selector['controller'] == 'OPPONENT_OF_EFFECT_CONTROLLER'
                and entity['controller'] == controller
            ):
                continue
            if (
                selector['controller'] == 'FRIENDLY'
                and entity['controller'] != controller
            ):
                continue
            if 'SELF' in selector.get('exclude', []) and entity['id'] == source_id:
                continue
            # Selected-target legality differs from area-effect eligibility.
            if policy:
                enemy = entity['controller'] != controller
                if enemy and ({'STEALTH', 'IMMUNE'} & set(entity['keywords'])):
                    continue
                if (
                    policy in ('SPELL_SELECTED_TARGET', 'HERO_POWER_SELECTED_TARGET')
                    and 'ELUSIVE' in entity['keywords']
                ):
                    continue
            result.append(entity)
        return result

    def _validate_play(self, state, player, source_id, target_id=None, position=None):
        if (
            type(player) is not int
            or player not in (0, 1)
            or state['result'] is not None
            or state['activePlayer'] != player
        ):
            raise ValueError('not an active decision point')
        if 'match' in state and state['phase'] != 'MAIN':
            raise ValueError('not in main phase')
        matches = [e for e in state['entities'] if e['id'] == source_id]
        if len(matches) != 1:
            raise ValueError('unknown or duplicate source')
        source = matches[0]
        if source['zone'] != 'HAND' or source['controller'] != player:
            raise ValueError('source is not in your hand')
        card = self.definition(source)
        if card['type'] not in ('MINION', 'SPELL', 'WEAPON'):
            raise ValueError('source is not a playable card')
        is_secret = 'SECRET' in card['mechanics']
        if is_secret:
            secrets = [
                e
                for e in state['entities']
                if e['zone'] == 'SECRET' and e['controller'] == player
            ]
            if len(secrets) >= 5 or any(
                e['cardId'] == source['cardId'] for e in secrets
            ):
                raise ValueError('Secret slots full or duplicate Secret')
        cost = card['baseStats']['manaCost']
        available = (
            resources.available(state['resources'][player])
            if 'resources' in state
            else state['mana'][player]
        )
        if available < cost:
            raise ValueError('insufficient mana')
        board = [
            e
            for e in state['entities']
            if e['zone'] == 'PLAY'
            and e['kind'] == 'MINION'
            and e['controller'] == player
        ]
        if card['type'] == 'MINION' and len(board) >= 7:
            raise ValueError('board is full')
        if position is not None and (
            card['type'] != 'MINION'
            or type(position) is not int
            or not 0 <= position <= len(board)
        ):
            raise ValueError('invalid minion position')
        kind = 'BATTLECRY' if card['type'] == 'MINION' else 'SPELL_EFFECT'
        ability = next((a for a in card['abilities'] if a['kind'] == kind), None)
        targeting = ability.get('targeting') if ability else None
        target = self._bind_target(state, targeting, player, source_id, target_id)
        if 'overload' in card and 'resources' not in state:
            raise ValueError('Overload requires a managed match resource state')
        return source, card, ability, target

    def play(self, state, player, source_id, target_id=None, position=None):
        """Return a new state; validation failures leave the input untouched."""
        next_state = copy_state(state)
        self._begin_reactions(next_state)
        self._refresh_stats(next_state)
        source, card, ability, target = self._validate_play(
            next_state, player, source_id, target_id, position
        )
        is_secret = 'SECRET' in card['mechanics']
        cost = card['baseStats']['manaCost']
        self._prepare_play_order(next_state)
        eligible = {
            (e['id'], e.get('playOrder'))
            for e in next_state['entities']
            if e['zone'] in ('PLAY', 'SECRET')
        }
        if 'resources' in next_state:
            resources.spend(next_state, player, cost)
        else:
            next_state['mana'][player] -= cost
        source['zone'] = 'PLAY' if card['type'] == 'MINION' else 'RESOLVING'
        if card['type'] == 'MINION':
            # A bounced entity is a fresh arrival with no previous attack rights.
            source['ready'] = False
            source['attacksThisTurn'] = 0
            self._place_minion(next_state, source, position)
            self._stamp_enter(next_state, source)
        if not is_secret:
            source.pop('privateTo', None)
        next_state['events'].append(dict(type='PLAY', source=source_id))
        if card['type'] == 'MINION':
            next_state['events'].append(
                dict(
                    type='SUMMON',
                    entity=source_id,
                    source=source_id,
                    player=player,
                    position=self.board(next_state, player).index(source),
                    reason='PLAY',
                )
            )
        if 'cardsPlayedThisTurn' in next_state:
            next_state['cardsPlayedThisTurn'][player] += 1
        frame = dict(countered=False)
        if card['type'] == 'SPELL':
            self._emit_reaction(next_state, 'BEFORE_SPELL', source, frame=frame)
            self._drain_reactions(next_state)
        self._emit_reaction(next_state, 'ON_CARD_PLAY', source, eligible=eligible)
        self._drain_reactions(next_state)
        self._deaths(next_state)
        if 'overload' in card and not frame['countered']:
            resources.overload(next_state, player, card['overload'])
        if card['type'] == 'WEAPON':
            self._equip(next_state, source)
        self._refresh_stats(next_state)
        if is_secret and not frame['countered']:
            source['zone'] = 'SECRET'
            self._stamp_enter(next_state, source)
            next_state['events'].append(
                dict(type='SECRET_SET', source=source_id, player=player)
            )
        if (
            ability
            and not frame['countered']
            and (card['type'] != 'MINION' or source['zone'] == 'PLAY')
        ):
            self._execute_effects(
                next_state, ability['effects'], player, source_id, target
            )
        self._deaths(next_state)
        self._emit_reaction(next_state, 'AFTER_CARD_PLAY', source, eligible=eligible)
        self._drain_reactions(next_state)
        if card['type'] == 'SPELL' and not frame['countered']:
            self._emit_reaction(next_state, 'AFTER_SPELL', source, eligible=eligible)
        if card['type'] == 'MINION' and source['zone'] == 'PLAY':
            self._emit_reaction(next_state, 'AFTER_SUMMON', source, eligible=eligible)
        self._drain_reactions(next_state)
        self._deaths(next_state)
        if card['type'] == 'SPELL' and source['zone'] != 'SECRET':
            source.pop('privateTo', None)
            source['zone'] = 'GRAVEYARD'
        self._result(next_state)
        return self._finish_reactions(next_state)

    def _bind_target(self, state, targeting, player, source_id, target_id):
        target = None
        if targeting:
            legal = self.select(
                state,
                targeting['selector'],
                player,
                source_id,
                targeting['legalityPolicy'],
            )
            mode = targeting['mode']
            if target_id is not None:
                target = next((e for e in legal if e['id'] == target_id), None)
                if target is None:
                    raise ValueError('illegal target')
            elif mode == 'REQUIRED' or (mode == 'REQUIRED_IF_AVAILABLE' and legal):
                raise ValueError('target required')
        elif target_id is not None:
            raise ValueError('unexpected target')
        return target

    @staticmethod
    def _entity(state, entity_id):
        matches = [e for e in state['entities'] if e['id'] == entity_id]
        if len(matches) != 1:
            raise ValueError('unknown or duplicate entity')
        return matches[0]

    @staticmethod
    def equipped_weapon(state, player):
        weapons = [
            e
            for e in state['entities']
            if e['kind'] == 'WEAPON'
            and e['zone'] == 'PLAY'
            and e['controller'] == player
        ]
        if len(weapons) > 1:
            raise ValueError('multiple weapons equipped')
        if weapons and weapons[0]['durability'] <= 0:
            raise ValueError('equipped weapon has no durability')
        return weapons[0] if weapons else None

    def _destroy_weapon(self, state, weapon, reason):
        self._queue_weapon_death(state, weapon)
        weapon['zone'] = 'GRAVEYARD'
        self._clear_departed(weapon)
        state['events'].append(
            dict(type='WEAPON_DESTROYED', weapon=weapon['id'], reason=reason)
        )

    def _equip(self, state, weapon):
        previous = self.equipped_weapon(state, weapon['controller'])
        if previous:
            self._destroy_weapon(state, previous, 'REPLACED')
        weapon['zone'] = 'PLAY'
        self._stamp_enter(state, weapon)
        state['events'].append(
            dict(type='EQUIP', weapon=weapon['id'], player=weapon['controller'])
        )

    def current_attack(self, state, entity):
        if entity['zone'] != 'PLAY':
            return 0
        if entity['kind'] == 'MINION':
            return self._computed_stats(state, entity)['attack']
        if entity['kind'] == 'HERO':
            amount = entity.get('attack', 0)
            if entity['controller'] == state['activePlayer']:
                weapon = self.equipped_weapon(state, entity['controller'])
                if weapon:
                    amount += self.definition(weapon)['baseStats']['attack']
            return amount
        return 0

    def begin_combat_turn(self, state, player):
        """Turn-runner primitive: refresh combat readiness/counts, not mana/draw.

        This is fixture setup until a full turn lifecycle exists, never a free
        player action. MatchEngine owns Freeze thawing and enchantment expiration.
        """
        if (
            type(player) is not int
            or player not in (0, 1)
            or state['result'] is not None
        ):
            raise ValueError('invalid combat turn')
        next_state = copy_state(state)
        self._refresh_stats(next_state)
        next_state['activePlayer'] = player
        for entity in next_state['entities']:
            if (
                entity['zone'] == 'PLAY'
                and entity['controller'] == player
                and entity['kind'] in ('HERO', 'MINION')
            ):
                entity['attacksThisTurn'] = 0
                entity['ready'] = True
        next_state['events'].append(dict(type='COMBAT_TURN_START', player=player))
        return self._finish_reactions(next_state)

    def attack(self, state, player, attacker_id, defender_id):
        """Resolve a normal declared attack atomically through the damage pipeline."""
        if (
            type(player) is not int
            or player not in (0, 1)
            or state['result'] is not None
            or state['activePlayer'] != player
        ):
            raise ValueError('not an active decision point')
        if 'match' in state and state['phase'] != 'MAIN':
            raise ValueError('not in main phase')
        attacker = self._entity(state, attacker_id)
        if attacker['controller'] != player or defender_id not in self.attack_targets(
            state, attacker_id
        ):
            raise ValueError('illegal attack')
        # Validate the referenced defender independently before consuming anything.
        self._entity(state, defender_id)
        return self._reactive_attack(state, player, attacker_id, defender_id)

    def _damage(self, state, entity, amount, source_id, damage_class=None):
        actual = amount
        if 'IMMUNE' in entity['keywords']:
            actual = 0
        elif amount > 0 and 'DIVINE_SHIELD' in entity['keywords']:
            entity['keywords'].remove('DIVINE_SHIELD')
            actual = 0
        absorbed = min(entity['armor'], actual)
        entity['armor'] -= absorbed
        entity['damage'] += actual - absorbed
        event = dict(
            type='DAMAGE', source=source_id, target=entity['id'], amount=actual
        )
        if damage_class:
            event['damageClass'] = damage_class
        state['events'].append(event)
        actor = next((e for e in state['entities'] if e['id'] == source_id), None)
        self._emit_reaction(state, 'DAMAGE', entity, actor=actor, amount=actual)

    def draw(self, state, player, count=1):
        """Resolve a draw sequence, e.g. from a future turn runner.

        This is an engine primitive, not a free player action. Opponent draws
        are allowed because effects may request them outside that player's turn.
        """
        if type(player) is not int or player not in (0, 1):
            raise ValueError('invalid player')
        if type(count) is not int or count < 1:
            raise ValueError('draw count must be a positive integer')
        if state['result'] is not None:
            raise ValueError('match is already over')
        next_state = copy_state(state)
        self._begin_reactions(next_state)
        self._draw(next_state, player, count, None)
        self._deaths(next_state)
        self._result(next_state)
        return self._finish_reactions(next_state)

    def _draw(self, state, player, count, source_id):
        # IDs, not entity-store order, determine the deck's top-to-bottom order.
        entities = {e['id']: e for e in state['entities']}
        if len(entities) != len(state['entities']):
            raise ValueError('duplicate instance IDs')
        deck_ids = [entity_id for deck in state['decks'] for entity_id in deck]
        if len(set(deck_ids)) != len(deck_ids):
            raise ValueError('duplicate deck entries')
        for owner, deck in enumerate(state['decks']):
            for entity_id in deck:
                entity = entities.get(entity_id)
                if (
                    not entity
                    or entity['zone'] != 'DECK'
                    or entity['controller'] != owner
                ):
                    raise ValueError('deck references a missing or incompatible entity')
        if {e['id'] for e in state['entities'] if e['zone'] == 'DECK'} != set(deck_ids):
            raise ValueError('deck order is missing a deck entity')
        heroes = [
            e
            for e in state['entities']
            if e['kind'] == 'HERO' and e['zone'] == 'PLAY' and e['controller'] == player
        ]
        if len(heroes) != 1:
            raise ValueError('drawing player must have exactly one hero in play')
        for _ in range(count):
            state['events'].append(
                dict(type='DRAW_ATTEMPT', player=player, source=source_id)
            )
            if not state['decks'][player]:
                state['fatigue'][player] += 1
                amount = state['fatigue'][player]
                state['events'].append(
                    dict(type='FATIGUE', player=player, amount=amount)
                )
                # Fatigue is not spell or Battlecry damage, even when a spell
                # or Battlecry initiated the failed draw. Never add Spell Damage.
                self._damage(state, heroes[0], amount, None, 'FATIGUE')
                continue
            entity = entities[state['decks'][player].pop(0)]
            hand_count = sum(
                e['zone'] == 'HAND' and e['controller'] == player
                for e in state['entities']
            )
            if hand_count >= 10:
                state['events'].append(
                    dict(
                        type='REVEAL',
                        player=player,
                        entity=entity['id'],
                        cardId=entity['cardId'],
                    )
                )
                entity['zone'] = 'GRAVEYARD'
                state['events'].append(
                    dict(
                        type='BURN',
                        player=player,
                        entity=entity['id'],
                        reason='FULL_HAND',
                    )
                )
            else:
                entity['zone'] = 'HAND'
                state['events'].append(
                    dict(type='DRAW', player=player, entity=entity['id'])
                )

    @staticmethod
    def _prepare_play_order(state):
        """Validate explicit entry stamps and reserve the next sequence number."""
        ids = [e['id'] for e in state['entities']]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate instance IDs')
        if (
            type(state.get('nextPlayOrder')) is not int
            or state.get('nextPlayOrder') < 1
        ):
            raise ValueError('invalid nextPlayOrder')
        stamps = [e['playOrder'] for e in state['entities'] if 'playOrder' in e]
        if any(type(n) is not int or n < 1 for n in stamps) or len(set(stamps)) != len(
            stamps
        ):
            raise ValueError('invalid or duplicate playOrder')
        state['nextPlayOrder'] = max(state['nextPlayOrder'], max(stamps, default=0) + 1)
        for entity in state['entities']:
            if (
                entity['zone'] == 'PLAY'
                and entity['kind'] in ('MINION', 'WEAPON')
                or entity['zone'] == 'SECRET'
            ) and 'playOrder' not in entity:
                raise ValueError('in-play entity requires an explicit playOrder')

    @staticmethod
    def _stamp_enter(state, entity):
        entity['playOrder'] = state['nextPlayOrder']
        state['nextPlayOrder'] += 1

    def resolve_deaths(self, state):
        """Fixture/engine checkpoint: drain deaths and Deathrattles to completion.

        This is not a player action. Normal play/attack/draw call the same drain.
        """
        if state['result'] is not None:
            raise ValueError('match is already over')
        next_state = copy_state(state)
        self._begin_reactions(next_state)
        self._deaths(next_state)
        self._result(next_state)
        return self._finish_reactions(next_state)

    def _deaths(self, state):
        self._drain_reactions(state)
        self._prepare_play_order(state)
        self._refresh_stats(state)
        resolved = 0
        while True:
            dead = sorted(
                (
                    e
                    for e in state['entities']
                    if e['kind'] == 'MINION'
                    and e['zone'] == 'PLAY'
                    and (
                        e.get('pendingDestroy', False)
                        or e['damage'] >= self.max_health(e)
                    )
                ),
                key=lambda e: e['playOrder'],
            )
            if not dead:
                return
            # Capture each dying minion and its queue before removing any of
            # the batch. Ownership, control, definition and board position are
            # last-known information, never re-read from a later board state.
            snapshots = []
            wave_boards = [[e['id'] for e in self.board(state, p)] for p in (0, 1)]
            for entity in dead:
                friendly_board = [
                    e
                    for e in state['entities']
                    if e['zone'] == 'PLAY'
                    and e['kind'] == 'MINION'
                    and e['controller'] == entity['controller']
                ]
                snapshot = dict(
                    entity=deepcopy(entity),
                    controllerAtDeath=entity['controller'],
                    position=friendly_board.index(entity),
                    abilities=(
                        []
                        if entity.get('silenced', False)
                        else deepcopy(
                            [
                                a
                                for a in self.definition(entity)['abilities']
                                if a['kind'] == 'DEATHRATTLE'
                            ]
                        )
                    ),
                )
                snapshots.append(snapshot)
            for entity in dead:
                entity['zone'] = 'GRAVEYARD'
                self._clear_departed(entity)
            state['deathHistory'].extend(deepcopy(snapshots))
            state['events'].append(
                dict(type='DEATH_BATCH', targets=[e['id'] for e in dead])
            )
            self._refresh_stats(state)
            # Drain this immutable wave before collecting deaths it creates.
            # Iteration rather than recursion bounds stack use for long chains.
            for snapshot in snapshots:
                source = snapshot['entity']
                controller = snapshot['controllerAtDeath']
                self._emit_reaction(state, 'MINION_DIED', source)
                for ability in snapshot['abilities']:
                    resolved += 1
                    if resolved > self.max_deathrattles:
                        raise ResolutionLimitError(
                            'Deathrattle resolution budget exceeded'
                        )
                    context = dict(slots=wave_boards[controller], cursor=source['id'])
                    state.setdefault('_reactionPending', []).append(
                        dict(
                            source=source['id'],
                            controller=controller,
                            stamp=source['playOrder'],
                            ability=deepcopy(ability),
                            event=dict(type='MINION_DIED', amount=0),
                            frame=None,
                            lastKnown=True,
                            death_context=context,
                        )
                    )
                state.setdefault('_reactionPending', []).sort(
                    key=lambda j: j.get('stamp', 0)
                )
                self._drain_reactions(state)

    def _result(self, state):
        dead = [
            e['controller']
            for e in state['entities']
            if e['kind'] == 'HERO' and e['damage'] >= e['maxHealth']
        ]
        if dead:
            state['result'] = 'DRAW' if len(dead) == 2 else f'PLAYER_{1-dead[0]}_WINS'

    def attack_targets(self, state, attacker_id):
        """Legal targets for supported normal combat, using execution's checks."""
        if 'match' in state and state['phase'] != 'MAIN':
            return []
        return self._combat_targets(state, attacker_id)

    def attack_limit(self, state, entity):
        # Counts belong to the character and survive keyword/weapon changes.
        keywords = set(entity['keywords'])
        if entity['kind'] == 'HERO':
            weapon = self.equipped_weapon(state, entity['controller'])
            if weapon:
                keywords.update(weapon['keywords'])
        return 2 if 'WINDFURY' in keywords else 1

    def _combat_targets(self, state, attacker_id, ignore_freeze=False):
        attacker = self._entity(state, attacker_id)
        keywords = set(attacker['keywords'])
        immediate = attacker['kind'] == 'MINION' and bool(keywords & {'CHARGE', 'RUSH'})
        if (
            state['result'] is not None
            or attacker['zone'] != 'PLAY'
            or attacker['kind'] not in ('MINION', 'HERO')
            or not (attacker.get('ready') or immediate)
            or attacker['controller'] != state['activePlayer']
        ):
            return []
        if (
            self.current_attack(state, attacker) <= 0
            or ('FROZEN' in keywords and not ignore_freeze)
            or 'CANT_ATTACK' in keywords
            or attacker.get('attacksThisTurn', 0) >= self.attack_limit(state, attacker)
            or self.current_health(state, attacker) <= 0
        ):
            return []
        enemies = [
            e
            for e in state['entities']
            if e['zone'] == 'PLAY'
            and e['kind'] in ('HERO', 'MINION')
            and e['controller'] != attacker['controller']
            and not ({'STEALTH', 'IMMUNE'} & set(e['keywords']))
            and self.current_health(state, e) > 0
        ]
        if (
            not attacker.get('ready')
            and 'RUSH' in keywords
            and 'CHARGE' not in keywords
        ):
            enemies = [e for e in enemies if e['kind'] == 'MINION']
        taunts = [
            e for e in enemies if e['kind'] == 'MINION' and 'TAUNT' in e['keywords']
        ]
        return [e['id'] for e in taunts or enemies]

    def _freeze(self, state, entity, source_id):
        # Adopt supplied KW-05 explicitly, including its after-any-attack rule.
        player = entity['controller']
        misses_current = (
            player == state['activePlayer']
            and entity.get('attacksThisTurn', 0) == 0
            and bool(self._combat_targets(state, entity['id'], ignore_freeze=True))
        )
        deadline = state['playerTurns'][player] + (0 if misses_current else 1)
        previous = entity.get('freezeUntil')
        if previous and previous['player'] == player:
            deadline = max(deadline, previous['playerTurn'])
        entity['freezeUntil'] = dict(player=player, playerTurn=deadline)
        if 'FROZEN' not in entity['keywords']:
            entity['keywords'].append('FROZEN')
        state['events'].append(
            dict(
                type='FREEZE',
                source=source_id,
                target=entity['id'],
                until=deepcopy(entity['freezeUntil']),
            )
        )
