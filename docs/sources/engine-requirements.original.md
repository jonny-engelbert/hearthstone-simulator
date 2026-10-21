# **Hearthstone Game Engine: Requirements Specification**

Oct 19, 2026 · @Jon

This spec turns Hearthstone's rules into numbered, testable requirements for a headless engine, current to patch 37.0. Read sections 2 to 12 as the rules, 13 to 15 as how to build and test them, and 16 as what is still unknown. Each requirement has an ID (`AREA-nn`), a strength (MUST, SHOULD, MAY) and a confidence tag explained in section 1\.

## **1\. Scope, assumptions and conventions**

This spec defines a headless rules engine for 1v1 constructed Hearthstone (Standard and Wild) that a later build step can turn into code. No official rulebook exists, so every rule below is derived from community documentation and Blizzard announcements and carries a confidence tag.

**In scope:** match setup, turns, resources, all card types, combat, effect resolution and death processing, auras and enchantments, keywords, secrets/quests/locations, deck validation by format, card data format, determinism and test requirements.

**Out of scope:** UI and animation, networking and reconnection, matchmaking and ranked stars, collection and progression, and other modes (Battlegrounds, Duels, Mercenaries, Arena drafting, Tavern Brawl rules).

**Assumptions (change these and the spec changes):**

* The engine is a language-agnostic library with no I/O; the first implementation language is not yet chosen.  
* Card behavior is data-driven: the engine implements a fixed set of primitives, and cards are scripted from them (section 13).  
* The reference behavior is the live game as of patch 37.0 (October 13, 2026); where sources only describe older patches, the requirement is tagged accordingly.  
* Full card-pool coverage is a content task, not an engine task. The engine must be able to express any card, but this spec does not enumerate cards.

**Conventions:** requirement IDs read `AREA-nn`. MUST means the engine is wrong without it; SHOULD means expected but deferrable. Confidence tags:

| Tag | Meaning |
| ----- | ----- |
| \[C\] | Confirmed by two or more independent sources |
| \[S\] | Single source, not contradicted |
| \[O\] | Observed community behavior, last verified against patch 9.2.0.21517 or earlier; verify in the live client |
| \[?\] | Unknown or contradicted; listed again in section 16 |

**Sources used (all opened):**

| Source | Used for | Reliability |
| ----- | ----- | ----- |
| [Blizzard: Card Sets](https://hearthstone.blizzard.com/en-us/expansions-adventures) | Standard/Wild set membership | Official |
| [Blizzard: Patch 37.0 notes](https://hearthstone.blizzard.com/en-us/news/24301454/370-patch-notes) | Current patch, formats | Official |
| [Blizzard: Reign of the Black Empire](https://hearthstone.blizzard.com/en-us/expansions-adventures/reign-of-the-black-empire) | Assemble, Old Gods | Official |
| [Blizzard: Core Set and Classic announcement](https://news.blizzard.com/en-us/article/23620129/introducing-the-core-set-and-classic-format) | Core/Legacy/Classic definitions | Official, 2021 |
| [Hearthstone Wiki: Gameplay](https://hearthstone.wiki.gg/wiki/Gameplay) and [Match](https://hearthstone.wiki.gg/wiki/Match) | Core loop, limits, timers | Community |
| [Hearthstone Wiki: Minions](https://hearthstone.wiki.gg/wiki/Minions) | Board limit, exhaustion, positioning | Community |
| [Hearthstone Wiki: Secret](https://hearthstone.wiki.gg/wiki/Secret) | Secret rules | Community |
| [Advanced rulebook (wiki.gg)](https://hearthstone.wiki.gg/wiki/Dominant_Player) and [(Fandom)](https://hearthstone.fandom.com/wiki/Advanced_rulebook) | Resolution order, death phases | Community, stale |
| [Icy Veins mechanics guide](https://www.icy-veins.com/hearthstone/mechanics-guide) | Cross-check of basics | Community, 2016 |

Mechanic pages also opened on the Hearthstone Wiki: [Mana cost](https://hearthstone.wiki.gg/wiki/Mana_cost), [Mana Crystal](https://hearthstone.wiki.gg/wiki/Mana_Crystal), [Overload](https://hearthstone.wiki.gg/wiki/Overload), [Fatigue](https://hearthstone.wiki.gg/wiki/Fatigue), [Armor](https://hearthstone.wiki.gg/wiki/Armor), [Hero Power](https://hearthstone.wiki.gg/wiki/Hero_Power), [Weapon](https://hearthstone.wiki.gg/wiki/Weapon), [Hero card](https://hearthstone.wiki.gg/wiki/Hero_card), [Location](https://hearthstone.wiki.gg/wiki/Location), [Summon](https://hearthstone.wiki.gg/wiki/Summon), [Mulligan](https://hearthstone.wiki.gg/wiki/Mulligan), [Aura](https://hearthstone.wiki.gg/wiki/Aura), [Enchantment](https://hearthstone.wiki.gg/wiki/Enchantment), [Silence](https://hearthstone.wiki.gg/wiki/Silence), [Transform](https://hearthstone.wiki.gg/wiki/Transform), [Taunt](https://hearthstone.wiki.gg/wiki/Taunt), [Stealth](https://hearthstone.wiki.gg/wiki/Stealth), [Immune](https://hearthstone.wiki.gg/wiki/Immune), [Divine Shield](https://hearthstone.wiki.gg/wiki/Divine_Shield), [Poisonous](https://hearthstone.wiki.gg/wiki/Poisonous), [Lifesteal](https://hearthstone.wiki.gg/wiki/Lifesteal), [Freeze](https://hearthstone.wiki.gg/wiki/Freeze), [Rush](https://hearthstone.wiki.gg/wiki/Rush), [Windfury](https://hearthstone.wiki.gg/wiki/Windfury), [Reborn](https://hearthstone.wiki.gg/wiki/Reborn), [Battlecry](https://hearthstone.wiki.gg/wiki/Battlecry), [Deathrattle](https://hearthstone.wiki.gg/wiki/Deathrattle), [Choose One](https://hearthstone.wiki.gg/wiki/Choose_One), [Discover](https://hearthstone.wiki.gg/wiki/Discover), [Spell Damage](https://hearthstone.wiki.gg/wiki/Spell_Damage), [Combo](https://hearthstone.wiki.gg/wiki/Combo), [Echo](https://hearthstone.wiki.gg/wiki/Echo), [Tradeable](https://hearthstone.wiki.gg/wiki/Tradeable), [Magnetic](https://hearthstone.wiki.gg/wiki/Magnetic), [Dormant](https://hearthstone.wiki.gg/wiki/Dormant), [Quest (ability)](https://hearthstone.wiki.gg/wiki/Quest_\(ability\)), [Deck](https://hearthstone.wiki.gg/wiki/Deck), [Wild format](https://hearthstone.wiki.gg/wiki/Wild_format), [Standard format](https://hearthstone.wiki.gg/wiki/Standard_format), [Keywords](https://hearthstone.wiki.gg/wiki/Keywords); and [Fandom: Ability](https://hearthstone.fandom.com/wiki/Ability).

## **2\. Domain model**

The game state is a flat store of entities, each with a zone, a controller and a set of typed tags; every later rule reads and writes those tags.

**Zones**

| Zone | Holds | Notes |
| ----- | ----- | ----- |
| Deck | Cards not yet drawn | Ordered, hidden from both players |
| Hand | Cards held | Max 10, hidden from the opponent |
| Play | Minions and locations (shared 7 slots), hero, hero power, weapon | Minions and locations are positioned left to right |
| Secret | Secrets and quests | Hidden from the opponent; separate from the board |
| Graveyard | Dead minions, spent spells, destroyed weapons | Needed for resurrect and Avenge-style effects |
| Set-aside | Tokens and cards in limbo (for example, a Choose One option) | Not part of any player's resources |
| Removed | Cards removed from the game | Cannot be returned |

**Requirements**

* DOM-01 MUST: every entity (card, hero, hero power, enchantment, token, dormant permanent) has a unique, stable ID, and every entity entering play receives a strictly increasing play-order stamp. Re-entering play (bounce and replay, resurrect) assigns a new stamp. Trigger queues are sorted by this stamp (section 7). \[O\]  
* DOM-02 MUST: ownership and control are separate tags. Owner is the player whose card it began as; controller is the player who currently controls it. Effects always use the current controller and have no memory of earlier board states, except effects that store a caster. \[O\]  
* DOM-03 MUST: a character is a hero or a minion. Only characters can be attacked, damaged, healed or frozen. Weapons, locations, secrets and hero powers are not characters. \[S\]  
* DOM-04 MUST: Health is stored as max Health plus accumulated damage, never as a single number. Raising max Health by an enchantment raises current Health by the same amount; lowering max Health caps current Health at the new max but never raises it. \[S\]  
* DOM-05 MUST: base values (cost, Attack, max Health, durability) live on the card definition; all current values are computed from base plus modifiers (section 8). \[S\]  
* DOM-06 MUST: when an entity leaves play by any route (death, return to hand, shuffle into deck), all enchantments and status effects on it are removed. Cost enchantments placed on a card in the deck persist when it is drawn; cost enchantments on a card in hand are removed when it is played. \[S\]  
* DOM-07 MUST: card definitions carry type, class or classes, tribes (zero or more), spell school (zero or one), rarity, set, collectible flag, cost, stats, keyword list, and a script reference (section 13).  
* DOM-08 MUST: each hero starts at 30 Health and 0 Armor, and has exactly one hero power and at most one weapon. \[C\]  
* DOM-09 MUST: each player tracks available mana, permanent crystals, temporary mana, locked (overloaded) crystals, pending overload, fatigue counter, cards played this turn, and per-game counters that cards query (for example, minions that died this game). \[S\]  
* DOM-10 MUST: the engine exposes a per-player view that hides the opponent's hand, deck order and secret identities, while exposing counts, and exposes a full omniscient view for tests and replays.  
* DOM-11 SHOULD: dormant minions and starship-style permanents are modelled as a permanent entity that is neither a character nor targetable until it awakens. \[S\]

## **3\. Match setup and turn flow**

A match is a coin toss, a 3-or-4-card mulligan, and then alternating turns until a hero dies, a player concedes, or turn 90 begins.

**Setup**

* MATCH-01 MUST: the first player is chosen by the engine's injected RNG, never by a global random call. \[C\]  
* MATCH-02 MUST: each deck is shuffled, then the first player is dealt 3 cards and the second player 4 from the top. \[C\]  
* MATCH-03 MUST: both players mark any subset of their opening cards to replace, without seeing the other's choice. Replacements come from the top of the remaining deck, so a card marked away cannot come back in that mulligan. When the mulligan ends, if any card was replaced, the replaced cards are shuffled back and the deck is reshuffled. \[S\]  
* MATCH-04 MUST: after the mulligan, the second player receives The Coin, a 0-cost spell that grants 1 temporary mana crystal for that turn. \[C\]  
* MATCH-05 SHOULD: Quest cards in a deck are guaranteed to appear in the opening mulligan hand. \[S\]  
* MATCH-06 MUST: in-hand effects are live during the mulligan (a cost reduction on a card in the opening hand is already applied). \[S\]

**Turn sequence (active player)**

1. **Handover.** Increment the turn counter. Expired enchantments wear off, per-turn counters reset, exhaustion clears on the active player's minions and hero power, weapons and secrets flip to the active side. \[O\]  
2. **Mana.** Gain one permanent crystal (also on turn 1\) up to the cap, refill all unlocked crystals, convert pending overload to locked crystals. \[S\]  
3. **Start-of-turn triggers.** Queue and resolve in order of play, with a death and win check after each. \[O\]  
4. **Draw.** The active player draws one card (fatigue rules in section 4). \[C\]  
5. **Main phase.** Any number of player actions in any order, limited by mana, attack counts and board state (section 5 and 6).  
6. **End of turn.** Queue and resolve end-of-turn triggers, then run the death and win check. Then remove until-end-of-turn enchantments and temporary mana, thaw per the Freeze rules (section 9), and hand over to the opponent. \[O\]

**Turn limit and end of match**

* MATCH-07 MUST: if the game reaches the start of turn 90 (the end of turn 89), the match is a draw, even if both heroes are Immune. The first player gets 45 turns and the second 44\. \[C\]  
* MATCH-08 MUST: the player action set is: play a card from hand (with target, position and choice parameters), use hero power, attack with a character, activate a location, use Tradeable/Forge on a hand card, end turn, concede. Conceding gives the opponent the win. \[S\]  
* MATCH-09 MUST: the engine is a pausable state machine. Wherever the rules need a human decision (mulligan, target, minion position, Choose One option, Discover pick), it stops and exposes a typed pending-choice request with its legal options, then resumes when the choice is submitted.  
* MATCH-10 MUST: at every decision point the engine can enumerate all legal actions. This is required for AI, fuzzing and the conformance tests in section 15\.  
* MATCH-11 MAY: the 75-second turn timer, the 20-second fuse and reconnection are external to the engine. The engine only needs an `end_turn` or `concede` action an outside clock can inject. \[S\]

## **4\. Resources and limits**

Each player has three resource systems (mana, cards, board space) plus health and armor, and each has hard caps the engine must enforce exactly.

**Limits at a glance**

| Limit | Value | Behavior when exceeded | Confidence |
| ----- | ----- | ----- | ----- |
| Hero starting Health | 30 | n/a | \[C\] |
| Deck size (constructed) | 30 cards | Deck is illegal (section 11\) | \[C\] |
| Hand size | 10 | New card is destroyed (drawn cards are revealed to both players first) | \[C\] |
| Board slots | 7, shared by minions and locations | Summon fails; a Battlecry or Deathrattle summon is wasted | \[C\] |
| Mana crystals (default cap) | 10 | Further gains do nothing, or generate Excess Mana | \[S\] |
| Mana crystals (hard cap) | 99 permanent | Some cards raise the cap above 10 | \[S\] |
| Secrets and quests | 5 Secrets, no two the same; 1 Quest (QST-05) | Cannot be played | \[S\] |
| Armor | 2,147,483,647 | The live game resets Armor to 0; the engine saturates instead (RES-18) | \[S\] |

**Mana**

* RES-01 MUST: track permanent crystals, filled crystals, locked (overloaded) crystals, pending overload, temporary mana and the crystal cap as separate values. \[S\]  
* RES-02 MUST: at the start of the active player's turn, gain one permanent crystal (up to the cap) and refill all unlocked crystals; unspent mana never carries over. \[C\]  
* RES-03 MUST: effects that add empty crystals raise permanent crystals only; effects that add filled crystals raise both permanent and available mana; if the cap is reached, filled-crystal gains grant Excess Mana instead. \[S\]  
* RES-04 MUST: temporary mana (The Coin, Innervate) is spent before permanent mana, is never overloaded, and disappears at end of turn. It may push available mana above the cap (11 of 10). \[S\]  
* RES-05 MUST: destroying crystals removes empty crystals first and lowers permanent crystals (floor 0). Destroying a filled crystal also lowers available mana this turn. \[S\]  
* RES-06 MUST: a card needs its full printed cost available before it resolves, even if its own effect would free mana (Lava Shock, Nourish). Zero-cost cards are always playable. \[S\]  
* RES-07 MUST: cost is computed as hidden cost (base plus all modifiers, no floor) and actual cost (hidden cost, floored at 0 only after all modifiers). Modifiers apply in creation order, oldest first, except Summoning Portal, which always applies first. Set-cost and add/subtract effects have no priority over each other. Returning a card to hand re-stamps it. \[S\]  
* RES-08 MUST: health-as-cost effects (Cho'gall, Seadevil Stinger) replace the mana payment of the next card with damage equal to its final cost, taken from Armor first; the card is unplayable if the player could not survive that damage and is not Immune. \[S\]

**Overload**

* RES-09 MUST: Overload is charged only when the card is successfully played from hand. Summoning the minion by other means gives none, a card countered by Counterspell gives none, and doubling a Battlecry does not double Overload. \[S\]  
* RES-10 MUST: overload played in turn N becomes pending, becomes locked at the start of the player's next turn, and clears at the start of the turn after. There is no upper limit, and excess beyond current crystals still offsets mana gains such as The Coin. \[S\]  
* RES-11 MUST: unlock effects (Lava Shock, Eternal Sentinel, Overdraft) unlock and refill locked crystals and clear pending overload. Destroying crystals never changes overload. \[S\]

**Cards**

* RES-12 MUST: drawing into a full hand reveals and destroys the card. Cards added to hand by other means (put into hand, Discover) are discarded when the hand is full. A Discover choice is added only at the end of the current sequence, so the hand may fill in between. A minion returned to a full hand is destroyed and its Deathrattle triggers. \[S\] (the bounce rule is from Icy Veins, 2016\)  
* RES-13 MUST: board space is shared by minions and locations. A Location's last use that summons a minion clears the Location first so the minion can use its slot. A hero power that summons cannot be used on a full board. \[S\]  
* RES-14 MUST: effects queued simultaneously may briefly exceed 7 (Cairne Bloodhoof with Ancestral Spirit); the limit is enforced when placing, not as a global invariant. \[S\]

**Fatigue and armor**

* RES-15 MUST: each player has a fatigue counter that starts at 0 and never resets (not by shuffles, refills or hero replacement). Each failed draw attempt, including the automatic turn draw, effect draws and manual fatigue draws, increments the counter, then deals that much damage to the hero. \[S\]  
* RES-16 SHOULD: in a multi-card draw, each failed attempt applies fatigue separately, in sequence. \[?\]  
* RES-17 MUST: Armor is removed before Health. Damage absorbed by Armor still counts as damage for triggers. Armor never prevents death if the hero already has 0 or less Health. Fatigue damage obeys Armor and Immune. \[S\]  
* RES-18 MUST: all integer stats use saturating arithmetic so a gain past the platform maximum cannot wrap negative.

## **5\. Card types and play rules**

Six kinds of object can be played or used (five card types plus the hero power), and each has its own play sequence, legality checks and zone, which the engine must keep distinct because triggers key off the difference between playing and summoning.

**Playing versus summoning**

* PLAY-01 MUST: a card is "played" only when it moves from hand to the board or is cast from hand. Every minion or location that enters the board by any route is "summoned." Battlecry, Choose One, Combo and Overload happen only on play; "whenever you summon" triggers fire on both. \[S\]  
* PLAY-02 MUST: transform replaces an entity in place without summoning, so it fires no summon, death or Deathrattle triggers (a Battlecry-caused transform is a documented exception that can trigger summon effects). \[S\]  
* PLAY-03 MUST: minions summoned by a spell or hero power appear at the far right of the player's board; a minion the player plays is placed at a position they choose; a minion summoned by another minion's trigger appears immediately to its right; multi-summons (Onyxia, Dr. Boom) spread to both sides. \[S\]  
* PLAY-04 MUST: once placed, a minion's position never changes except by removal, in which case neighbors become adjacent. \[S\]

**Per-type rules**

| Type | Play sequence | Key rules |
| ----- | ----- | ----- |
| Minion | Pay mana, move to board at chosen position, then On Play triggers, Summon Resolution, Battlecry, After Play and After Summon triggers | Enters exhausted unless Charge or Rush. Needs a free board slot. A targeted Battlecry with no legal target is skipped; with a legal target it must be chosen. A Battlecry cannot target its own minion. \[S\] |
| Spell | Pay mana, remember target, On Play triggers, spell text, After Spell triggers | Target is remembered and not rechecked; a spell whose target leaves play still resolves its remaining effects. Counterspell stops Overload and the spell text only. \[O\] |
| Weapon | Pay mana, new weapon enters, its Battlecry resolves, then the old weapon is destroyed and its Deathrattle fires | Hero has at most one weapon. Weapons cannot be silenced. \[S\] |
| Hero card | Pay mana, replace hero, gain Armor, Battlecry, replace hero power | Current and max Health carry over (Jaraxxus-style cards set them). Thaws a frozen hero. A single-class hero card changes the player's class for Discover. \[S\] |
| Location | Pay mana, enters board | Not a minion. No Attack or Health. Usable the turn it is played; each use costs 1 durability and the Location is unusable on the player's next turn. Can target otherwise untargetable minions. \[S\] |
| Hero power | Pay mana (2; Demon Hunter 1), choose target, effect resolves, exhaust, then Inspire and hero-power triggers | Once per turn, refreshes at turn start or on replacement. Cannot be used if exhausted, unaffordable, would summon onto a full board, or needs a target and none is legal. Replacing a power resets its per-turn use. \[S\] |

**Targeting legality**

* PLAY-05 MUST: a legal-target query takes (source, effect, controller) and returns the set of entities that may be chosen. It excludes enemy Stealth and Immune characters, Dormant permanents, and Elusive characters for spells and hero powers (locations may target Elusive). The controller may always target their own Stealth and Immune characters. \[S\]  
* PLAY-06 MUST: automatic, random and area effects are not blocked by Stealth or Immune targeting; they still honor damage prevention. \[S\]  
* PLAY-07 MUST: a play is rejected before any cost is paid if the card is unaffordable, the board is full (for minions), a required target has no legal choice (except for effects that are skipped, like Battlecries), or the card's play condition fails.

**Card-text semantics**

* PLAY-08 MUST: Choose One presents its options as temporary choice cards in Set-aside; the card does not count as played until an option is chosen, so Counterspell cannot respond before the choice. Choose One is not a Battlecry (Brann does not double it). If both options apply (Fandral Staghelm), selection is skipped and effects run in printed order. \[S\]  
* PLAY-09 MUST: Combo triggers when at least one other card has been played from hand earlier that turn, including The Coin. \[S\]  
* PLAY-10 SHOULD: Discover offers three different cards from the effect's stated pool (default: the hero's class plus neutral, Standard-legal), the player must pick one, and the pick is added to hand unless text says otherwise. With fewer than three eligible cards, fewer options are shown. A random-pool Discover cannot offer a copy of itself. \[S\]

## **6\. Combat rules**

Combat is a two-phase sequence (preparation, then simultaneous damage) in which only attackers and defenders leaving play can cancel it; everything else still resolves.

**Who may attack, and what**

| Attacker state | Can attack minions | Can attack hero | Source |
| ----- | ----- | ----- | ----- |
| Minion, ready (not exhausted) | Yes | Yes | \[S\] |
| Minion, just summoned, no keyword | No (exhausted) | No | \[S\] |
| Minion with Rush, arrival turn | Yes | No | \[S\] |
| Minion with Charge, arrival turn | Yes | Yes | \[S\] |
| Minion with both Rush and Charge | Yes | Yes (Charge wins) | \[S\] |
| Hero with Attack above 0 (a weapon or temporary Attack) | Yes | Yes | \[S\] |

**Eligibility and targets**

* CMB-01 MUST: a character may attack only if it is not frozen, has Attack of at least 1, has made fewer attacks this turn than its limit (1; 2 with Windfury; 4 with Mega-Windfury), and is not exhausted (or is exempt by Charge or Rush). A hero can attack only on its owner's turn and only with Attack above 0\. \[S\]  
* CMB-02 MUST: Windfury granted after an attack lets the minion attack again; lost Windfury does not refund a spent attack. A hero's attack count carries across weapons within a turn. Mega-Windfury and Windfury do not stack. \[S\]  
* CMB-03 MUST: a Rush granted to an already-ready minion has no effect (it can still attack the hero); Rush granted to a minion that already attacked does not give another attack. Rush and Charge are exempt only the turn the minion arrives or changes control. \[S\]  
* CMB-04 MUST: an attack target is an enemy character that is not Stealthed and not Immune. If the opponent controls any Taunt minion that is not Stealthed or Immune, the target must be a Taunt minion. The attacker may decline to attack. A Stealthed or Immune Taunt minion does not act as Taunt until that status ends. \[S\]  
* CMB-05 MUST: Taunt restricts only the choice of attack target. It does not restrict spells, hero powers, area effects, random effects or forced attacks that bypass it. \[S\]  
* CMB-06 MUST: an attack against an Immune character cannot be declared, and a hero or minion with no legal attack target cannot attack. \[S\]

**Attack sequence**

1. **Declare.** Create a proposed attack event (attacker, defender). Remember the attack count and whether the attack is forced.  
2. **Combat preparation phase.** Resolve attack-triggered effects, including Secrets, in order of play. A trigger that changes the defender (Misdirection) produces a new proposed event. Then the real attack event resolves, the attacker loses Stealth, and the engine runs a win/loss check. If an effect already ended the game here (Explosive Trap on a 2-Health hero), the attack never reaches damage. \[O\]  
3. **Combat phase.** Attacker and defender deal damage simultaneously, each equal to its current Attack. A hero defender does not strike back. A hero attacker's weapon loses 1 durability unless the hero is Immune. \[S\]  
4. **After-attack.** An After Attack event fires even if no damage was dealt (for example, 0 Attack), then the death phase and win/loss check run (section 7). \[O\]  
* CMB-07 MUST: combat is cancelled only if the attacker or the defender leaves play (or changes zone) before the combat phase. A defender that changes sides, or an attacker dropped to 0 Attack, does not cancel it. \[O\]  
* CMB-08 MUST: if combat was cancelled after at most one death phase, the attacker has not used its attack and may attack again; with two or more death phases, the attacker's attack is spent. The source calls the latter case a bug, so make this a configurable policy. \[O\]  
* CMB-09 MUST: Stealth is lost after the preparation phase and before combat damage, even when no damage event follows (Ice Block, 0 Attack). A 0-Attack Stealthed minion attacked by a random-target effect keeps Stealth because no damage event occurs. A 0-damage event that exists (Divine Shield pop) breaks Stealth. \[S\]  
* CMB-10 MUST: on simultaneous damage, "was damaged" triggers resolve with the defender's first, and "dealt damage" triggers with the attacker's first. \[O\]  
* CMB-11 MUST: weapon Attack counts only on the owner's turn and is lost when the weapon is sheathed at turn end. Weapons lose durability only from their own hero's attacks, never from being attacked, and are destroyed at 0 durability. Gorehowl-style weapons override this with their own Immune clause. \[S\]  
* CMB-12 MUST: each combat damage application is a separate damage event and runs through the damage pipeline in section 9 (Immune, Divine Shield, Armor, Poisonous, Lifesteal).

## **7\. Effect resolution and death processing**

Resolution is a depth-first walk over triggers queued in order of play, and nothing dies until the outermost phase finishes. This is the section most likely to be wrong in a naive engine, and it is the one source with the weakest currency (patch 9.2.0.21517), so every rule here is tagged \[O\] and must be exposed as a versioned policy (ARCH-03).

\[embed: node/5cd7c8e5-90f1\]

The top row runs left to right and the middle row right to left. Steps 1 to 3 run once per outermost phase, and a death phase that kills more minions sends the sequence back through them.

**Vocabulary**

* **Player action:** attack, play a card, use hero power, end turn. It starts a **sequence**.  
* **Sequence:** an ordered list of **phases** started by one player action.  
* **Phase:** a block that starts when events or triggers are raised.  
* **Event:** any state change (damage, heal, summon, draw, death).  
* **Trigger:** anything that reacts to an event, including triggered effects, Secrets and Deathrattles.

**Resolution rules**

* EFF-01 MUST: a phase, trigger or event is resolved only after all its consequences are resolved. A newly raised trigger is fully resolved before returning to the rest of the parent (depth-first). Simultaneous events resolve one at a time. A trigger cannot nest inside itself; the skipped repetitions apply after the other consequences. \[O\]  
* EFF-02 MUST: when a phase or event starts, build a queue of all responding triggers ordered by play-order stamp, oldest first. Simultaneous events are queued by order of play, and each event's triggers are queued the same way. The queue becomes immutable once its first entry starts resolving. A minion entering play mid-event cannot respond to events already in progress but can respond to later ones. Redemption-type effects always queue last. \[O\]  
* EFF-03 MUST: nested phases may start and end inside an outer phase, but no entity is killed until the outermost phase ends (exception: forced-death effects such as Reincarnate and Poison Seeds, whose new deaths cannot start a new death phase). \[O\]  
* EFF-04 MUST: after the outermost phase ends, run in this order: (1) update Health and Attack auras, (2) the death creation step, which removes all mortally wounded (Health 0 or less) and pending-destroy entities simultaneously, (3) update the remaining auras. Removed entities cannot trigger, be triggered, emit auras or occupy space. \[O\]  
* EFF-05 MUST: if the death step removed anything, start a death phase. Queue the deaths in order of play; for each, queue all of its death triggers (its Deathrattles, Secrets such as Duplicate, effects such as Cult Master) in order of play and resolve each fully before the next. Deathrattles get no special priority. A death phase may cause another; repeat until none, then continue the sequence. \[O\]  
* EFF-06 MUST: a character with Health 0 or less is mortally wounded but stays in play until step 2\. Negative effects (damage, destroy, hinder, redirect) skip mortally wounded or pending-destroy targets. Secrets abort if their target is in that state. Beneficial effects (heal, buff) and area effects still see them, so a heal or a Health aura can save a minion before the death step. For "if it survives" or "if that kills it" checks, such characters count as killed. \[O\]  
* EFF-07 MUST: a later phase does not run if its required subject has left play; only presence is rechecked, not target conditions. Exceptions: spells with a stored target still resolve their side effects (Drain Life), and conditional Battlecries recheck their condition (Dragon checks) during the Battlecry phase. \[O\]  
* EFF-08 MUST: win, loss and draw are checked when the sequence ends and control returns to a player (so both heroes can die in one sequence and the game is a draw). During an attack, the check also runs between the preparation and combat phases. \[O\]  
* EFF-09 MUST: conditional triggers check their condition at up to three points: pre-check (only for After Play and death-phase triggers), queuing, and triggering. "After" triggers fire only if their source was valid when the sequence started. Death consequences require the entity's position and controller to have been valid before the death creation step. \[O\]  
* EFF-10 MUST: effects have no memory of earlier board states. They read the current state each time a queue is populated or an effect resolves. Effects that store a caster (Blessing of Wisdom, Shadow Madness) are explicit exceptions. \[O\]  
* EFF-11 MUST: Battlecry and similar play effects resolve after On Play triggers and before After Play and After Summon triggers. Secrets triggered by a minion being played resolve after its Battlecry. \[S\]

**Play sequences (phase order)**

| Action | Phase order |
| ----- | ----- |
| Play minion | Enter play and raise the summon event, On Play, Summon Resolution, Battlecry (Mayor Noggenfogger first), After Play and After Summon, win check |
| Summon minion (not played) | After Summon only |
| Play spell | Pay and store target, On Play (Counterspell stops Overload and spell text here), spell text, After Spell |
| Play weapon | New weapon enters, its Battlecry, old weapon destroyed and its Deathrattle resolves |
| Attack | Section 6 |
| Start and end of turn | Section 3, each trigger followed by a death and win check |

## **8\. Stats, auras and enchantments**

Every current stat is computed from the card's base value, then enchantments in the order they were granted, then auras last; nothing is stored as a running total except damage.

**Evaluation layers (Attack, Health, cost, keywords)**

| Layer | Contents | Order within layer |
| ----- | ----- | ----- |
| 1\. Base | Value printed on the card definition | n/a |
| 2\. Enchantments | Buffs and debuffs from spells, Battlecries, triggers, including set-to effects | Oldest granted first (timestamp) |
| 3\. Auras | Ongoing effects from other entities in play, including Health and Attack auras | After all enchantments, in play order of their sources |
| 4\. Floor | Cost is floored at 0 only after layers 1 to 3; Attack and Health are not floored by the stat itself | After everything |

Set-to versus add/subtract effects have no built-in priority; the timestamp decides. Auras are applied after enchantments even if the aura source arrived first, so auras do not feed into other enchantments' arithmetic. \[S\]

**Requirements**

* STAT-01 MUST: an aura exists only while its source is in play. When the source dies, is silenced, is returned to hand or changes control, its aura effect is removed from every affected entity at the next aura update. \[S\]  
* STAT-02 MUST: Health and Attack auras are recalculated before the death creation step; all other auras (Baron Rivendare, Auchenai Soulpriest, Brann Bronzebeard, Mal'Ganis's Immune, Prophet Velen, Violet Illusionist, Drakkari Enchanter, The Four Horsemen) are recalculated after it. Summoning a minion (not playing it) triggers both updates. \[O\]  
* STAT-03 MUST: aura-granted Health persists until the next recalculation, so a minion with a Health aura that is mortally wounded in the same phase as its aura source can survive it, because Health is not recalculated by the kill. \[O\]  
* STAT-04 MUST: an aura source benefits from its own aura when it meets the condition (Tundra Rhino gaining Charge). A minion's aura is active from the moment it is played, before its Battlecry. A minion gained by mind control starts its aura only after the outermost phase ends, unless another minion is summoned first. \[S\]\[O\]  
* STAT-05 MUST: enchantments apply immediately when attached, and the update re-sorts Health and Attack auras after enchantments. Cost auras have no special priority over cost enchantments. \[O\]  
* STAT-06 MUST: temporary enchantments (until end of turn, until next turn) expire at turn handover; when one expires, the remaining stack is recomputed. \[S\]  
* STAT-07 MUST: Enrage is not an aura; it depends only on the minion's own damage state and is active only while the minion is damaged. \[S\]  
* STAT-08 MUST: Spell Damage is a stackable additive bonus that takes effect the moment its source enters play and updates continuously. It adds to each target's damage for spells only (not hero powers, Battlecries, Deathrattles, combat or fatigue), and applies before multiplicative effects such as Prophet Velen. It also raises the damage of healing spells that were converted to damage. \[S\]  
* STAT-09 MUST: copy effects do not copy enchantments that exist only on cards in hand, and cost-changing enchantments are not copied. Copies of a Dormant minion that has already awakened start awake. Whether a copy inherits battlefield enchantments is not stated by the sources. \[?\]

**Silence**

| Silence removes | Silence keeps |
| ----- | ----- |
| All card text, keywords (Taunt, Windfury, Reborn, Divine Shield, Stealth, Freeze) | Damage already on the minion |
| All enchantments, including Health enchantments (max Health is recomputed, current Health is capped) | Tribes and factions |
| Its own aura and triggered effects, Deathrattles | Transforms (Hex, Polymorph) |
| Temporary mind control (Shadow Madness) | Permanent mind control (Mind Control) |
| Enchantments it generates for others only stop being generated | Enchantments it already placed on others; auras from other cards; playerbound effects |

* STAT-10 MUST: silence applies once and is not itself an enchantment, so it cannot be dispelled. A second silence does nothing, new enchantments applied afterward work normally, and returning the minion to hand restores its original text and stats. Weapons cannot be silenced; whether heroes can is not stated by the sources (section 16). \[S\]

**Transform**

* STAT-11 MUST: transform creates a new entity in the old entity's place, clears all card text and enchantments, makes the new minion exhausted (unless it has Charge or Rush), fires no summon, death or Deathrattle effects (a Battlecry-caused transform is the documented exception), and is permanent. The new entity is stamped as the newest in play. It cannot be reverted by silence or bounce. \[S\]  
* STAT-12 MUST: cost-based transforms (Evolve, Devolve, Revolve) re-roll, floor cost at 0, and may land on the same minion; minions of cost 10 or less cannot evolve past cost 10, and minions of cost 11 or more transform only into the same cost. \[S\]  
* STAT-13 SHOULD: whether damage and controller carry across a transform is not stated in the sources. Default to a fresh undamaged minion under the same controller and flag this as an open question. \[?\]

## **9\. Keyword catalog and the damage pipeline**

Keywords are the engine's built-in primitives; each is either a tag the core reads (Taunt, Stealth) or a trigger the core fires (Battlecry, Deathrattle). The damage pipeline is the single place their interactions are decided.

**Damage pipeline**

Every point of damage, from any source, passes these steps in order:

1. **Compute.** The source determines raw damage. Spell Damage is added only for spells (STAT-08).  
2. **Immune.** If the target is Immune, damage becomes 0 and no damage-triggered effects fire. \[S\]  
3. **Divine Shield.** If the damage is above 0 and the target has Divine Shield, damage becomes 0 and the shield is removed; "was damaged" triggers do not fire, and Lifesteal heals 0\. A 0-damage event does not pop the shield. \[S\]  
4. **Armor.** For heroes, Armor absorbs first; the remainder lowers Health. Armor-absorbed damage still counts as damage for triggers. \[S\]  
5. **Apply.** Record the damage. Fire "was damaged" and "dealt damage" triggers (defender-side first in combat, CMB-10). A character at 0 Health or less becomes mortally wounded. \[O\]  
6. **Poisonous.** If a Poisonous source dealt damage above 0 to a minion, mark the minion pending-destroy. A shielded or 0-Attack source destroys nothing. \[S\]  
7. **Lifesteal.** After damage is dealt, the source's controller's hero is healed by the damage dealt. If lethal damage and the heal are in the same action, the hero survives when damage minus the heal is less than its Health. \[S\]  
* KW-01 MUST: multi-target damage effects produce one damage event per target; Choose One damage cards produce two separate events. \[S\]  
* KW-02 SHOULD: whether Lifesteal counts overkill, or damage absorbed by Armor, is not stated by the sources; default to the damage actually removed from Health plus Armor, and flag this. \[?\]  
* KW-03 MUST: Lifesteal heals only the controlling hero, never minions. Healing effects converted to damage (Auchenai Soulpriest) do not count as damage dealt by the Lifesteal source. \[S\]

**Core keywords**

| Keyword | Semantics the engine must implement | Confidence |
| ----- | ----- | ----- |
| Taunt | Enemy attackers must target a Taunt minion; suppressed while the minion is Stealthed or Immune; ignored by spells, hero powers, area and random effects | \[S\] |
| Charge | Can attack on the arrival turn, including the enemy hero | \[S\] |
| Rush | Can attack minions only on the arrival turn; has no effect on a minion that is already ready to attack | \[S\] |
| Windfury / Mega-Windfury | Up to 2 / 4 attacks per turn; do not stack; hero Windfury exists only while the weapon is equipped | \[S\] |
| Divine Shield | Absorbs the next damage above 0, then removed; does not stop destroy effects or stat changes; granting it again does nothing; random grants skip characters that already have it | \[S\] |
| Stealth | Cannot be targeted by the enemy (attacks, spells, hero powers, Battlecries); affected by area and random effects; the owner may target it; lost on attacking; a Stealthed Taunt does not taunt | \[S\] |
| Elusive | Cannot be targeted by spells or hero powers; can be attacked and targeted by Battlecries (not a formal keyword) | \[S\] |
| Immune | No damage taken and not targetable by the enemy; not blocked: destroy, Health restore, area and automatic effects; owner may target; Immune characters may attack | \[S\] |
| Poisonous | Destroys any minion it damages | \[S\] |
| Lifesteal | Damage dealt also heals the controlling hero | \[S\] |
| Freeze | See thaw rules below | \[S\] |
| Reborn | The first time it dies, it returns with 1 Health and its original max Health, without enchantments, as a new summon (fires summon triggers); its Deathrattle resolves before Reborn; returning to hand and replaying restores Reborn | \[S\] |
| Battlecry | Fires only when played from hand; targeted Battlecries need a legal target to fire; resolves after On Play and before After Summon; a doubled Battlecry (Brann) fires twice; replaying a bounced minion fires it again | \[S\] |
| Deathrattle | Fires when the minion, weapon or location is destroyed on the board, not when discarded, removed from deck or bounced; several can exist on one minion; resolves in death-phase order | \[S\] |
| Secret | See section 10 | \[S\] |
| Spell Damage | See STAT-08 | \[S\] |
| Discover | See PLAY-10 | \[S\] |
| Combo | See PLAY-09 | \[S\] |
| Overload | See RES-09 and RES-10 | \[S\] |
| Dormant | Enters as an untouchable permanent; awakens on its condition or a countdown that ticks at the start of its controller's turn; can be made dormant again | \[S\] |
| Echo | Adds a copy to hand playable this turn; copies cost at least 1 | \[S\] |
| Outcast | Extra effect if the card is leftmost or rightmost in hand when played | \[S\] |
| Tradeable | For 1 mana, shuffle into the deck and draw a replacement | \[S\] |
| Magnetic | Played to the left of a Mech, merges stats and effects into it | \[S\] |
| Colossal | Arrives with additional token minions | \[S\] |
| Forge | For 2 mana, drag the card into the deck to gain an extra effect and return to hand | \[S\] |
| Infuse | Gains an extra effect after a set number of friendly minions died while it is in hand | \[S\] |
| Starship | Dead Starship Pieces add stats and effects to a permanent Starship, which can be summoned for 5 mana | \[S\] |
| Assemble | Adds a minion to hand, then replaces part of its text with the text of another minion from a curated pool | \[S\] (official one-line description only) |
| Old Gods | One per deck; each has four abilities, invokes two per turn instead of attacking, each ability once per game; can attack only after all four are used | \[S\] (official) |

**Freeze thaw rules**

* KW-04 MUST: a Frozen character cannot attack but still defends. A Frozen hero may still use its hero power and equip weapons. Silence removes Frozen; playing a hero card thaws the hero. \[S\]  
* KW-05 MUST: if Freeze is applied on the controller's turn before the character has attacked and while it could still attack, it thaws at the end of that turn. If it is applied after the character has attacked, or while it could not attack (exhausted, no legal target for a Rush or Charge minion), it thaws at the end of the controller's next turn. A forced attack counts as the attack and cannot be prevented by Freeze. \[S\]  
* KW-06 SHOULD: Freeze applied on the opponent's turn thaws at the end of the controller's next turn. The sources only describe freezes applied on the controller's own turn. \[?\]

## **10\. Secrets, quests, locations and special zones**

Secrets and quests are hidden or semi-hidden persistent effects that live outside the board, and each has its own cap, trigger window and visibility.

| Property | Secret | Quest | Location |
| ----- | ----- | ----- | ----- |
| Card type | Spell | Legendary spell | Own card type |
| Where it lives | Secret zone | Hero zone above the portrait | Board (shares the 7 slots) |
| Max active | 5 per player, no two the same | 1 per hero | No limit beyond board space |
| Visible to opponent | Existence only, not identity | Yes, including progress | Yes |
| When it acts | Mostly on the opponent's actions; a few at the start of the owner's own turn | Progress from the controller's own actions on either turn | Activated by the controller on their turn |
| Counterable | Yes, when played (it is a spell) | Yes (it is a spell) | Yes, when played |
| Source | \[S\] | \[S\] | \[S\] |

**Secrets**

* SEC-01 MUST: a player may have at most 5 Secrets active and may not play a Secret whose card matches one already active. Effects that put Secrets into play (Kezan Mystic, Mysterious Challenger) respect the same cap. A documented 2015 bug let Mad Scientist exceed the cap; do not replicate it. \[S\]\[O\]  
* SEC-02 MUST: Secrets are hidden from the opponent and become revealed when triggered or destroyed. \[S\]  
* SEC-03 MUST: when one event triggers several Secrets, they take effect one at a time in the order played. A Secret and another triggered effect that share a trigger also resolve in play order. Secrets triggered by a minion being played resolve after that minion's Battlecry. \[S\]  
* SEC-04 MUST: if an earlier Secret removes a later Secret's target, the later Secret does not take effect. Secrets that need no target (Explosive Trap, Snake Trap) still resolve. \[S\]  
* SEC-05 MUST: a Secret whose trigger fires but cannot take effect (Mirror Entity or Noble Sacrifice with no board room, Avenge with no friendly minions left) stays in place and stays hidden. \[S\]  
* SEC-06 MUST: Secrets resolve before the game can end, so Eye for an Eye can produce a draw. A Secret aborts if its target is mortally wounded or pending destroy (EFF-06). \[S\]

**Quests**

* QST-01 MUST: Quests start in hand, are all Legendary spells, and appear as the leftmost cards in the mulligan (and may be replaced there). \[S\]  
* QST-02 MUST: a hero may have only one active Quest; another cannot be played until it completes, except for sub-quests granted by Quest Accepted\! and Reach Equilibrium. \[S\]  
* QST-03 MUST: only the controller's actions advance a Quest. Unlike Secrets, progress can occur on either player's turn (an opponent's effect that summons minions for the controller can count), while card-play progress can happen only on the controller's turn. \[S\]  
* QST-04 MUST: the reward is generated after the phase in which the Quest was completed; an effect that completes the Quest cannot change a reward already generated. If the hand is full, the reward waits until a slot opens, which may be on the opponent's turn (since patch 33.0.0.223542). \[S\]  
* QST-05 SHOULD: whether Quests use Secret slots is stated only by the wiki Secret page ("Quest cards take up a Secret slot") and not by the Quest page; implement as a configurable policy. \[?\]  
* QST-06 SHOULD: Questlines and sidequests exist but the sources do not describe their rules. \[?\]

**Locations, hero zone and generated cards**

* ZONE-01 MUST: see PLAY table for Location use; a Location has no Attack or Health, cannot be damaged or destroyed unless a card says so, and behaves like a Dormant minion for most effects. Plague of Death does not destroy it. \[S\]  
* ZONE-02 MUST: Dormant minions, Locations and Starship permanents are not valid targets of minion effects unless a card specifies them. \[S\]  
* ZONE-03 MUST: Discover and generate effects take their pool from the effect text; the default is cards of the controller's class plus neutral cards legal in the match's format. Cards that generate random cards cannot generate copies of themselves. \[S\]  
* ZONE-04 MUST: Echo copies are always the original card (buffs and cost changes on the hand card do not carry over, except from auras) and cost at least 1\. They are removed at end of turn and require being played from hand. \[S\]  
* ZONE-05 MUST: Tradeable inserts the card into the deck at a random position and then draws the top card as a normal draw, without shuffling or counting as a play. It keeps its enchantments, cannot be used on an empty deck, and may be used on a full hand. \[S\]  
* ZONE-06 MUST: Magnetic counts as playing a minion, not summoning one: the minion becomes an enchantment on the Mech (its text and stats), so silence or bounce removes it, and targeted on-play effects do not fire. A full board still allows a Magnetic play. \[S\]

## **11\. Formats and deck construction**

A deck is valid if it has 30 cards of one class plus neutrals, within the copy limits and the selected format's card pool; the pool is data, not code.

**Formats**

| Format | Card pool | Source and confidence |
| ----- | ----- | ----- |
| Standard | Sets from the current and previous calendar year, plus the Core set. As of October 2026: Cataclysm, Escape from Violet Hold, Reign of the Black Empire (2026) and Into the Emerald Dream, The Lost City of Un'Goro, Across the Timeways (2025). Updated when the year's first expansion launches | [Blizzard](https://hearthstone.blizzard.com/en-us/expansions-adventures) \[C\]; wiki.gg also lists the 2024 Event set, unconfirmed \[?\] |
| Wild | Every set, including Legacy (the old Basic and Classic cards); banned in Wild: Godfrey the Betrayer, Grove Shaper (as of patch 36.6.0.251952) | [wiki.gg](https://hearthstone.wiki.gg/wiki/Wild_format) \[S\] |
| Classic | A separate format of the 240 original cards as of June 2014, with later balance changes reverted and no Demon Hunter | [Blizzard 2021](https://news.blizzard.com/en-us/article/23620129/introducing-the-core-set-and-classic-format) \[S\]; current status not checked \[?\] |
| Twist | Exists as a Play-mode format; its rules are not described by the sources | \[?\] |

**Requirements**

* DECK-01 MUST: a constructed deck has exactly 30 cards unless a card in the deck changes the size (Prince Renathal). \[S\]  
* DECK-02 MUST: a deck chooses one class and may contain only that class's cards and neutral cards. Whether a multi-class card is legal for any one of its classes is not stated by the sources; the engine should treat a card as legal if any of its classes matches the deck's class. \[?\]  
* DECK-03 MUST: at most 2 copies of any card (regular and premium versions count together) and 1 copy of each Legendary. \[S\]  
* DECK-04 MUST: every card in a deck must be legal in the chosen format, and no banned card may appear in a deck for the format that bans it. Legality comes from card-set metadata (set, release year, Core membership, ban list) supplied with each ruleset version, not hard-coded. \[S\]  
* DECK-05 MUST: deck-specific restrictions on cards (Highlander-style "no duplicates" effects, one Old God per deck) are validated at deck-check time through a rule hook on the card definition. \[S\]  
* DECK-06 MUST: during a match, shuffle-into-deck effects may push a deck above its starting size, up to 99 cards. Changes do not persist after the match. \[S\]  
* DECK-07 SHOULD: provide a validator `validate_deck(deck, format, ruleset_version)` that returns every violation (not just the first) so tools can display them.  
* DECK-08 SHOULD: accept and emit the community deck-string encoding for import and export. The sources do not give its layout; capture it from a specification when implementing. \[?\]  
* DECK-09 MAY: Arena, Tavern Brawl, Adventure and boss decks lift the 30-card, class and copy limits. They are out of scope for the core engine but the validator should allow a `rules_profile` override so they can be added later. \[S\]

## **12\. Win, loss and draw**

A player loses when their hero is destroyed, or they concede; both heroes dying in the same sequence, or reaching turn 90, is a draw.

| Outcome | Condition | When it is checked | Confidence |
| ----- | ----- | ----- | ----- |
| Loss | Hero at 0 Health or less (Armor does not save a hero already at 0\) | End of each sequence; between attack preparation and combat | \[C\] |
| Loss | Hero destroyed directly by a card (Uther of the Ebon Blade, Mecha'thun, Purified Shard) | Same | \[C\] |
| Loss | Player concedes | Immediately | \[C\] |
| Draw | Both heroes lose in the same sequence | End of sequence | \[C\] |
| Draw | Start of turn 90 (end of turn 89\) | Turn handover, even if heroes are Immune | \[C\] |

* END-01 MUST: a hero at 0 Health does not end the game mid-sequence; pending triggers (including Secrets and Lifesteal heals) resolve first, and only the end-of-sequence state decides the result. \[O\]  
* END-02 MUST: the result is final once emitted; no further actions are accepted.  
* END-03 MAY: disconnect handling (60-second reconnect window, both players disconnecting is a draw) belongs to the hosting layer, not the engine. \[S\]

## **13\. Card data and scripting**

Cards are data plus a script built from a fixed set of engine primitives; the engine must never contain card-specific `if` branches. These are design requirements for this engine, not facts about the live game.

* CARD-01 MUST: each card definition holds a stable ID, name, type, class or classes, cost, Attack, Health or durability, tribes, spell school, rarity, set, collectible flag, keyword list, rules text and a script. Tokens, choice cards, enchantments and hero powers are cards too.  
* CARD-02 MUST: scripts are declarative and composed from four kinds of primitive:  
  * **Triggers:** on play, Battlecry, Deathrattle, start and end of turn, "whenever" (queued when the event starts) and "after" (queued after the event), aura (continuous), in-hand and in-deck.  
  * **Selectors:** self, chosen target, all, random N, adjacent, friendly or enemy, filtered by type, tribe, school, cost or keyword.  
  * **Conditions:** board, hand, deck and history queries (for example, "if you played a spell this turn", "if your deck has no duplicates").  
  * **Actions:** damage, heal, destroy, summon, draw, discard, add to hand, shuffle, transform, copy, return to hand, equip, gain Armor or mana, change cost, give or remove enchantment or keyword, silence, freeze, Discover, set Health or Attack.  
* CARD-03 MUST: the "whenever" and "after" wording must map to different queue points, because ordering depends on it (EFF-09, EFF-11).  
* CARD-04 MUST: enchantments are first-class definitions with stat changes (add or set), granted keywords, duration (permanent, end of turn, start of next turn), attached triggers and whether they survive zone changes (in-hand cost enchantments do not, Tradeable keeps them).  
* CARD-05 MUST: an escape hatch allows a card to call a scripted function for effects the primitives cannot express. It may only use the engine API, must be deterministic and must draw randomness from the engine RNG.  
* CARD-06 MUST: random-card pools (Discover, "random spell", Evolve) are queries over the card catalog filtered by the match's format and the effect's stated constraints.  
* CARD-07 SHOULD: card text is templated from the script so that in-hand values (Spell Damage, cost changes) display correctly.  
* CARD-08 SHOULD: every card carries an implementation status and links to its tests, so coverage of a format can be reported.  
* CARD-09 SHOULD: card names, text and art are Blizzard property. If the engine is ever distributed, the catalog should be loaded from data the user supplies, not shipped with it.

## **14\. Engine architecture**

The engine is a deterministic, pure state machine: given the same seed, decks and action list, it must produce the same states and event log every time. These are design requirements, not game facts.

* ARCH-01 MUST: all randomness (shuffles, coin toss, random targets, Discover offers, generated cards) comes from one seeded RNG owned by the game state, drawn in a defined order. No global random calls, clocks or I/O.  
* ARCH-02 MUST: the complete state is serializable and restorable, and cheap to clone so AI search can branch from it.  
* ARCH-03 MUST: rules are versioned. Every ordering policy tagged \[O\] or \[?\] in this spec (for example CMB-08, QST-05, KW-06) is a named setting of a ruleset version, so behavior can change when verified without code changes elsewhere.  
* ARCH-04 MUST: every state change is emitted as an event with a sequence number, the action that caused it and its phase. The log is the basis for replays, debugging and tests, and a redacted copy per player hides information that player should not see.  
* ARCH-05 MUST: the public API is small:

| Call | Purpose |
| ----- | ----- |
| `new_game(ruleset, decks, seed)` | Validate decks, set up the match, stop at the mulligan choice |
| `legal_actions(player)` | Every action or choice that player may submit now |
| `apply(player, action)` | Validate, resolve fully, return events and the next pending choice or the result |
| `view(player)` | That player's view, with hidden information removed |
| `snapshot()` / `restore(state)` | Save and load full state |

* ARCH-06 MUST: an invalid action is rejected with a reason and changes nothing (actions are atomic).  
* ARCH-07 MUST: a sequence that does not terminate (an infinite trigger loop) is stopped by a configurable guard on events per sequence. What the live game does in this case is not known from the sources; the guard should end the match as a draw and log the cause. \[?\]  
* ARCH-08 MUST: triggers register with an event bus keyed by event type and are sorted by play-order stamp when a queue is built (EFF-02).  
* ARCH-09 SHOULD: set a throughput target (games simulated per second) before implementation, because it decides data layout choices such as copy-on-write state.

## **15\. Testing and conformance**

Every requirement ID in this spec needs at least one scenario test, and every \[O\] or \[?\] requirement also needs a check against the live client before it is treated as settled.

* TEST-01 MUST: a scenario format sets up a board (heroes, Health, mana, hand, deck order, minions with play-order stamps), applies actions, and asserts on the event log and final state.  
* TEST-02 MUST: each test names the requirement IDs it covers; a report lists requirements with no test.  
* TEST-03 MUST: property tests run random legal games and check invariants after every sequence: hand of 10 or fewer, board of 7 or fewer (except the transient case in RES-14), no character at 0 Health still in play, mana within bounds, and replay from the same seed gives the same log.  
* TEST-04 MUST: the edge cases named in the sources become fixed regression tests:

| Case | Expected | Covers |
| ----- | ----- | ----- |
| Two Sylvanas Windrunners kill each other | The one played first resolves its Deathrattle first | EFF-05 |
| Hero at 2 Health attacks into Explosive Trap | Game ends before combat damage | CMB step 2, EFF-08 |
| Eye for an Eye on lethal damage | Draw | SEC-06 |
| Cairne Bloodhoof dies with Ancestral Spirit | Board can briefly exceed 7 | RES-14 |
| Two Dust Devils on turn 2, then The Coin on turn 3 | 0 usable mana, 1-cost cards unplayable | RES-10 |
| Far Sight on Earth Shock, then Loatheb | Cost 3 | RES-07 |
| Hero attacks with an axe, equips Doomhammer | Exactly one more attack | CMB-02 |
| Discover at 10-card hand after Wild Pyromancer and Acolyte of Pain draws | Discovered card is discarded | RES-12 |
| Freeze a Charge minion before it attacks | Thaws at end of that turn | KW-05 |
| Lifesteal hero at 5 Health takes lethal while healing | Survives if damage minus heal is under 5 | KW pipeline step 7 |

* TEST-05 SHOULD: where possible, verify ordering against logs recorded from the live client rather than wiki descriptions, and record the client patch each test was verified on.

## **16\. Open questions and next research**

The biggest risk is section 7: the only detailed source on resolution order was last checked against patch 9.2.0.21517, years before 37.0. Verify it against the live client before building on it.

**Open questions (each is a ruleset setting until resolved)**

| ID | Question | Default in this spec |
| ----- | ----- | ----- |
| RES-16 | Does each failed draw in a multi-card draw apply its own fatigue hit? | Yes, in sequence |
| STAT-09 | Does a copy of a minion on the board inherit its enchantments? | Not decided |
| STAT-13 | Do damage and controller survive a transform? | Fresh, undamaged, same controller |
| KW-02 | Does Lifesteal count overkill or Armor-absorbed damage? | Counts damage removed from Health plus Armor |
| KW-06 | When does Freeze applied on the opponent's turn thaw? | End of the controller's next turn |
| QST-05 | Do Quests use one of the 5 Secret slots? | Configurable, on |
| QST-06 | How do Questlines and sidequests work? | Not modelled |
| DECK-02 | Are multi-class cards legal in any one of their classes? | Yes |
| DECK-08 | What is the deck-string layout? | Not modelled |
| ARCH-07 | What does the live game do with an infinite loop? | Draw after a guard limit |
| CMB-08 | Can an attacker re-attack after a combat cancelled across 2 or more death phases? | No (as observed) |
| Formats | Is the 2024 Event set in Standard? What are Twist's rules? Is Classic still live? | Event excluded; Twist and Classic out of scope |
| Silence | Can heroes be silenced? | No |

**Next research, in priority order**

1. Record live-client logs for every \[O\] rule in section 7 and the TEST-04 cases, on patch 37.0.  
2. Document the keywords added in 2025 and 2026 sets (including Assemble and Old God abilities) from card text and patch notes; the wiki keyword pages describe older mechanics best.  
3. Fill the documented gaps: Titans, Invoke, Imbue, Questlines, Colossal placement, Dormant board-slot use, Location interaction with auras and Freeze.  
4. Get the Core set card list for 2026 and a machine-readable card catalog, which the format validator needs.