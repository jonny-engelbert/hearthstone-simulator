"""One handler per validated operation; shared recipient and timing semantics."""

from copy import deepcopy
from dataclasses import dataclass

from . import resources


@dataclass
class EffectContext:
    player: int
    source_id: str
    target: dict | None = None
    death: dict | None = None
    reaction: dict | None = None


class EffectOperations:
    EFFECT_HANDLERS = {
        'COUNTER_SPELL': '_effect_counter_spell',
        'REDIRECT_ATTACK': '_effect_redirect_attack',
        'SUMMON': '_effect_summon',
        'ADD_CARD': '_effect_add_card',
        'GAIN_MANA': '_effect_gain_mana',
        'DESTROY_MANA': '_effect_destroy_mana',
        'UNLOCK_MANA': '_effect_unlock_mana',
        'DRAW_CARD': '_effect_draw_card',
        'RETURN_TO_HAND': '_effect_return_to_hand',
        'SHUFFLE_INTO_DECK': '_effect_shuffle_into_deck',
        'SHUFFLE_COPIES': '_effect_shuffle_copies',
        'TRANSFORM': '_effect_transform',
        'DESTROY': '_effect_destroy',
        'HEAL': '_effect_heal',
        'BUFF': '_effect_buff',
        'SILENCE': '_effect_silence',
        'FREEZE': '_effect_freeze',
        'DEAL_DAMAGE': '_effect_deal_damage',
        'RANDOM_DAMAGE': '_effect_random_damage',
        'ADD_RANDOM_CARD': '_effect_add_random_card',
        'DISCOVER': '_effect_discover',
        'CHOOSE_ONE': '_effect_choose_one',
    }
    # These operations already perform their own stat updates, or cannot
    # change board stats. Preserve the existing effect/reaction checkpoints.
    DIRECT_OPS = {
        'COUNTER_SPELL',
        'REDIRECT_ATTACK',
        'SUMMON',
        'ADD_CARD',
        'GAIN_MANA',
        'DESTROY_MANA',
        'UNLOCK_MANA',
        'DRAW_CARD',
    }

    def _execute_effects(
        self,
        state,
        effects,
        player,
        source_id,
        target=None,
        death_context=None,
        reaction_context=None,
    ):
        """Execute one ability atomically relative to death checkpoints."""
        context = EffectContext(
            player, source_id, target, death_context, reaction_context
        )
        for effect in effects:
            op = effect['op']
            handler = self.EFFECT_HANDLERS.get(op)
            if handler is None:
                raise ValueError(f'unsupported effect operation: {op}')
            getattr(self, handler)(state, effect, context)
            if op not in self.DIRECT_OPS:
                self._refresh_stats(state)
            if op != 'COUNTER_SPELL':
                self._drain_reactions(state)

    def _effect_targets(self, state, effect, context):
        recipient = effect['recipient']
        if recipient['kind'] == 'BOUND_TARGET':
            return (
                [context.target]
                if context.target and context.target['zone'] == 'PLAY'
                else []
            )
        if recipient['kind'] == 'RANDOM':
            candidates = [
                entity
                for entity in self.select(
                    state, recipient['selector'], context.player, context.source_id
                )
                if not entity.get('pendingDestroy')
                and self.current_health(state, entity) > 0
            ]
            chosen = self._random_pick(state, candidates)
            return [chosen] if chosen is not None else []
        if recipient['kind'] == 'QUERY':
            return self.select(
                state, recipient['selector'], context.player, context.source_id
            )
        return self._reaction_recipients(
            state, recipient, context.player, context.source_id, context.reaction
        )

    @staticmethod
    def _effect_amount(effect, context):
        return (
            effect['amount']['value']
            if effect['amount']['kind'] == 'CONSTANT'
            else context.reaction['event']['amount']
        )

    def _effect_counter_spell(self, state, effect, context):
        context.reaction['frame']['countered'] = True
        state['events'].append(dict(type='SPELL_COUNTERED', source=context.source_id))

    def _effect_redirect_attack(self, state, effect, context):
        frame = context.reaction['frame']
        old = frame['defender']
        self._create_effect(
            state,
            dict(
                op='SUMMON',
                definition=effect['definition'],
                count=1,
                placement='RIGHT_END',
                targetPlayer='EFFECT_CONTROLLER',
            ),
            context.player,
            context.source_id,
            None,
        )
        frame['defender'] = self.board(state, context.player)[-1]['id']
        state['events'].append(
            dict(
                type='ATTACK_REDIRECTED',
                source=context.source_id,
                before=old,
                after=frame['defender'],
            )
        )

    def _effect_summon(self, state, effect, context):
        self._create_effect(
            state, effect, context.player, context.source_id, context.death
        )

    def _effect_add_card(self, state, effect, context):
        self._create_effect(
            state, effect, context.player, context.source_id, context.death
        )

    @staticmethod
    def _effect_resource(state, effect, context):
        player = (
            context.player
            if effect['targetPlayer'] == 'EFFECT_CONTROLLER'
            else 1 - context.player
        )
        resources.change(state, player, effect)

    def _effect_gain_mana(self, state, effect, context):
        self._effect_resource(state, effect, context)

    def _effect_destroy_mana(self, state, effect, context):
        self._effect_resource(state, effect, context)

    def _effect_unlock_mana(self, state, effect, context):
        self._effect_resource(state, effect, context)

    def _effect_draw_card(self, state, effect, context):
        player = (
            context.player
            if effect['targetPlayer'] in ('EFFECT_CONTROLLER', 'CONTROLLER_AT_DEATH')
            else 1 - context.player
        )
        self._draw(state, player, effect['count'], context.source_id)

    def _effect_return_to_hand(self, state, effect, context):
        self._move_effect(
            state,
            effect,
            self._effect_targets(state, effect, context),
            context.player,
            context.source_id,
        )

    def _effect_shuffle_into_deck(self, state, effect, context):
        self._move_effect(
            state,
            effect,
            self._effect_targets(state, effect, context),
            context.player,
            context.source_id,
        )

    def _effect_shuffle_copies(self, state, effect, context):
        self._move_effect(
            state,
            effect,
            self._effect_targets(state, effect, context),
            context.player,
            context.source_id,
        )

    def _effect_transform(self, state, effect, context):
        for entity in self._effect_targets(state, effect, context):
            destination = effect['targetDefinition']
            replacement = self.entity(
                entity['id'],
                destination['cardId'],
                entity['controller'],
                revision=destination['revision'],
            )
            replacement['owner'] = entity['owner']
            if 'createdBy' in entity:
                replacement['createdBy'] = entity['createdBy']
            entity.clear()
            entity.update(replacement)
            self._stamp_enter(state, entity)
            state['events'].append(dict(type='TRANSFORM', target=entity['id']))

    def _effect_destroy(self, state, effect, context):
        for entity in self._effect_targets(state, effect, context):
            entity['pendingDestroy'] = True
            state['events'].append(
                dict(type='DESTROY', source=context.source_id, target=entity['id'])
            )

    def _effect_heal(self, state, effect, context):
        for entity in self._effect_targets(state, effect, context):
            amount = self._effect_amount(effect, context)
            restored = min(max(0, entity['damage']), amount)
            entity['damage'] -= restored
            state['events'].append(
                dict(
                    type='HEAL',
                    source=context.source_id,
                    target=entity['id'],
                    amount=restored,
                )
            )
            self._emit_reaction(state, 'HEAL', entity, amount=restored)

    def _effect_buff(self, state, effect, context):
        for entity in self._effect_targets(state, effect, context):
            enchantment = dict(
                kind='STAT_BUFF', source=context.source_id, **effect['modifiers']
            )
            if effect['duration'] != 'PERMANENT':
                if 'match' not in state:
                    raise ValueError('temporary buffs require managed turn timing')
                if effect['duration'] == 'END_OF_TURN':
                    enchantment['expiration'] = dict(
                        phase='END_OF_TURN', turn=state['turn']
                    )
                else:
                    enchantment['expiration'] = dict(
                        phase='START_OF_TURN',
                        player=context.player,
                        playerTurn=state['playerTurns'][context.player] + 1,
                    )
            entity['enchantments'].append(enchantment)
            state['events'].append(
                dict(
                    type='BUFF',
                    source=context.source_id,
                    target=entity['id'],
                    modifiers=deepcopy(effect['modifiers']),
                )
            )

    def _effect_silence(self, state, effect, context):
        for entity in self._effect_targets(state, effect, context):
            entity['silenced'] = True
            entity['keywords'].clear()
            entity.pop('freezeUntil', None)
            entity['enchantments'].clear()
            state['events'].append(
                dict(type='SILENCE', source=context.source_id, target=entity['id'])
            )

    def _effect_freeze(self, state, effect, context):
        if 'match' not in state:
            raise ValueError('Freeze requires managed turn timing')
        for entity in self._effect_targets(state, effect, context):
            self._freeze(state, entity, context.source_id)

    def _effect_deal_damage(self, state, effect, context):
        # Resolve recipients and bonus once for this batch, before any hits.
        targets = self._effect_targets(state, effect, context)
        amount = self._effect_amount(effect, context)
        if effect['damageClass'] == 'SPELL':
            amount += self.spell_damage(state, context.player)
        for entity in targets:
            self._damage(state, entity, amount, context.source_id)
