"""JSON-resumable, deterministic decision transactions.

Evaluate from a committed checkpoint to collect choices. A suspended action
publishes no partial effects/events; replay its pure prefix with saved answers,
then commit its complete output once. No Python stack/frame is serialized.
"""

from copy import deepcopy
import hashlib
import json

from .errors import ResolutionLimitError
from .events import copy_state


class ChoiceRequired(Exception):
    def __init__(self, request):
        self.request = request


def request_hash(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


class ChoiceTransactions:
    def _request_choice(self, state, player, source_id, kind, options):
        if 'match' not in state or '_choiceTransaction' not in state:
            raise ValueError('choices require a managed decision transaction')
        transaction = state['_choiceTransaction']
        index = transaction['cursor']
        if index >= self.max_choices:
            raise ResolutionLimitError('choice resolution budget exceeded')
        number = state.get('nextChoiceId', 1)
        state['nextChoiceId'] = number + 1
        request = dict(
            id=f'choice-{number}',
            player=player,
            source=source_id,
            kind=kind,
            options=deepcopy(options),
        )
        if index == len(transaction['answers']):
            raise ChoiceRequired(request)
        answer = transaction['answers'][index]
        if answer['requestHash'] != request_hash(request):
            raise ValueError('choice checkpoint no longer matches its request')
        transaction['cursor'] += 1
        option = next(
            (option for option in options if option['id'] == answer['option']), None
        )
        if option is None:
            raise ValueError('choice checkpoint contains an invalid option')
        state['events'].append(
            dict(
                type='CHOICE_RESOLVED',
                player=player,
                choice=kind,
                source=source_id,
                visibility='CONTROLLER_ONLY',
            )
        )
        return option

    def _run_decision(self, state, player, action, answers=None):
        # A copy of mutable state, not the engine, owns transaction bookkeeping.
        # Implementations copy before mutation; this outer shell adds only
        # private transaction inputs, avoiding a second full state copy.
        working = dict(state)
        working['_choiceTransaction'] = dict(answers=deepcopy(answers or []), cursor=0)
        try:
            result = self._perform(working, player, action)
        except ChoiceRequired as pause:
            # Keep the last committed board/resources/log, never half a death
            # batch or an interrupted reaction stack. Only the chooser sees offers.
            result = copy_state(state)
            result['phase'] = 'CHOICE'
            result['pendingChoice'] = pause.request
            result['continuation'] = dict(
                start=copy_state(state),
                player=player,
                action=deepcopy(action),
                answers=deepcopy(answers or []),
            )
            return result
        transaction = result.pop('_choiceTransaction')
        if transaction['cursor'] != len(transaction['answers']):
            raise ValueError('choice checkpoint has unused answers')
        return result

    def _validate_choice(self, state, player, choice_id, option_id):
        self._managed(state)
        self._player(player)
        request = state.get('pendingChoice')
        if state['result'] is not None or state['phase'] != 'CHOICE' or not request:
            raise ValueError('no pending choice')
        if request['player'] != player:
            raise ValueError('choice belongs to another player')
        if type(choice_id) is not str or choice_id != request['id']:
            raise ValueError('stale or invalid choice ID')
        if type(option_id) is not str or option_id not in {
            option['id'] for option in request['options']
        }:
            raise ValueError('invalid choice option')
        return request

    def choose(self, state, player, choice_id, option_id):
        request = self._validate_choice(state, player, choice_id, option_id)
        continuation = state['continuation']
        self._managed(continuation['start'])
        answer = dict(option=option_id, requestHash=request_hash(request))
        return self._run_decision(
            continuation['start'],
            continuation['player'],
            continuation['action'],
            continuation['answers'] + [answer],
        )
