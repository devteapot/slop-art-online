# When the LLM Is Called

All paths that lead to an LLM call, and the cost model.

```mermaid
flowchart TD
    subgraph Triggers["What triggers an LLM call?"]
        Dawn["🌅 Dawn<br/>New day, plan the day"]
        Exhaust["😴 Tree Exhaustion<br/>N ticks with no action"]
        GoalDone["🎯 Goal Completed/Failed<br/>Tree is obsolete"]
        Knowledge["📚 Major Knowledge Gain<br/>New category learned"]
        NearDeath["💀 Near-Death Survival<br/>Health < 10%"]
        SelfReq["🔄 RequestNewTree<br/>BT action node"]
        SigEvent["⚡ Significant Event<br/>Betrayal, major discovery"]
        Novel["💬 Novel Conversation<br/>No template/knowledge match"]
    end

    subgraph Types["Decision Types"]
        TreeGen["🌳 Tree Generation<br/>Returns: unified behavior tree"]
        ExpEval["🔍 Experience Evaluation<br/>Returns: identity deltas<br/>(personality, beliefs, knowledge)"]
        ConvGen["💬 Conversation Content<br/>Returns: response text"]
    end

    Dawn --> TreeGen
    Exhaust --> TreeGen
    GoalDone --> TreeGen
    Knowledge --> TreeGen
    NearDeath --> TreeGen
    SelfReq --> TreeGen

    SigEvent --> ExpEval
    NearDeath --> ExpEval

    Novel --> ConvGen

    subgraph NotTriggers["❌ NOT triggers (handled by tree)"]
        NT1["New enemy appears"]
        NT2["Someone talks to me"]
        NT3["Day/night change"]
        NT4["Emotion spike"]
        NT5["Taking damage"]
        NT6["Item picked up"]
    end

    style Triggers fill:#9b59b6,stroke:#fff,color:#fff
    style Types fill:#2980b9,stroke:#fff,color:#fff
    style NotTriggers fill:#27ae60,stroke:#fff,color:#fff
```

## Cost Model

```mermaid
graph LR
    subgraph Mobs["🐺 Mobs (thousands)"]
        M1["Static default trees"]
        M2["No LLM ever"]
        M3["Cost: $0"]
    end

    subgraph Common["🛡️ Common NPCs (hundreds)"]
        C1["Tree at dawn: 1 call"]
        C2["Rare events: 1-4 calls"]
        C3["Cost: ~2-5 calls/day"]
    end

    subgraph Key["👑 Key NPCs (dozens)"]
        K1["Tree at dawn: 1 call"]
        K2["Events: 2-5 calls"]
        K3["Novel conversations: 5-20 calls"]
        K4["Cost: ~10-30 calls/day"]
    end

    style Mobs fill:#27ae60,stroke:#fff,color:#fff
    style Common fill:#f39c12,stroke:#fff,color:#000
    style Key fill:#e74c3c,stroke:#fff,color:#fff
```

## What the tree handles without LLM

```mermaid
graph TD
    Tree["🌳 Existing Behavior Tree<br/>(generated once, lasts all day)"]

    Tree --> Combat["⚔️ Combat<br/>EmotionAbove/Below gates<br/>StrengthAdvantage checks"]
    Tree --> Social["💬 Conversation<br/>Template responses ~95%<br/>Knowledge-based answers"]
    Tree --> Movement["🚶 Movement<br/>TravelToEntity, Patrol<br/>GoHome at night"]
    Tree --> Trade["💰 Trade<br/>BuyItem, SellItem<br/>knowledge-gated"]
    Tree --> Emotional["😡 Emotional reactions<br/>EmotionAbove(anger) → attack<br/>EmotionAbove(fear) → flee"]
    Tree --> Identity["🧠 Identity updates<br/>SetBelief, AddKnowledge<br/>AdjustRelationship"]

    style Tree fill:#2c3e50,stroke:#fff,color:#fff
```

**Status:** Currently using v1 decision types (8 types, more LLM calls). Target v2 simplifies to 3 types with much lower call volume.
