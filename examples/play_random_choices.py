"""Complete seeded stage-10 match, with private debug output kept locally."""

import json
from pathlib import Path

from hearthstone.match import MatchEngine
from tools.bench import random_game

ROOT = Path(__file__).resolve().parents[1]


def run(seed=8):
    state, trace, _ = random_game(MatchEngine(), seed)
    return state, trace


if __name__ == '__main__':
    state, actions = run()
    report = dict(
        debugOnly=True,
        seed=8,
        catalogId=state['match']['catalogId'],
        result=state['result'],
        turn=state['turn'],
        actions=actions,
        state=state,
    )
    destination = ROOT / 'outputs/stage10-demo.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(
        f"{state['result']}; {len(actions)} actions; private debug trace: {destination}"
    )
