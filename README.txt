Hearthstone simulator
====================

This project currently contains a working card-language conformance prototype:
51 historical fixture definitions, including reactions, Secrets and weapon scripts,
a strict JSON Schema, semantic
validation, a fixture interpreter, a managed match engine, and regression tests.
It is not yet a complete Hearthstone simulator or patch-37.0 implementation.

Project map
-----------
docs/sources/                 Unedited exports of the two supplied Google Docs
docs/requirements.txt          Reviewed definition and execution contract
docs/review-and-decisions.txt  Corrections, evidence, and unresolved questions
docs/test-plan.txt             Validation strategy, coverage, and next milestones
cards/foundation-v9.json       Current executable fixture catalog (51 entries)
cards/foundation-v8.json       Preserved stage-8 catalog (37 entries)
cards/foundation-v7.json       Preserved stage-7 catalog (23 entries)
cards/foundation-v6.json       Preserved stage-6 catalog (16 cards)
cards/foundation-v5.json       Preserved stage-5 catalog (14 cards)
cards/foundation-v4.json       Preserved stage-4 catalog (10 cards)
cards/foundation-v3.json       Preserved stage-3 catalog (9 cards)
cards/foundation-v2.json       Preserved stage-2 catalog (8 cards)
cards/foundation-v1.json       Preserved stage-1 catalog (7 cards)
cards/manifest-v9.json         Current version/profile and catalog/schema hashes
cards/manifest-v8.json         Preserved stage-8 hashes
cards/manifest-v7.json         Preserved stage-7 hashes
cards/manifest-v6.json         Preserved stage-6 hashes
cards/manifest-v5.json         Preserved stage-5 hashes
cards/manifest-v4.json         Preserved stage-4 hashes
cards/manifest-v3.json         Preserved stage-3 hashes
cards/manifest-v2.json         Preserved stage-2 hashes
cards/manifest.json            Preserved stage-1 hashes
schemas/catalog-v1.9.schema.json  Current schema, triggers/Secrets/interruptions
schemas/catalog-v1.8.schema.json  Preserved schema 1.8
schemas/catalog-v1.7.schema.json  Preserved schema 1.7
schemas/catalog-v1.6.schema.json  Preserved schema 1.6
schemas/catalog-v1.5.schema.json  Preserved schema 1.5
schemas/catalog-v1.4.schema.json  Preserved schema 1.4
schemas/catalog-v1.3.schema.json  Preserved schema 1.3
schemas/catalog-v1.2.schema.json  Preserved schema 1.2
schemas/catalog.schema.json   Preserved schema 1.1
hearthstone/catalog.py         Structural and semantic catalog validator
hearthstone/prototype.py       Core rules and legacy fixture interpreter
hearthstone/match.py           Managed setup, mulligans, turns and player actions
hearthstone/resources.py       Permanent/temporary mana and Overload
hearthstone/zones.py           Placement, generated IDs and zone cleanup
hearthstone/reactions.py       Bounded reaction stack and combat preparation
hearthstone/errors.py          Shared atomic resolution guards
hearthstone/rng.py             Serializable seeded setup RNG
tests/test_conformance.py      Stage-1 regression scenarios
tests/test_drawing.py          Draw, fatigue, burn and version regressions
tests/test_combat.py           Weapon, combat, durability and version regressions
tests/test_deaths.py           Ordered death waves, snapshots and nested resolution
tests/test_stats.py            Healing, additive buffs, auras and silence cleanup
tests/test_match.py            Setup, mulligans, turns, resources and full games
tests/test_keywords.py         Powers, keywords, thawing, expiration and replay
tests/test_zones.py            Summoning, generation, bounce/shuffle and replay
tests/test_reactions.py        Listeners, Secrets, weapons and interruption traces
examples/play_reactions.py     Stage-9 complete public-action game
outputs/stage9-demo.json       Saved stage-9 game trace
docs/card-inventory.txt        All 51 definitions with IDs, stages and types
examples/play_zones.py         Stage-8 public-action sandbox match demo
outputs/stage8-demo.json       Saved stage-8 game trace
examples/play_keywords.py      Stage-7 public-action sandbox match demo
outputs/stage7-demo.json       Saved stage-7 game trace
examples/play_match.py         Stage-6 public-API sandbox match demo
outputs/stage6-demo.json       Saved demo actions, final state and summary
requirements.txt              Python dependency declaration

Run from this project folder with Python 3.10 or later:

  python3 -m pip install -r requirements.txt
  python3 -m hearthstone.catalog
  python3 -m unittest discover -s tests -v

No downloads or external accounts are needed to run validation or tests.
The jsonschema dependency was already available in the development environment.

Start reading with docs/review-and-decisions.txt, then docs/requirements.txt.
The original source documents are retained as evidence; known errors in them
are not authoritative requirements. No linked Google document was edited.

Current validation result: 51 definitions accepted; 382 tests passed, 2026-10-20.
See docs/test-plan.txt for precisely what that result does and does not prove.

Stage 2 adds explicit deck order, per-player fatigue counters, multi-card draws,
and the ten-card hand cap. Draw into a full hand reveals/burns the top card;
empty decks deal escalating fatigue, including when the hand is full. Playing
Novice Engineer first frees its hand slot. See docs/drawing-stage2.txt for the
full contract, API examples, event semantics and requirements-to-test mapping.

Prototype.draw remains a fixture primitive. MatchEngine owns automatic draws
and rejects free draw/readiness-reset shortcuts. General reactive listeners
remain future work. To validate the previous catalog: python3 -m hearthstone.catalog cards/foundation-v1.json
To check its hashes: python3 -m hearthstone.manifest cards/manifest.json

Stage 3 adds Fiery War Axe (historical 2-mana 3/2), weapon replacement, normal
hero/minion attacks, simultaneous return damage, attack counts and durability.
Read docs/combat-stage3.txt for supported rules, examples and test mapping.
begin_combat_turn is a scoped fixture/turn-runner primitive, not a player action
or a complete turn lifecycle. Earlier catalogs, schemas and hashes are preserved.

Stage 4 adds Loot Hoarder, death snapshots, ordered Deathrattles and iterative
nested death waves. See docs/deaths-stage4.txt for the explicit wave policy,
requirements, limitations and tests. Normal play/attack/draw settle deaths via
the same resolver; resolve_deaths is a fixture/future-engine checkpoint.

Stage 5 adds Voodoo Doctor, Blessing of Kings, historical Stormwind Champion
and Spellbreaker. Positive permanent stat buffs and flat friendly minion auras
are computed separately, with explicit Health adjustment on max-Health loss.
See docs/stats-stage5.txt for rules/API/test coverage and docs/roadmap.txt for
the earlier planning estimate. Stage 9 is now complete; three planned stages remain.

Stage 6: use MatchEngine.new_game, then apply mulligan/play/attack/end_turn/
concede actions. Setup pauses for both mulligans. Full turns own mana refill,
readiness, start/end hooks, draws, temporary expiry, Overload and the turn limit.
See docs/match-stage6.txt for API examples, profile limitations and exact policies.

Run a complete deterministic example:
  python3 -m examples.play_match
This saves a local report in outputs/stage6-demo.json. Its repeated-card decks
are explicitly sandbox decks. Constructed class/copy/format rules are future work.

Stage 7 adds Fireblast, Lesser Heal, Wolfrider, Rabid Worgen, Windfury Harpy,
Frostbolt and historical Abusive Sergeant. Hero powers use a separate action
and once-per-own-turn usage counter. Match turns handle Freeze thawing and
timed minion buffs. See docs/keywords-stage7.txt for exact policies and API.

  python3 -m examples.play_keywords

This saves outputs/stage7-demo.json. Configure powers with
new_game(..., hero_powers=['CS2_034', 'CS1h_001']); default v7 uses Fireblast
for both players. Activate with engine.hero_power(state, player, target_id),
or apply(state, player, {'type': 'hero_power', 'target': 'hero-1'}).
Freeze follows the supplied KW-05 fixture policy; detailed timing is not
client-log verified. Temporary minion buffs expire at the current end of turn
or the effect controller's next start of turn. Older catalogs remain frozen.

Stage 8 adds ordered minion placement, token summons, generated hand cards,
bounce, clean deck copies and seeded shuffles. Fourteen new definitions include
Murloc Tidehunter, Mirror Image, Haunted Creeper, Youthful Brewmaster, Sap,
King Mukla, Gang Up, Recycle, Reinforce and their tokens. Read
docs/zones-stage8.txt for identity, cleanup, capacity and death-slot policies.
Board-state copying and general reactive listeners remain future work.

  python3 -m examples.play_zones

This saves outputs/stage8-demo.json. Minion plays accept an optional position:
  engine.play(state, player, source_id, target_id=None, position=0)
The same position field works with apply. Default v8 placement is the right
end; earlier frozen catalogs retain their older event and placement behavior.
The stage-7 example is now pinned to foundation-v7 to preserve its trace.

Stage 9 adds a bounded depth-first reaction scheduler, automatic spell and
attack interruption windows, five Secrets, six listening minions, a Defender
token and two scripted weapons. See docs/reactions-stage9.txt for the exact
ordering policy, requirements, test mapping and scope limits. Card inventory:
docs/card-inventory.txt. Historical stats and timing fixtures are explicit.

  python3 -m examples.play_reactions

This saves outputs/stage9-demo.json: counters, attack cancellation/redirection,
damage/heal reactions and weapon Deathrattles, driven by normal player actions.
Reactions resolve automatically. Returned states have no private pending work
and replay through JSON checkpoints. Constructor option max_reactions=1000
bounds an action's callbacks; limit errors leave input state unchanged.
Earlier stage-7/8 examples are pinned to their historical catalogs. Secret
state is still an omniscient debug view; per-player hidden views come later.
