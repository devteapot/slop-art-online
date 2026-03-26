# NPC Identity Model

Six identity components and how they relate to each other and the behavior tree.

```mermaid
graph TD
    subgraph Identity["NPC Identity (persisted, evolves)"]
        P[🎭 Personality<br/>aggression, sociability<br/>curiosity, courage<br/>empathy, discipline]
        B[💭 Beliefs<br/>subjective assessments<br/>confidence 0-1<br/>can be wrong]
        K[📚 Knowledge<br/>learned mechanics<br/>expands action space<br/>shareable]
        G[🎯 Goals<br/>long-term desires<br/>priority levels<br/>success conditions]
        R[🤝 Relations<br/>disposition -100 to +100<br/>per entity<br/>with context]
        E[❤️ Emotions<br/>anger, fear, joy<br/>sadness, surprise, disgust<br/>changes every tick]
    end

    subgraph Runtime["Runtime Systems"]
        BT[🌳 Behavior Tree<br/>unified, one per NPC]
        Tick[⏱️ Tick Loop<br/>every 500ms]
        Decay[📉 Emotion Decay<br/>lerp toward baseline]
    end

    subgraph External["LLM (rare calls)"]
        TreeGen[🌱 Tree Generation<br/>~1-3 per NPC per day]
        ExpEval[🔍 Experience Eval<br/>after significant events]
    end

    P -->|defines baselines| Decay
    P -->|shapes structure| TreeGen
    E -->|gates branches| BT
    B -->|informs conditions| BT
    K -->|expands available actions| TreeGen
    K -->|gates concrete refs| BT
    G -->|drives daily life layer| TreeGen
    R -->|affects social responses| BT

    Decay -->|each tick| E
    Tick --> Decay
    Tick --> BT

    TreeGen -->|new tree| BT
    ExpEval -->|identity deltas| P
    ExpEval -->|new beliefs| B
    ExpEval -->|new knowledge| K
    ExpEval -->|goal changes| G
    ExpEval -->|relationship shifts| R
    ExpEval -->|emotion adjustments| E

    BT -->|inline actions| B
    BT -->|inline actions| K
    BT -->|inline actions| R
    BT -->|inline actions| E

    style Identity fill:#2c3e50,stroke:#fff,color:#fff
    style Runtime fill:#2980b9,stroke:#fff,color:#fff
    style External fill:#8e44ad,stroke:#fff,color:#fff
```

**Status:** Personality, Knowledge, and Emotions tables are planned (v2). Beliefs, Goals, and Relations are implemented (v1). Inline BT identity actions are partially implemented (SetBelief exists, AddKnowledge/TriggerEmotion planned).
