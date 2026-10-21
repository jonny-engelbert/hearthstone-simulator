"""Board placement, fresh generated instances, and supported zone operations.

The entity store also supplies board order. Play chronology is the separate,
monotonically increasing playOrder stamp. No global counters or RNG are used.
"""

from . import rng


class ZoneOperations:
    @staticmethod
    def board(state, player):
        if type(player) is not int or player not in (0, 1):
            raise ValueError('invalid player')
        return [
            e
            for e in state['entities']
            if e['zone'] == 'PLAY'
            and e['kind'] == 'MINION'
            and e['controller'] == player
        ]

    def _place_minion(self, state, entity, position=None):
        board = [
            e
            for e in self.board(state, entity['controller'])
            if e['id'] != entity['id']
        ]
        position = len(board) if position is None else position
        if type(position) is not int or not 0 <= position <= len(board):
            raise ValueError('invalid minion position')
        state['entities'].remove(entity)
        if position < len(board):
            index = state['entities'].index(board[position])
        elif board:
            index = state['entities'].index(board[-1]) + 1
        else:
            index = len(state['entities'])
        state['entities'].insert(index, entity)

    def _generated(self, state, reference, player, source_id, zone):
        counter = state.get('nextEntityId', 1)
        if type(counter) is not int or counter < 1:
            raise ValueError('invalid nextEntityId')
        occupied = {e['id'] for e in state['entities']}
        while f'generated-{counter}' in occupied:
            counter += 1
        entity = self.entity(
            f'generated-{counter}',
            reference['cardId'],
            player,
            zone,
            reference['revision'],
        )
        state['nextEntityId'] = counter + 1
        entity['createdBy'] = source_id
        state['entities'].append(entity)
        state['events'].append(
            dict(
                type='GENERATED',
                entity=entity['id'],
                source=source_id,
                cardId=entity['cardId'],
                revision=entity['revision'],
                player=player,
            )
        )
        return entity

    def _reset_for_zone(self, entity, zone, player):
        # Bounce/shuffle retain instance identity and current definition, not buffs.
        fresh = self.entity(
            entity['id'], entity['cardId'], player, zone, entity['revision']
        )
        fresh['owner'] = entity['owner']
        if 'createdBy' in entity:
            fresh['createdBy'] = entity['createdBy']
        entity.clear()
        entity.update(fresh)

    def _clear_departed(self, entity):
        # Death snapshots retain last-known state. Graveyard diagnostics retain
        # damage/playOrder, while operative board modifiers and statuses are gone.
        entity['keywords'] = list(self.definition(entity)['keywords'])
        entity['enchantments'].clear()
        entity['silenced'] = False
        entity['pendingDestroy'] = False
        entity['ready'] = False
        entity.pop('freezeUntil', None)
        entity.pop('effectiveStats', None)

    @staticmethod
    def _effect_player(effect, player, recipient=None):
        choice = effect['targetPlayer']
        if choice == 'RECIPIENT_CONTROLLER':
            return recipient['controller']
        return 1 - player if choice == 'OPPONENT_OF_EFFECT_CONTROLLER' else player

    def _create_effect(self, state, effect, player, source_id, death_context):
        destination = self._effect_player(effect, player)
        if effect['op'] == 'ADD_CARD':
            for _ in range(effect['count']):
                entity = self._generated(
                    state, effect['definition'], destination, source_id, 'HAND'
                )
                # Count before adding this new card: the eleventh card is discarded.
                hand_size = sum(
                    e['zone'] == 'HAND' and e['controller'] == destination
                    for e in state['entities']
                )
                if hand_size > 10:
                    entity['zone'] = 'GRAVEYARD'
                    state['events'].append(
                        dict(
                            type='DISCARD',
                            entity=entity['id'],
                            player=destination,
                            reason='FULL_HAND',
                        )
                    )
                else:
                    state['events'].append(
                        dict(
                            type='ADD_TO_HAND',
                            entity=entity['id'],
                            player=destination,
                            reason='CARD_EFFECT',
                        )
                    )
            return
        placement = effect['placement']
        cursor = None
        if placement == 'RIGHT_OF_SOURCE':
            source = self._entity(state, source_id)
            if source not in self.board(state, destination):
                raise ValueError('summon placement source is not on this board')
            cursor = source_id
        if placement == 'DEATH_POSITION' and not death_context:
            raise ValueError('death placement requires a death snapshot')
        for _ in range(effect['count']):
            board = self.board(state, destination)
            if len(board) >= 7:
                state['events'].append(
                    dict(
                        type='SUMMON_FAILED',
                        source=source_id,
                        player=destination,
                        reason='FULL_BOARD',
                    )
                )
                continue
            slot_index = None
            if placement == 'RIGHT_OF_SOURCE':
                position = next(i for i, e in enumerate(board) if e['id'] == cursor) + 1
            elif placement == 'DEATH_POSITION':
                slots = death_context['slots']
                slot_index = slots.index(death_context['cursor']) + 1
                alive = {e['id'] for e in board}
                position = sum(i in alive for i in slots[:slot_index])
            else:
                position = len(board)
            entity = self._generated(
                state, effect['definition'], destination, source_id, 'PLAY'
            )
            self._place_minion(state, entity, position)
            self._stamp_enter(state, entity)
            if death_context:
                if slot_index is not None:
                    death_context['slots'].insert(slot_index, entity['id'])
                    death_context['cursor'] = entity['id']
                else:
                    # Keep the wave's virtual slots consistent with real placement.
                    following = board[position]['id'] if position < len(board) else None
                    slots = death_context['slots']
                    if following in slots:
                        slots.insert(slots.index(following), entity['id'])
                    else:
                        slots.append(entity['id'])
            cursor = entity['id']
            state['events'].append(
                dict(
                    type='SUMMON',
                    entity=entity['id'],
                    source=source_id,
                    player=destination,
                    position=position,
                    reason='CARD_EFFECT',
                )
            )
            self._refresh_stats(state)
            self._emit_reaction(state, 'AFTER_SUMMON', entity)

    def _move_effect(self, state, effect, targets, player, source_id):
        shuffle_players = set()
        if effect['op'] != 'RETURN_TO_HAND' and 'rng' not in state:
            raise ValueError('deck shuffles require a seeded RNG state')
        for entity in targets:
            destination = self._effect_player(effect, player, entity)
            if effect['op'] == 'SHUFFLE_COPIES':
                for _ in range(effect['count']):
                    if len(state['decks'][destination]) >= 99:
                        state['events'].append(
                            dict(
                                type='COPY_FAILED',
                                source=source_id,
                                player=destination,
                                reason='FULL_DECK',
                            )
                        )
                        continue
                    reference = dict(
                        cardId=entity['cardId'], revision=entity['revision']
                    )
                    copy = self._generated(
                        state, reference, destination, source_id, 'DECK'
                    )
                    state['decks'][destination].append(copy['id'])
                    state['events'].append(
                        dict(
                            type='COPY',
                            entity=copy['id'],
                            original=entity['id'],
                            policy='BASE_DEFINITION',
                        )
                    )
                    shuffle_players.add(destination)
                continue
            zone = 'HAND' if effect['op'] == 'RETURN_TO_HAND' else 'DECK'
            full = (
                sum(
                    e['zone'] == 'HAND' and e['controller'] == destination
                    for e in state['entities']
                )
                >= 10
                if zone == 'HAND'
                else len(state['decks'][destination]) >= 99
            )
            if full:
                entity['pendingDestroy'] = True
                state['events'].append(
                    dict(
                        type='ZONE_MOVE_FAILED',
                        source=source_id,
                        entity=entity['id'],
                        to=zone,
                        reason=f'FULL_{zone}',
                    )
                )
                continue
            self._reset_for_zone(entity, zone, destination)
            if zone == 'DECK':
                state['decks'][destination].append(entity['id'])
                shuffle_players.add(destination)
            state['events'].append(
                dict(
                    type='ZONE_CHANGE',
                    source=source_id,
                    entity=entity['id'],
                    fromZone='PLAY',
                    to=zone,
                    player=destination,
                )
            )
        for destination in sorted(shuffle_players):
            rng.shuffle(state['rng'], state['decks'][destination])
            state['events'].append(
                dict(
                    type='SHUFFLE',
                    source=source_id,
                    player=destination,
                    count=len(state['decks'][destination]),
                )
            )
