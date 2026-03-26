# Knowledge-Gated Action Progression

How NPCs progress from vague to concrete actions as they learn through experience.

```mermaid
graph TD
    subgraph Stage1["Stage 1: No Knowledge"]
        S1NPC["NPC is hurt<br/>never seen healing"]
        S1Tree["Tree: HealthBelow(0.5) → Rest<br/>(only option: sit and regen)"]
        S1NPC --> S1Tree
    end

    subgraph Stage2["Stage 2: Vague Knowledge"]
        S2Learn["Overheard: 'potions heal you'<br/>confidence: 0.2"]
        S2Tree["Tree: HealthBelow(0.5) → SearchFor('healing')<br/>(wander looking for anything healing-related)"]
        S2Discover["Runtime: finds a potion!<br/>→ AddKnowledge fires"]
        S2Learn --> S2Tree
        S2Tree --> S2Discover
    end

    subgraph Stage3["Stage 3: Concrete Knowledge"]
        S3Know["Knowledge: item_def:12 is a health potion<br/>available at POI:3 (Market Square)<br/>confidence: 0.9"]
        S3Tree["Tree: HealthBelow(0.5)<br/>→ TravelToEntity(Poi, 3)<br/>→ BuyItem(from_npc:5, item:12, max:15)<br/>→ UseItem(item:12)"]
        S3Know --> S3Tree
    end

    Stage1 -->|overhears conversation<br/>about healing| Stage2
    Stage2 -->|discovers potion<br/>through SearchFor| Stage3
    Stage3 -->|teaches other NPC<br/>via gossip| Propagate["Other NPC gains<br/>knowledge at reduced<br/>confidence"]

    style Stage1 fill:#e74c3c,stroke:#fff,color:#fff
    style Stage2 fill:#f39c12,stroke:#fff,color:#000
    style Stage3 fill:#27ae60,stroke:#fff,color:#fff
    style Propagate fill:#3498db,stroke:#fff,color:#fff
```

## How knowledge gates the LLM prompt

```mermaid
graph LR
    subgraph Context["LLM Prompt Context"]
        NPC["NPC State:<br/>health: 30/100<br/>position: near market"]
        Know["NPC Knowledge:<br/>- item_def:12 = health potion<br/>- POI:3 = Market Square<br/>- NPC:5 = Potion Merchant"]
        NoKnow["NOT in knowledge:<br/>- Blacksmith's forge<br/>- Magic scrolls<br/>- Eastern cave"]
    end

    subgraph Constraint["Prompt Constraint"]
        Rule["'Only reference entities<br/>in NPC's knowledge'"]
    end

    subgraph Generated["LLM Generates"]
        Valid["✅ TravelToEntity(Poi, 3)<br/>✅ BuyItem(from_npc:5, item:12)<br/>✅ UseItem(item:12)"]
        Invalid["❌ Cannot generate:<br/>TravelToEntity(Poi, 7)<br/>BuyItem(item:42)"]
    end

    Context --> Constraint
    Constraint --> Generated

    style Valid fill:#27ae60,stroke:#fff,color:#fff
    style Invalid fill:#e74c3c,stroke:#fff,color:#fff
```

## The mob learning path

```mermaid
graph TD
    Wolf["🐺 Wolf (mob)<br/>Static default tree<br/>Zero LLM cost<br/>Zero knowledge"]

    Wolf -->|survives many fights| Learn1["Gains knowledge:<br/>'players with shields are hard to kill'<br/>(via inline AddKnowledge action)"]
    Learn1 -->|first knowledge in<br/>'combat' category| Trigger["Major knowledge gain trigger<br/>→ NpcPendingDecision"]
    Trigger -->|LLM generates| SmartWolf["🐺 Smarter Wolf<br/>LLM-generated tree with<br/>shield-avoidance tactics<br/>Now more dangerous than kin"]

    Note["This is emergent, not scripted.<br/>Significance threshold is set<br/>very high for mobs."]

    style Wolf fill:#95a5a6,stroke:#fff,color:#fff
    style SmartWolf fill:#e74c3c,stroke:#fff,color:#fff
    style Note fill:#2c3e50,stroke:#fff,color:#fff
```

**Status:** Planned (v2). Requires NpcKnowledge table, SearchFor runtime resolution, and knowledge-gated LLM prompt constraints.
