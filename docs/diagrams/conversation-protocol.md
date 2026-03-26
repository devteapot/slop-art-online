# Conversation Protocol

How NPCs handle conversations within the behavior tree. Listening is separated from responding — information is never lost by giving a template response.

```mermaid
sequenceDiagram
    participant P as Player/NPC
    participant L as Listening System<br/>(always active)
    participant R as Response Selector
    participant LLM as LLM Bridge<br/>(rare)

    P->>L: Speech event
    Note over L: Assess engagement level<br/>(focused/attentive/overhearing/distant)

    L->>L: Parse keywords, extract topic
    L->>L: Calculate confidence<br/>= base × engagement × topic_relevance
    L->>L: Update beliefs/knowledge<br/>at calculated confidence
    L->>L: Log detailed event<br/>(time, place, speaker, content)

    Note over L: Information captured regardless<br/>of response quality

    L->>R: Trigger response selection

    alt Matches template (~60%)
        R->>P: SayTemplate("greeting_response")
    else Topic matches knowledge (~25%)
        R->>P: SayFromKnowledge(topic)
    else Emotion-colored template (~10%)
        R->>P: SayTemplate("nervous_deflection")
    else Important conversation (~5%)
        R->>LLM: GenerateLlmResponse(context)
        LLM->>R: Novel response text
        R->>P: SayGenerated
    else Nothing matches
        R->>P: SayTemplate("Hmm, I see.")
    end
```

## Engagement Confidence Calculation

```mermaid
graph LR
    Speech[Speech Event] --> Eng{Engagement?}

    Eng -->|Focused: in active convo| E1["× 1.0"]
    Eng -->|Attentive: nearby, idle| E2["× 0.5"]
    Eng -->|Overhearing: nearby, busy| E3["× 0.2"]
    Eng -->|Distant: edge of range| E4["× 0.1"]

    E1 --> Topic{Topic relevant<br/>to role/goals?}
    E2 --> Topic
    E3 --> Topic
    E4 --> Topic

    Topic -->|Yes| TR1["× 1.0"]
    Topic -->|No| TR2["× 0.5"]

    TR1 --> Result[effective_confidence<br/>= base × engagement × relevance]
    TR2 --> Result

    Result --> Store[Store as belief/knowledge<br/>at this confidence]

    style Speech fill:#3498db,stroke:#fff,color:#fff
    style Result fill:#27ae60,stroke:#fff,color:#fff
    style Store fill:#2c3e50,stroke:#fff,color:#fff
```

### Worked Example

"The dragon burned down the eastern village" spoken in Market Square:

```mermaid
graph TD
    Speech["🗣️ 'Dragon burned eastern village'"]

    Speech --> Guard1["Guard (in convo)<br/>1.0 × 1.0 = <b>1.0</b><br/>'Dragon attacked!' (certain)"]
    Speech --> Guard2["Guard (patrolling)<br/>0.5 × 1.0 = <b>0.5</b><br/>'Heard about a dragon' (moderate)"]
    Speech --> Smith["Blacksmith (forging)<br/>0.2 × 0.5 = <b>0.1</b><br/>'Something about a dragon?' (vague)"]
    Speech --> Merchant["Merchant (far away)<br/>0.1 × 0.5 = <b>0.05</b><br/>'...' (barely registered)"]

    style Guard1 fill:#27ae60,stroke:#fff,color:#fff
    style Guard2 fill:#f39c12,stroke:#fff,color:#000
    style Smith fill:#e67e22,stroke:#fff,color:#fff
    style Merchant fill:#e74c3c,stroke:#fff,color:#fff
```

**Status:** Planned (v2). Currently conversations trigger a "social" decision type that calls the LLM for every response.
