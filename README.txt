Hearthstone simulator
====================
Headless Python rules engine with a deliberately limited historical card profile.
This is a conformance prototype, not complete or live-client-verified Hearthstone.

Run with Python 3.10+ from this folder:
  python3 -m pip install -r requirements.txt
  python3 -m hearthstone.catalog
  python3 -m hearthstone.manifest
  python3 -m unittest discover -s tests -q
  python3 -m examples.play_reactions
  python3 tools/bench.py --games 100 --seed 0

Project map
-----------
hearthstone/                 Rules, match actions, zones, resources, reactions
cards/foundation.json        The single current executable card catalog
schemas/catalog.schema.json The single current structural schema
cards/manifest.json          Current profile and catalog/schema hashes
tests/                      Behavioral and validation tests
examples/                   Seeded complete-game examples
outputs/                    Regenerated demo reports (ignored by git)
docs/requirements.txt       Execution contract
docs/test-plan.txt          Test strategy
docs/mechanics-coverage.txt Implemented mechanics and representative cards
docs/card-inventory.txt     Card IDs, names and origins
docs/roadmap.txt            Remaining milestones
docs/sources/               Original supplied documents, retained as evidence
CHANGELOG.txt               Concise changes and verification notes

Development policy: change the current catalog/schema/manifest in place. Git
history preserves earlier releases; no frozen per-stage copies or compatibility
branches. Card revision references identify definitions, not alternate engine rules.
Historical stage notes explain timing decisions; current code/tests take precedence.
Do not edit the supplied Google documents. Constructed deck legality, random
card effects and choices, and a pinned client-log conformance profile remain work.

Current public API
------------------
  from hearthstone.match import MatchEngine
  engine = MatchEngine()
  actions = engine.legal_actions(state, player)
  next_state = engine.apply(state, player, actions[0])
  visible = engine.view(next_state, player)

legal_actions returns concrete action dictionaries, including every mulligan
subset (at most 16), legal target and minion position. Concession is legal for
both players until the result is set. Views expose own hand and public entities,
counts and filtered events; full checkpoints/event logs contain private data.
Historical event payloads are immutable; JSON export produces ordinary editable
data. The log sequence is independent in each state. See docs/requirements.txt
and docs/test-plan.txt for the precise API/privacy and testing contracts.

Current: 52 definitions; schema 1.10; catalog foundation-v9.1.
Remaining: random effects/choices, deck legality/API contracts, pinned-profile
conformance (three planned stages, range two to four).

Publishing and CI
-----------------
Commit completed changes on a feature branch, then publish after local checks:
  python3 -m pip install -r requirements-dev.txt
  python3 tools/publish.py

The publisher requires a clean committed feature branch and stops if any catalog,
manifest, format, test or push check fails. Open/update its pull request afterward.
GitHub CI runs on pushes and pull requests: formatting/catalog checks and the full
suite on Python 3.10 and 3.13. Main requires passing CI and a pull request; merging
is an explicit decision. Use the workflow's manual input random_games=100 for a
larger invariant run. CI does not upload uncommitted files from your computer.
