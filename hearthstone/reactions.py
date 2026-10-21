"""Bounded depth-first event delivery with immutable listener snapshots.

Queues are built at event time. Effect continuations run on an explicit stack,
so nested reactions do not consume the Python call stack. Death collection
remains a separate checkpoint after an outer effect phase.
"""

from copy import deepcopy

from .events import copy_state
from .errors import ResolutionLimitError


class ReactionScheduler:
    def _begin_reactions(self, state):
        state.setdefault('scheduler', dict(nextEventId=1))
        state['_reactionCount'] = 0

    @staticmethod
    def _finish_reactions(state):
        if state.get('_reactionPending') or state.get('_reactionDraining'):
            raise RuntimeError('unfinished reaction work at action boundary')
        state.pop('_reactionCount', None)
        return state

    @staticmethod
    def _subject(entity):
        return (
            None
            if entity is None
            else dict(
                id=entity['id'], kind=entity['kind'], controller=entity['controller']
            )
        )

    def _matches_reaction(self, state, source, ability, event, frame):
        rule = ability['trigger']
        subject = event['subject']
        actor = event.get('actor')
        if frame and event['type'] in ('BEFORE_ATTACK', 'AFTER_ATTACK'):
            subject = self._subject(self._entity(state, frame['defender']))
            actor = self._subject(self._entity(state, frame['attacker']))
        if rule['relation'] == 'SELF' and event['type'] in (
            'BEFORE_ATTACK',
            'AFTER_ATTACK',
        ):
            subject = actor
        if subject is None:
            return False
        wanted = rule['subjectKind']
        if (
            wanted != 'ANY'
            and not (wanted == 'CHARACTER' and subject['kind'] in ('HERO', 'MINION'))
            and subject['kind'] != wanted
        ):
            return False
        actor_kind = rule.get('actorKind', 'ANY')
        if actor_kind != 'ANY' and (
            actor is None
            or not (
                actor['kind'] == actor_kind
                or actor_kind == 'CHARACTER'
                and actor['kind'] in ('HERO', 'MINION')
            )
        ):
            return False
        relation = rule['relation']
        if relation == 'FRIENDLY' and subject['controller'] != source['controller']:
            return False
        if relation == 'ENEMY' and subject['controller'] == source['controller']:
            return False
        if relation == 'SELF':
            if source['kind'] == 'WEAPON':
                if (
                    not actor
                    or actor['kind'] != 'HERO'
                    or actor['controller'] != source['controller']
                ):
                    return False
            elif subject['id'] != source['id']:
                return False
        if rule.get('excludeSelf') and subject['id'] == source['id']:
            return False
        if event['type'] in ('DAMAGE', 'HEAL') and event['amount'] <= 0:
            return False
        if ability['kind'] == 'SECRET':
            if state['activePlayer'] == source['controller']:
                return False
            if frame and frame.get('countered'):
                return False
            if frame and event['type'] == 'BEFORE_ATTACK':
                defender = self._entity(state, frame['defender'])
                if (
                    defender['zone'] != 'PLAY'
                    or defender.get('pendingDestroy')
                    or self.current_health(state, defender) <= 0
                ):
                    return False
            for effect in ability['effects']:
                if effect['op'] == 'REDIRECT_ATTACK':
                    if len(self.board(state, source['controller'])) >= 7:
                        return False
                    attacker = self._entity(state, frame['attacker'])
                    if (
                        attacker['zone'] != 'PLAY'
                        or attacker.get('pendingDestroy')
                        or self.current_health(state, attacker) <= 0
                    ):
                        return False
                recipient = effect.get('recipient', {}).get('kind')
                if recipient in ('ATTACKER', 'DEFENDER'):
                    entity = self._entity(
                        state,
                        frame['attacker' if recipient == 'ATTACKER' else 'defender'],
                    )
                    if (
                        entity['zone'] != 'PLAY'
                        or entity.get('pendingDestroy')
                        or self.current_health(state, entity) <= 0
                    ):
                        return False
        return True

    def _emit_reaction(
        self, state, kind, subject, actor=None, amount=0, frame=None, eligible=None
    ):
        self._prepare_play_order(state)
        scheduler = state.setdefault('scheduler', dict(nextEventId=1))
        event = dict(
            type=kind,
            subject=self._subject(subject),
            actor=self._subject(actor),
            amount=amount,
            id=scheduler['nextEventId'],
        )
        scheduler['nextEventId'] += 1
        queue = []
        for source in sorted(
            (
                e
                for e in state['entities']
                if e['zone'] in ('PLAY', 'SECRET')
                and e['kind'] in ('MINION', 'WEAPON', 'SPELL')
                and not e.get('silenced', False)
            ),
            key=lambda e: e.get('playOrder', 0),
        ):
            if (
                eligible is not None
                and (source['id'], source.get('playOrder')) not in eligible
            ):
                continue
            for index, ability in enumerate(self.definition(source)['abilities']):
                if (
                    ability['kind'] not in ('TRIGGER', 'SECRET')
                    or ability['trigger']['event'] != kind
                ):
                    continue
                if ability['kind'] == 'SECRET' and source['zone'] != 'SECRET':
                    continue
                if ability['kind'] == 'TRIGGER' and source['zone'] != 'PLAY':
                    continue
                if self._matches_reaction(state, source, ability, event, frame):
                    queue.append(
                        dict(
                            source=source['id'],
                            stamp=source.get('playOrder'),
                            cardId=source['cardId'],
                            revision=source['revision'],
                            controller=source['controller'],
                            zone=source['zone'],
                            ability=deepcopy(ability),
                            index=index,
                            event=event,
                            frame=frame,
                        )
                    )
        if queue:
            state['events'].append(
                dict(
                    type='REACTION_WINDOW',
                    window=kind,
                    eventId=event['id'],
                    sources=[j['source'] for j in queue],
                )
            )
            state.setdefault('_reactionPending', []).extend(queue)

    def _queue_weapon_death(self, state, weapon):
        for ability in self.definition(weapon)['abilities']:
            if ability['kind'] == 'DEATHRATTLE':
                state.setdefault('_reactionPending', []).append(
                    dict(
                        source=weapon['id'],
                        controller=weapon['controller'],
                        stamp=weapon.get('playOrder'),
                        ability=deepcopy(ability),
                        event=dict(type='WEAPON_DEATH', amount=0),
                        frame=None,
                        lastKnown=True,
                    )
                )

    def _drain_reactions(self, state):
        if state.get('_reactionDraining'):
            return
        state.setdefault('scheduler', dict(nextEventId=1))
        state['_reactionDraining'] = True
        stack = []
        try:
            while stack or state.get('_reactionPending'):
                pending = state.pop('_reactionPending', [])
                stack.extend(reversed(pending))
                job = stack.pop()
                if 'effects' not in job:
                    source = self._entity(state, job['source'])
                    if not job.get('lastKnown'):
                        if (
                            source['zone'] != job['zone']
                            or source.get('playOrder') != job['stamp']
                            or source['controller'] != job['controller']
                            or (source['cardId'], source['revision'])
                            != (job['cardId'], job['revision'])
                            or source.get('silenced', False)
                        ):
                            continue
                        if not self._matches_reaction(
                            state, source, job['ability'], job['event'], job['frame']
                        ):
                            continue
                    state['_reactionCount'] = state.get('_reactionCount', 0) + 1
                    if state['_reactionCount'] > self.max_reactions:
                        raise ResolutionLimitError(
                            'reaction resolution budget exceeded'
                        )
                    if job['ability']['kind'] == 'SECRET':
                        source['zone'] = 'GRAVEYARD'
                        state['events'].append(
                            dict(
                                type='SECRET_REVEALED',
                                source=source['id'],
                                cardId=source['cardId'],
                            )
                        )
                    if job['ability']['kind'] == 'DEATHRATTLE':
                        state['events'].append(
                            dict(
                                type='DEATHRATTLE',
                                source=job['source'],
                                controller=job['controller'],
                                playOrder=job.get('stamp'),
                            )
                        )
                    state['events'].append(
                        dict(
                            type='REACTION',
                            source=job['source'],
                            event=job['event']['type'],
                            eventId=job['event'].get('id'),
                            kind=job['ability']['kind'],
                        )
                    )
                    job['effects'] = list(job['ability']['effects'])
                if not job['effects']:
                    continue
                effect, *remaining = job['effects']
                if remaining:
                    stack.append(dict(job, effects=remaining))
                self._execute_effects(
                    state,
                    [effect],
                    job['controller'],
                    job['source'],
                    reaction_context=job,
                    death_context=job.get('death_context'),
                )
        finally:
            state.pop('_reactionDraining', None)
            state.pop('_reactionPending', None)

    def _reaction_recipients(self, state, recipient, player, source_id, context):
        kind = recipient['kind']
        if kind == 'SELF':
            ids = [source_id]
        elif kind in ('CONTROLLER_HERO', 'OPPONENT_HERO'):
            p = player if kind == 'CONTROLLER_HERO' else 1 - player
            ids = [
                e['id']
                for e in state['entities']
                if e['kind'] == 'HERO' and e['controller'] == p
            ]
        elif kind == 'EVENT_TARGET':
            ids = [context['event']['subject']['id']]
        else:
            ids = [context['frame']['attacker' if kind == 'ATTACKER' else 'defender']]
        return [
            self._entity(state, i)
            for i in ids
            if self._entity(state, i)['zone'] == 'PLAY'
        ]

    def _reactive_attack(self, state, player, attacker_id, defender_id):
        next_state = copy_state(state)
        self._begin_reactions(next_state)
        self._prepare_play_order(next_state)
        self._refresh_stats(next_state)
        attacker = self._entity(next_state, attacker_id)
        stamp = attacker.get('playOrder')
        frame = dict(attacker=attacker_id, defender=defender_id)
        self._emit_reaction(
            next_state,
            'BEFORE_ATTACK',
            self._entity(next_state, defender_id),
            actor=attacker,
            frame=frame,
        )
        self._drain_reactions(next_state)
        self._deaths(next_state)
        self._result(next_state)
        attacker = self._entity(next_state, attacker_id)
        defender = self._entity(next_state, frame['defender'])
        if (
            next_state['result'] is not None
            or attacker['zone'] != 'PLAY'
            or defender['zone'] != 'PLAY'
            or attacker.get('playOrder') != stamp
        ):
            next_state['events'].append(
                dict(
                    type='ATTACK_CANCELLED',
                    attacker=attacker_id,
                    defender=frame['defender'],
                    reason=(
                        'MATCH_ENDED'
                        if next_state['result'] is not None
                        else 'SUBJECT_LEFT_PLAY'
                    ),
                )
            )
            return self._finish_reactions(next_state)
        attack_damage = self.current_attack(next_state, attacker)
        return_damage = (
            self.current_attack(next_state, defender)
            if defender['kind'] == 'MINION'
            else 0
        )
        weapon = (
            self.equipped_weapon(next_state, player)
            if attacker['kind'] == 'HERO'
            else None
        )
        attacker['attacksThisTurn'] += 1
        if 'STEALTH' in attacker['keywords']:
            attacker['keywords'].remove('STEALTH')
        next_state['events'].append(
            dict(type='ATTACK', attacker=attacker_id, defender=frame['defender'])
        )
        self._damage(next_state, defender, attack_damage, attacker_id, 'COMBAT')
        if return_damage > 0:
            self._damage(next_state, attacker, return_damage, defender['id'], 'COMBAT')
        self._drain_reactions(next_state)
        if weapon and weapon['zone'] == 'PLAY':
            weapon['durability'] -= 1
            next_state['events'].append(
                dict(
                    type='DURABILITY',
                    weapon=weapon['id'],
                    remaining=weapon['durability'],
                )
            )
            if weapon['durability'] == 0:
                self._destroy_weapon(next_state, weapon, 'EXHAUSTED')
        self._emit_reaction(
            next_state, 'AFTER_ATTACK', defender, actor=attacker, frame=frame
        )
        self._drain_reactions(next_state)
        self._deaths(next_state)
        self._result(next_state)
        return self._finish_reactions(next_state)
