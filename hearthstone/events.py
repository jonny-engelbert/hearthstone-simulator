"""Cheap state copies with immutable historical events and JSON-compatible logs.

Events are frozen once when appended. Copying a log copies only its list of
references, never the historical event dictionaries or nested payloads. The
list itself is independent in every state. JSON restore accepts ordinary lists.
"""

from copy import deepcopy


def _immutable(*args, **kwargs):
    raise TypeError(
        'historical events are immutable; export through JSON for editable data'
    )


class _FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = (
        __ior__
    ) = _immutable

    def __deepcopy__(self, memo):
        return self


class _FrozenList(list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = (
        _immutable
    )
    sort = reverse = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return self


def _freeze(value):
    if isinstance(value, (_FrozenDict, _FrozenList)):
        return value
    if isinstance(value, dict):
        return _FrozenDict((key, _freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze(item) for item in value)
    return value


class EventLog(list):
    """An independent mutable sequence of immutable JSON event payloads."""

    def __init__(self, events=()):
        super().__init__(_freeze(event) for event in events)

    def append(self, event):
        super().append(_freeze(event))

    def extend(self, events):
        super().extend(_freeze(event) for event in events)

    def insert(self, index, event):
        super().insert(index, _freeze(event))

    def __setitem__(self, index, value):
        super().__setitem__(
            index,
            (
                [_freeze(event) for event in value]
                if isinstance(index, slice)
                else _freeze(value)
            ),
        )

    def __iadd__(self, events):
        self.extend(events)
        return self

    def __deepcopy__(self, memo):
        copy = EventLog()
        memo[id(self)] = copy
        # Each payload is immutable, so references are safe across branches.
        list.extend(copy, self)
        return copy


def copy_state(state):
    """Copy mutable game state while sharing only frozen historical payloads."""
    result = deepcopy({key: value for key, value in state.items() if key != 'events'})
    events = state['events']
    result['events'] = (
        deepcopy(events) if isinstance(events, EventLog) else EventLog(events)
    )
    return result
