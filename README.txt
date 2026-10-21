Hearthstone simulator
====================
Headless Python rules engine with a pinned Wild 11.0.0.24118 card-data subset.
This is a conformance prototype, not complete or live-client-verified Hearthstone.

Run with Python 3.10+ from this folder:
  python3 -m pip install -r requirements.txt
  python3 -m hearthstone.catalog
  python3 -m hearthstone.manifest
  python3 -m unittest discover -s tests -q
  python3 -m examples.play_reactions
  python3 -m examples.play_random_choices
  python3 -m examples.play_client
  python3 tools/bench.py --games 100 --seed 0

Project map
-----------
hearthstone/                 Rules, match actions, zones, resources, reactions
cards/foundation.json        The single current executable card catalog
schemas/catalog.schema.json Current executable card-language schema
schemas/integration.schema.json Versioned client/persistence contracts
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

Development policy: change the current catalog, schemas and manifest in place. Git
history preserves earlier releases; no frozen per-stage copies or compatibility
branches. Card revision references identify definitions, not alternate engine rules.
Historical stage notes explain timing decisions; current code/tests take precedence.
Do not edit the supplied Google documents. A pinned client-log conformance profile remains work.

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

Current: 60 definitions; schema 1.12; catalog foundation-v12.
Remaining: pinned-profile conformance (one planned stage; may split with scope).

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

Random effects and choices (stage 10)
------------------------------------
Random targets/cards use the saved seeded RNG. Discover and Choose One pause with
phase CHOICE. Read engine.view(state, player)['choice']; only its player sees the
offers. Resume using engine.choose(state, player, choice_id, option_id), or apply:
  {'type': 'choose', 'choice': 'choice-1', 'option': 'option-0'}
legal_actions includes those concrete choices. Other actions wait; either player
can concede. The private execution root stays committed, while views project the resolved
prefix at Discover: cost paid, card placed, earlier effects/events visible.
Root Choose One remains a private pre-play decision; the opponent view stays
unchanged. Choosing replays and commits the result exactly once. Prefixes and
nested/off-turn choices round-trip through private checkpoints (version 2.0).

Discover uses the current supported catalog, not all Hearthstone cards. Stonehill
uses uniform Neutral Taunt offers; Wrath branches share its selected target.
Book/Stonehill stats follow pinned build 24118 (1/1 and 1/4). See requirements.txt
for the explicit profile and protocol limits. Generated/Discovered hand cards,
unchosen offers and full-hand generated discards stay private. Example output
outputs/stage10-demo.json is an omniscient debug trace and must not be sent to
players; use view for client data.

Constructed games and clients (stage 11)
----------------------------------------
  from hearthstone.contracts import Session
  state = engine.new_constructed_game([deck0, deck1], ['MAGE', 'PRIEST'], seed=3)
  session = Session(engine, state)
  observation = session.observe(player)
  command = {'apiVersion': '2.0', 'sequence': observation['sequence'],
             'action': observation['legalActions'][0]}
  observation = session.submit(player, command)

FOUNDATION_CONSTRUCTED_V1 supports Mage, Priest and Paladin: exactly 30 collectible
class/Neutral cards, two copies per cardId, one Legendary. The current catalog
fingerprint pins the format pool. Hero powers follow the classes. This historical
format does not claim Standard/Wild legality. new_game remains a sandbox for
arranged tests. contract() describes versions, limits and the exact format pool.

Client commands/observations use integration schema 2.0. The host supplies player
identity and serializes submissions; stale sequences are rejected atomically.
Send observe(player) to clients. Session.checkpoint() belongs in private server
storage; Session.resume(engine, checkpoint) restores JSON with exact catalog,
rules and budget compatibility checks. Private checkpoints expose both decks,
RNG and pending offers. They must never be used as player observations. See
requirements.txt for versioning, privacy, trust and persistence limits.

Pinned profile and review decisions
-----------------------------------
Card values target Wild build 11.0.0.24118, HearthSim/hsdata commit
  af94b04fdff91a1900f4adfc873d89c76aa298cd
  https://github.com/HearthSim/hsdata/blob/af94b04fdff91a1900f4adfc873d89c76aa298cd/CardDefs.xml
All 49 collectibles existed in that build. Wild retains rotated cards. The
manifest pins the source and extracted-facts hashes; docs/card-profile-audit.txt
lists every old/profile value. docs/review-and-decisions.txt explains profile
selection, choice timing and rules policies that still need client-log evidence.
This pins data; it does not claim full client parity. API/checkpoints are now 2.0.

The default random-game budget is 1; HS_RANDOM_GAMES=100 enables the extended
workload (also the manual CI workflow default). Time the complete suite with
python3 tools/time_tests.py. See docs/performance-review.txt for before/after
measurements and the 15 slowest tests. No distinct-rule tests were removed.
