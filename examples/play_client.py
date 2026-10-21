"""A transport-independent client plays a legal constructed game from views only."""

import json

from hearthstone.contracts import Session, validate
from hearthstone.match import MatchEngine


NEUTRALS = (
    'CS2_182',
    'CS2_179',
    'EX1_015',
    'EX1_096',
    'EX1_011',
    'CS2_222',
    'EX1_048',
    'CS2_124',
    'EX1_033',
    'EX1_046',
    'EX1_506',
    'FP1_002',
    'EX1_049',
    'UNG_072',
    'CS2_142',
)


def deck():
    return [card for card in NEUTRALS for _ in range(2)]


def choose(observation):
    """Client code: receives neither server state, RNG nor opponent private IDs."""
    actions = observation['legalActions']
    for kind in ('mulligan', 'choose', 'play', 'attack', 'hero_power', 'end_turn'):
        candidates = [a for a in actions if a['type'] == kind]
        if candidates:
            if kind == 'mulligan':
                return next(a for a in candidates if not a['replace'])
            if kind == 'attack':
                enemy = f"hero-{1 - observation['view']['player']}"
                return next(
                    (a for a in candidates if a['defender'] == enemy), candidates[0]
                )
            return candidates[0]
    return None


def run(seed=3):
    engine = MatchEngine()
    session = Session(
        engine,
        engine.new_constructed_game(
            [deck(), deck()],
            ['MAGE', 'PRIEST'],
            seed,
        ),
    )
    trace = []
    resumed = False
    for _ in range(2000):
        # The host polls both clients: the chooser can be off-turn.
        observations = [session.observe(player) for player in (0, 1)]
        for observation in observations:
            validate('observation', observation)
        if observations[0]['view']['result'] is not None:
            return observations[0]['view']['result'], trace, resumed
        for player, observation in enumerate(observations):
            action = choose(observation)
            if action is None:
                continue
            command = dict(
                apiVersion='1.0', sequence=observation['sequence'], action=action
            )
            # Restore on every pending choice, plus periodic ordinary decisions.
            if observation['view']['phase'] == 'CHOICE' or len(trace) % 17 == 0:
                session = Session.resume(
                    engine, json.loads(json.dumps(session.checkpoint()))
                )
                assert session.observe(player) == observation
                resumed |= observation['view']['phase'] == 'CHOICE'
            session.submit(player, command)
            trace.append(dict(player=player, command=command))
            break
        else:
            raise AssertionError('no client decision available')
    raise AssertionError('client example exceeded action budget')


if __name__ == '__main__':
    result, trace, resumed = run()
    print(
        f'{result}; {len(trace)} commands; pending-choice checkpoint resumed: {resumed}'
    )
