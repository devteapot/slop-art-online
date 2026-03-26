# Unified Behavior Tree Structure

Priority layers and how emotions/knowledge gate branches.

```mermaid
graph TD
    Root[Select - Priority Root]

    subgraph Reactive["⚡ Reactive Layer (highest priority)"]
        R1[Sequence]
        R1A[IsBeingAttacked]
        R1B[CombatResponse subtree]
        R2[Sequence]
        R2A[BeingAddressedInConversation]
        R2B[ConversationProtocol subtree]
    end

    subgraph Awareness["👁️ Awareness Layer"]
        A1[Sequence]
        A1A[EnemyDetected]
        A1B["NOT(IsBeingAttacked)"]
        A1C[EvaluateStrength]
        A1D[Select - Response]
        A1D1["Sequence: GoalRequires + EmotionBelow(fear) → Attack"]
        A1D2["Sequence: StrengthAdvantage + EmotionAbove(anger) → Intimidate"]
        A1D3["Sequence: SetBelief(spotted) + KeepDistance → Continue"]
    end

    subgraph Daily["🏠 Daily Life Layer"]
        D1["Sequence: GoalActive(trade) → TravelTo(Market) → Trade"]
        D2["Sequence: HasKnowledge(nav) → Explore"]
        D3["Sequence: IsNightTime → GoHome → Rest"]
    end

    subgraph Fallback["🔄 Fallback Layer"]
        F1[Wander]
    end

    Root --> R1
    Root --> R2
    Root --> A1
    Root --> D1
    Root --> D2
    Root --> D3
    Root --> F1

    R1 --> R1A
    R1 --> R1B
    R2 --> R2A
    R2 --> R2B
    A1 --> A1A
    A1 --> A1B
    A1 --> A1C
    A1 --> A1D
    A1D --> A1D1
    A1D --> A1D2
    A1D --> A1D3

    style Reactive fill:#e74c3c,stroke:#fff,color:#fff
    style Awareness fill:#f39c12,stroke:#fff,color:#fff
    style Daily fill:#27ae60,stroke:#fff,color:#fff
    style Fallback fill:#95a5a6,stroke:#fff,color:#fff
```

## How personality shapes the tree

The LLM generates different trees for different NPCs. The **structure itself** embodies personality:

```mermaid
graph LR
    subgraph Guard["Guard NPC (cautious)"]
        G1["EnemyDetected → Observe + KeepDistance (default)"]
        G2["Only attack if: mission requires OR anger > 0.7"]
    end

    subgraph Bandit["Bandit NPC (aggressive)"]
        B1["EnemyDetected → Attack if can win (default)"]
        B2["Only flee if: outmatched AND fear > 0.8"]
    end

    style Guard fill:#3498db,stroke:#fff,color:#fff
    style Bandit fill:#e74c3c,stroke:#fff,color:#fff
```

**Key insight:** Personality is baked into tree structure at generation time. Emotions add runtime variation via condition gates.

**Status:** Planned (v2). Currently using separate combat_tree + life_tree with mode switching.
