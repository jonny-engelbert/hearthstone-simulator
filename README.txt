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
