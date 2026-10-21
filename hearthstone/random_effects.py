"""Seeded random recipients, catalog pools and private generated cards."""

from . import rng
from .errors import ResolutionLimitError


class RandomEffects:
    def _random_pick(self, state, candidates):
        if 'rng' not in state:
            raise ValueError('random effects require a seeded RNG state')
        if not candidates:
            return None
        state['_randomCount'] = state.get('_randomCount', 0) + 1
        if state['_randomCount'] > self.max_random_steps:
            raise ResolutionLimitError('random resolution budget exceeded')
        return candidates[rng.randbelow(state['rng'], len(candidates))]

    def _card_pool(self, pool):
        cards = [
            card
            for card in self.cards.values()
            if card['collectible']
            and card['type'] == pool['cardType']
            and (not pool.get('classes') or set(card['classes']) & set(pool['classes']))
            and set(pool.get('keywords', [])) <= set(card['keywords'])
            and (
                'manaCost' not in pool
                or card['baseStats']['manaCost'] == pool['manaCost']
            )
        ]
        return [
            dict(cardId=card['cardId'], revision=card['revision'])
            for card in sorted(
                cards, key=lambda card: (card['cardId'], card['revision'])
            )
        ]

    def _private_card(self, state, reference, player, source_id):
        entity = self._generated(
            state, reference, player, source_id, 'HAND', private=True
        )
        full = (
            sum(
                e['zone'] == 'HAND' and e['controller'] == player
                for e in state['entities']
            )
            > 10
        )
        if full:
            entity['zone'] = 'GRAVEYARD'
        state['events'].append(
            dict(
                type='DISCARD' if full else 'ADD_TO_HAND',
                entity=entity['id'],
                player=player,
                reason='FULL_HAND' if full else 'CARD_EFFECT',
                visibility='CONTROLLER_ONLY',
            )
        )

    def _effect_add_random_card(self, state, effect, context):
        reference = self._random_pick(state, self._card_pool(effect['pool']))
        if reference is not None:
            self._private_card(state, reference, context.player, context.source_id)

    def _effect_discover(self, state, effect, context):
        if '_choiceTransaction' not in state:
            raise ValueError('choices require a managed decision transaction')
        pool = self._card_pool(effect['pool'])
        offers = []
        for index in range(min(3, len(pool))):
            reference = self._random_pick(state, pool)
            pool.remove(reference)
            offers.append(dict(id=f'option-{index}', definition=reference))
        if not offers:
            return
        chosen = self._request_choice(
            state, context.player, context.source_id, 'DISCOVER', offers
        )
        self._private_card(
            state, chosen['definition'], context.player, context.source_id
        )

    def _effect_choose_one(self, state, effect, context):
        if '_choiceTransaction' not in state:
            raise ValueError('choices require a managed decision transaction')
        chosen = self._request_choice(
            state, context.player, context.source_id, 'CHOOSE_ONE', effect['options']
        )
        self._execute_effects(
            state,
            chosen['effects'],
            context.player,
            context.source_id,
            context.target,
            context.death,
            context.reaction,
        )

    def _effect_random_damage(self, state, effect, context):
        hits = effect['hits']
        if effect['damageClass'] == 'SPELL':
            hits += self.spell_damage(state, context.player)
        # Prevent pathological hit counts even when all candidates are Immune.
        if hits > self.max_random_steps:
            raise ResolutionLimitError('random resolution budget exceeded')
        for _ in range(hits):
            candidates = [
                e
                for e in self.select(
                    state, effect['selector'], context.player, context.source_id
                )
                if not e.get('pendingDestroy') and self.current_health(state, e) > 0
            ]
            target = self._random_pick(state, candidates)
            if target is None:
                break
            self._damage(state, target, 1, context.source_id)
            self._drain_reactions(state)
            self._deaths(state)
