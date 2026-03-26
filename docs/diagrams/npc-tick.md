# NPC Tick Loop

What happens every 500ms for each NPC.

## Target (v2)

```mermaid
flowchart TD
    Start([Tick fires every 500ms]) --> Decay[Apply emotion decay<br/>lerp toward personality baseline]
    Decay --> Eval[Evaluate current_tree<br/>with runtime state]
    Eval --> Action{Action<br/>produced?}

    Action -->|Yes| Exec[Execute action<br/>deterministic side effects]
    Action -->|No| Exhaust[Increment exhaustion counter]

    Exec --> InlineID{Inline identity<br/>action?}
    InlineID -->|SetBelief, AddKnowledge<br/>AdjustRelationship, TriggerEmotion| UpdateID[Write to identity tables<br/>zero LLM cost]
    InlineID -->|No| RegenCheck

    UpdateID --> RegenCheck{Check regen<br/>triggers}
    Exhaust --> RegenCheck

    RegenCheck -->|Tree exhausted?<br/>Goal completed?<br/>Near-death?| Regen[Create NpcPendingDecision<br/>type: tree_generation]
    RegenCheck -->|No trigger| SigCheck

    Regen --> SigCheck{Significant<br/>event?}
    SigCheck -->|Near-death, betrayal<br/>major discovery| ExpEval[Create NpcPendingDecision<br/>type: experience]
    SigCheck -->|No| Done([Next NPC])
    ExpEval --> Done

    style Start fill:#3498db,stroke:#fff,color:#fff
    style Done fill:#3498db,stroke:#fff,color:#fff
    style Regen fill:#9b59b6,stroke:#fff,color:#fff
    style ExpEval fill:#9b59b6,stroke:#fff,color:#fff
    style UpdateID fill:#27ae60,stroke:#fff,color:#fff
```

## Current (v1)

```mermaid
flowchart TD
    Start([Tick fires]) --> Mode{Check mode}

    Mode -->|sleeping| Sleep[Walk home + regen 5%/tick]
    Mode -->|combat| Combat[Evaluate combat_tree<br/>against nearest player]
    Mode -->|plan| Plan[Execute current plan step<br/>advance step counter]
    Mode -->|life_tree| Life[Evaluate life_tree]
    Mode -->|idle| Idle[Default wander]

    Combat -->|target gone| PostCombat[trigger post_combat decision]
    Combat -->|target present| ExecCombat[Execute combat action]

    Sleep --> Done([Next NPC])
    ExecCombat --> Done
    PostCombat --> Done
    Plan --> Done
    Life --> Done
    Idle --> Done

    style Start fill:#e74c3c,stroke:#fff,color:#fff
    style Mode fill:#e74c3c,stroke:#fff,color:#fff
    style Done fill:#e74c3c,stroke:#fff,color:#fff
```

**Status:** Currently using v1 (mode switching). Migration to v2 (unified tree + emotion decay) is the primary next step.
