# **Hearthstone Ruleset Manifest & Card Definitions (foundation-v1)**

**Version:** foundation-v1  
**Catalog Revision:** 1.0  
**Target Patch:** 37.0

## **1\. Overview & Scope**

This document acts as the RulesetManifest and initial CardDefinition catalog for the foundation subset of the Hearthstone engine. All card logic is decoupled from runtime state (CardInstance) and defined using explicit, machine-readable execution mechanics.

## **2\. Card Definition Catalog**

### **CS2\_032: Chillwind Yeti**

**Type:** Minion | **Class:** Neutral | **Cost:** 4 | **Attack:** 4 | **Health:** 5  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_032",  
  "revision": "foundation-v1",  
  "name": "Chillwind Yeti",  
  "type": "MINION",  
  "classes": \["NEUTRAL"\],  
  "baseStats": { "manaCost": 4, "attack": 4, "health": 5 },  
  "keywords": \[\],  
  "mechanics": \[\],  
  "text": { "enUS": "" },  
  "playConditions": \[\],  
  "abilities": \[\]  
}

### **CS2\_122: Sen'jin Shieldmasta**

**Type:** Minion | **Class:** Neutral | **Cost:** 4 | **Attack:** 3 | **Health:** 5  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_122",  
  "revision": "foundation-v1",  
  "name": "Sen'jin Shieldmasta",  
  "type": "MINION",  
  "classes": \["NEUTRAL"\],  
  "baseStats": { "manaCost": 4, "attack": 3, "health": 5 },  
  "keywords": \["TAUNT"\],  
  "mechanics": \[\],  
  "text": { "enUS": "Taunt" },  
  "playConditions": \[\],  
  "abilities": \[\]  
}

### **CS2\_042: Fire Elemental**

**Type:** Minion | **Class:** Shaman | **Cost:** 6 | **Attack:** 6 | **Health:** 5  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_042",  
  "revision": "foundation-v1",  
  "name": "Fire Elemental",  
  "type": "MINION",  
  "classes": \["SHAMAN"\],  
  "baseStats": { "manaCost": 6, "attack": 6, "health": 5 },  
  "keywords": \[\],  
  "mechanics": \["BATTLECRY"\],  
  "text": { "enUS": "Battlecry: Deal 3 damage." },  
  "playConditions": \[\],  
  "abilities": \[  
    {  
      "kind": "BATTLECRY",  
      "targeting": {  
        "mode": "REQUIRED\_IF\_AVAILABLE",  
        "bindAs": "chosenTarget",  
        "selector": {  
          "zone": "PLAY",  
          "entityKind": "CHARACTER",  
          "controller": "ANY",  
          "exclude": \["SELF"\]  
        },  
        "legalityPolicy": "BATTLECRY\_SELECTED\_TARGET"  
      },  
      "effects": \[  
        {  
          "op": "DEAL\_DAMAGE",  
          "amount": { "kind": "CONSTANT", "value": 3 },  
          "recipient": { "kind": "BOUND\_TARGET", "name": "chosenTarget" },  
          "missingRecipient": "SKIP",  
          "modifierPolicy": "NO\_MODIFIERS"  
        }  
      \]  
    }  
  \]  
}

### **CS2\_022: Polymorph**

**Type:** Spell | **Class:** Mage | **Cost:** 4  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_022",  
  "revision": "foundation-v1",  
  "name": "Polymorph",  
  "type": "SPELL",  
  "classes": \["MAGE"\],  
  "baseStats": { "manaCost": 4 },  
  "keywords": \[\],  
  "mechanics": \["TRANSFORM"\],  
  "text": { "enUS": "Transform a minion into a 1/1 Sheep." },  
  "playConditions": \[  
    {  
      "condition": "TARGET\_REQUIRED",  
      "selector": {  
        "zone": "PLAY",  
        "entityKind": "MINION",  
        "controller": "ANY"  
      }  
    }  
  \],  
  "abilities": \[  
    {  
      "kind": "SPELL\_EFFECT",  
      "targeting": {  
        "mode": "REQUIRED",  
        "bindAs": "chosenTarget",  
        "selector": {  
          "zone": "PLAY",  
          "entityKind": "MINION",  
          "controller": "ANY"  
        },  
        "legalityPolicy": "SPELL\_SELECTED\_TARGET"  
      },  
      "effects": \[  
        {  
          "op": "TRANSFORM",  
          "recipient": { "kind": "BOUND\_TARGET", "name": "chosenTarget" },  
          "targetDefinition": "CS2\_022t"  
        }  
      \]  
    }  
  \]  
}

### **CS2\_032\_SPELL: Flamestrike**

**Type:** Spell | **Class:** Mage | **Cost:** 7  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_032\_SPELL",  
  "revision": "foundation-v1",  
  "name": "Flamestrike",  
  "type": "SPELL",  
  "classes": \["MAGE"\],  
  "baseStats": { "manaCost": 7 },  
  "keywords": \[\],  
  "mechanics": \[\],  
  "text": { "enUS": "Deal 5 damage to all enemy minions." },  
  "playConditions": \[\],  
  "abilities": \[  
    {  
      "kind": "SPELL\_EFFECT",  
      "effects": \[  
        {  
          "op": "DEAL\_DAMAGE",  
          "amount": { "kind": "CONSTANT", "value": 5 },  
          "recipient": {  
            "kind": "QUERY",  
            "zone": "PLAY",  
            "entityKind": "MINION",  
            "controller": "OPPONENT\_OF\_EFFECT\_CONTROLLER"  
          },  
          "application": "SINGLE\_DAMAGE\_BATCH",  
          "modifierPolicy": "SPELL\_DAMAGE"  
        }  
      \]  
    }  
  \]  
}

### **CS2\_105: Novice Engineer (Draw / Battlecry)**

**Type:** Minion | **Class:** Neutral | **Cost:** 2 | **Attack:** 1 | **Health:** 1  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_105",  
  "revision": "foundation-v1",  
  "name": "Novice Engineer",  
  "type": "MINION",  
  "classes": \["NEUTRAL"\],  
  "baseStats": { "manaCost": 2, "attack": 1, "health": 1 },  
  "keywords": \[\],  
  "mechanics": \["BATTLECRY"\],  
  "text": { "enUS": "Battlecry: Draw a card." },  
  "playConditions": \[\],  
  "abilities": \[  
    {  
      "kind": "BATTLECRY",  
      "effects": \[  
        {  
          "op": "DRAW\_CARD",  
          "count": 1,  
          "targetPlayer": "SELF"  
        }  
      \]  
    }  
  \]  
}

### **CS2\_091: Fiery War Axe (Weapon)**

**Type:** Weapon | **Class:** Warrior | **Cost:** 3 | **Attack:** 3 | **Durability:** 2  
{  
  "schemaVersion": "1.0",  
  "cardId": "CS2\_091",  
  "revision": "foundation-v1",  
  "name": "Fiery War Axe",  
  "type": "WEAPON",  
  "classes": \["WARRIOR"\],  
  "baseStats": { "manaCost": 3, "attack": 3, "durability": 2 },  
  "keywords": \[\],  
  "mechanics": \[\],  
  "text": { "enUS": "" },  
  "playConditions": \[\],  
  "abilities": \[\]  
}

### **EX1\_096: Loot Hoarder (Deathrattle)**

**Type:** Minion | **Class:** Neutral | **Cost:** 2 | **Attack:** 2 | **Health:** 1  
{  
  "schemaVersion": "1.0",  
  "cardId": "EX1\_096",  
  "revision": "foundation-v1",  
  "name": "Loot Hoarder",  
  "type": "MINION",  
  "classes": \["NEUTRAL"\],  
  "baseStats": { "manaCost": 2, "attack": 2, "health": 1 },  
  "keywords": \[\],  
  "mechanics": \["DEATHRATTLE"\],  
  "text": { "enUS": "Deathrattle: Draw a card." },  
  "playConditions": \[\],  
  "abilities": \[  
    {  
      "kind": "DEATHRATTLE",  
      "effects": \[  
        {  
          "op": "DRAW\_CARD",  
          "count": 1,  
          "targetPlayer": "CONTROLLER\_AT\_DEATH"  
        }  
      \]  
    }  
  \]  
}