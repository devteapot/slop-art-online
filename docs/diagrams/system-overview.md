# System Overview

Three-tier architecture: Bevy Client ↔ SpacetimeDB ↔ LLM Bridge ↔ LLM backends.

```mermaid
graph TD
    subgraph Client["🎮 Bevy Client"]
        FU[FixedUpdate 60Hz<br/>prediction, physics]
        UP[Update uncapped<br/>rendering, interpolation]
    end

    subgraph STDB["🗄️ SpacetimeDB"]
        Tables[Game State Tables<br/>Players, NPCs, World, Items]
        Tick[NPC Tick Scheduler<br/>every 500ms]
        Reducers[Reducers<br/>validate + execute actions]
        BT[Behavior Tree Evaluator<br/>deterministic, per-NPC]
        Identity[NPC Identity<br/>personality, beliefs, knowledge<br/>goals, relations, emotions]
        Pending[NpcPendingDecision]
    end

    subgraph Bridge["🌉 LLM Bridge"]
        Router[Decision Router<br/>stateless, async]
        Prompt[Prompt Assembly]
        Parse[Response Parser<br/>+ Validation]
    end

    subgraph LLM["🧠 LLM Backends"]
        Cloud[Cloud API<br/>Claude / GPT-4o<br/>Key NPCs]
        Local[Local Ollama<br/>Llama 3 8B<br/>Common NPCs]
    end

    Client <-->|WebSocket| STDB
    Tick --> BT
    BT --> Reducers
    Tick -->|rare: dawn, exhaustion,<br/>near-death, goal change| Pending
    Pending -->|subscription| Router
    Router --> Prompt
    Prompt --> Cloud
    Prompt --> Local
    Cloud --> Parse
    Local --> Parse
    Parse -->|submit_npc_* reducer| Reducers
    Identity --> BT
    Reducers --> Tables
    Tables --> Identity

    style Client fill:#f5a623,stroke:#333,color:#000
    style STDB fill:#4a90d9,stroke:#333,color:#fff
    style Bridge fill:#7ed321,stroke:#333,color:#000
    style LLM fill:#9b59b6,stroke:#333,color:#fff
```

**Status:** Reflects current implementation. The bridge currently routes 8 decision types (combat_start, combat_update, post_combat, idle, social, reflection, dawn, significant). Target v2 simplifies to 3 (tree_generation, experience, conversation).
