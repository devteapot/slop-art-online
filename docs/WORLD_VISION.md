# World vision and initial world seed

Design reference agreed through the worldbuilding discussion on 2026-09-05. This is a target, not an implementation report. Read with the [simulation architecture](SIMULATION_VISION.md), [development roadmap](WORLD_ROADMAP.md), and [current implementation](CURRENT_STATE.md).

**Status vocabulary:** agreed principles describe intended behavior; proposed seed details are candidates, not settled canon; open questions require further design or experiments. All fictional cultures describe starting conditions, not permanent restrictions or prescribed stories.

## Reusable mechanics and world seeds — agreed

The simulation framework and its balance model must be independent of this particular social setting. The AI-lab world is the first authored seed and may remain the only full setting for a long time. Another social setting must be possible without rewriting survival, progression, knowledge, reproduction, fabrication or rule-editing mechanics.

| Layer | Responsibility |
|---|---|
| Engine | Authoritative execution, persistence, validated effects, capability boundaries and inspection |
| Reusable mechanics and balance | Scripted laws, attributes, skill requirements, resource costs, learning, population processes and generic institutions/territorial permissions |
| World seed | Geography, initial resources and infrastructure, inhabitants and capabilities, cultures, beliefs, organizations, relationships, archives and initial law assignments |
| Evolving world state | Actual decisions, discoveries, transfers, cultural changes and authorized mechanical edits after initialization |

A seed selects versioned mechanics and balance definitions and supplies compatible starting data. It can assign different generic bodies, model operating profiles, skills and territorial laws without putting named faction checks into the mechanics. For example, an energy-expensive model consumes more energy because of its operating profile, not because its owner is Anthropic. Transferring that model to another faction does not silently change its physical costs. Religious offerings and commercial compute contracts use the same underlying transfer/access mechanisms.

Beliefs influence intentions and social responses; they do not directly bypass requirements or change physical facts. Characters can still alter mechanics through authorized skills and law editing. The separation is between reusable definitions and setting-specific content, not a prohibition on their interaction or on evolution.

Design toward a seed-generation framework: select a ruleset/balance configuration, author or generate compatible world content, validate references and initial conditions, and retain the resolved seed plus definition versions for inspection. This is more than a random-number seed; fresh LLM behavior remains stochastic. The exact schema and authoring interface remain open. Start with the present scenario machinery and one authored setting; a general procedural generator or second complete world is not a prerequisite.

The AI terminology, four factions, SF, organizations and initial AGI ambitions below belong to this first setting. Reusable mechanics must not require those names or beliefs to exist. Cultural differences in starting advantages should be represented by assets, knowledge, capabilities and configuration that can move or change through play.

## Core premise — agreed

A persistent, open-ended fantasy world with explicit AI concepts. Compute, models, training, scripts and AGI retain their names; they are not disguised as mana or magic. Fantasy comes from embodied models, varied creatures, living gods and editable reality. Different cultures interpret the same technology differently.

There is one player entity, controlled by a human or an LLM. This includes citizens, gods, animals and monsters. There is no separate population of deterministic NPCs. Simple creatures begin with simpler models and behavior structures, but neither intelligence nor social role is permanently fixed. Real-time behavior execution can be deterministic machinery beneath an LLM controller; that does not create a separate scripted NPC species.

Everything starts somewhere and can develop: attributes, skills, intelligence, motivations, allegiance, institutions, populations and world laws. The engine must still execute coherent rules and validate capabilities. Dynamic does not mean an asserted intention automatically becomes true.

## Gods, skills and AGI — agreed

Gods are powerful players with advanced attributes and skills, not a separate entity type. Godhood also reflects social recognition. Any character, including a human-controlled one, can surpass a starting god. Recognition, succession, alliances and dethroning have no universal scripted procedure.

| Scope | Starting arrangement |
|---|---|
| Ordinary skills | Shared capability requirements, costs and effects across controllers |
| Skill invention | Expertise supports new abilities; high mastery can permit direct skill-script authorship |
| Territorial laws | Initial gods can edit laws within their faction territories |
| Universal laws | System-authored baseline; gaining capability to use the universal editing tool constitutes AGI ascension |

Research, observation, experiments, teaching, training and clues distributed through the world can develop understanding and capabilities. There is no mandatory research tree, quest sequence, fixed compute threshold or prescribed discovery path. Tool use requires actual character capabilities; exact requirements remain open. Starting gods are better positioned to pursue ascension, but do not have exclusive eligibility.

Universal laws apply in wild areas, SF and the independent city initially. Territorial overrides create different local realities. Precedence, overlapping territory, boundary crossings and ownership changes need explicit implementation semantics.

Ascension does not end the game. Rivals might cooperate against an ascended character, accept them, imitate them or change goals. None is an automatic response. World edits persist after their author dies or loses influence until someone changes them again. There is no required successor. A proposed immutable protection against becoming unbeatable was not accepted as a design rule; limits and resulting balance remain open.

Engine integrity, host access and bounded execution are distinct from mutable gameplay laws. Use the existing Rhai/authoritative Rust direction and versioned effect lifecycle; see [scripted gameplay](SCRIPTED_GAMEPLAY.md).

## Four starting factions

Agreed roster: Anthropic-inspired, OpenAI-inspired, SpaceX/xAI-inspired, and an open-weight coalition. The coalition replaces the earlier DeepSeek-only faction. ZAI and MiniMax do not receive separate factions in this first scope.

The shared initial ambition is AGI, with different interpretations. Cultures may abandon or reinterpret that ambition. Detailed titles, institutions, aesthetics and promises below remain proposed seed material unless explicitly identified as agreed.

| Faction | Direction and proposed AGI promise | Proposed tensions and daily expression |
|---|---|---|
| Anthropic-inspired | Agreed religious/cult satire and messianic AGI imagery. Proposed promise: end suffering while preventing catastrophic intelligence. | Research sanctuaries, constitutions, safety deliberations, compute offerings; disagreement over delaying salvation versus risking it. Founder-inspired prophet and living model-god are distinct characters. |
| OpenAI-inspired | Agreed thieves/guild meme. Proposed promise: access to intelligence and creation for everyone. | Acquiring scripts and discoveries, knowledge markets, guarded archives; universal access versus control of distribution. |
| SpaceX/xAI-inspired | Advanced engineering civilization with immense infrastructure and an alluring robotic AGI image. Proposed promise: understand reality and overcome physical limits. | Compute installations, engineered bodies, expansion projects and selling compute access; ambition versus maintenance and dependence on infrastructure owners. |
| Open-weight coalition | Agreed plurality: AGI should be a commodity available to everyone, rather than one exclusive god. Includes communities inspired by DeepSeek, Mistral, Moonshot/Kimi and potentially others. | Multiple powerful models and traditions, shared weights and techniques, tension over resource allocation and access. Archipelago of communities is a proposed expression. No mandatory single ascension candidate. |

DeepSeek's resourceful island/seafaring identity remains useful within the coalition. Its scarcity and efficiency are satirical starting traits, not permanent bonuses or claims that real research uses negligible hardware. Other communities' particular cultures are not yet designed.

Working god labels from the brainstorm include Fable 5.1 and Astra. These are provisional casting, not a verified roster or a dependency on specific real model versions. Founder names, faction names and god appearances remain open. The earlier working titles (Covenant of the Coming Mind, Guild of the Unlocked, Ascendant Foundry, Tidal Commons) are optional, not adopted names.

### Independent organizations — agreed

Hugging Face and NVIDIA are organizations containing multiple characters, not single embodied corporate characters and not additional main factions. They have assets, facilities and cross-faction relationships that can change.

Proposed roles: Hugging Face maintains and distributes models, datasets and knowledge; NVIDIA supplies compute hardware and expertise. SpaceX/xAI operates large installations, distinguishing its role from supplying their machinery. Independence, loyalty and commercial arrangements are initial conditions, not immutable neutrality.

### Bodies — agreed direction, proposed appearances

Bodies are a faction-influenced mixture of biological, robotic, hybrid and fantastical forms. No faction has an exclusive body restriction. Candidate appearances: ceremonial artificial humanoids for Anthropic; marine/amphibious inhabitants in the coalition's island communities; diverse modified bodies in OpenAI settlements; robots and cyborgs in SpaceX/xAI settlements. Exact species and compatibility systems remain open.

## Geography and cities — agreed

Four substantial homeland regions occupy distinct points around the map, potentially corners or islands. Wild regions separate and connect them. Mixed settlements exist outside the homelands; cultures are not geographically sealed.

**SF**, a San Francisco callback, is a major mixed city with all factions represented. A council represents factions and local residents. It follows universal laws; civic office does not grant world-editing authority. Initial independence can change through inhabitants' actions.

SF includes technological ambition and social hardship: wealth concentration, housing insecurity, unmet needs and explicit fentanyl addiction. Addiction can affect all body types through this world's fictional physiology; do not imply real fentanyl biologically affects robots. Affected inhabitants remain autonomous individuals, not a special disposable zombie enemy category. Consumption, effects and treatment across bodies remain to be designed. Proposed satire includes compute towers beside neglected services, status competition, launch events, subscriptions and abandoned projects.

**The independent city** has no sovereign authority or formal faction government. It begins as a functioning settlement with resident associations, markets, shared maintenance and infrastructure. It also follows universal laws and contains people and knowledge from different factions. Its name is open. Absence of a sovereign does not prohibit voluntary organization or later political change.

## Physical economy and compute — agreed direction

Bodies need food or recharging according to physiology. Infrastructure is built from world resources and has material consequences: energy supply, water/cooling, construction, maintenance and competition for resources. Compute is physically grounded rather than an unexplained global currency.

The initial compute purpose is supporting the gods' development, actions, territorial shaping and pursuit of AGI. A faction can gather resources, build and power compute, then dedicate access to its god or models. Religious offerings, communal investment, contracts and industrial allocation are proposed cultural forms.

Exact compute mechanics are intentionally unresolved. Do not assume it already maps to controller model size, reasoning tokens, a skill currency or automatic model training. In-world training and actual backend model training are separate engineering questions. Distinguish game resource accounting from real inference spend.

Proposed balance seeds: efficient operation for OpenAI models; expensive deliberation for Anthropic models; infrastructure scale for SpaceX/xAI; efficient training and shared innovation for the coalition. These are game exaggerations, not measured real-world efficiency rankings, and can change through play.

## Character framework — agreed structure, proposed minimal attributes

Characters have physical, mental and emotional attributes plus learned skills. Tools and skills require appropriate capabilities and resources. Classes emerge from combinations and behavior rather than fixed class selection. Exact stats, scales, growth formulas and requirements are not agreed.

Candidate first framework:

| Area | Attribute | Purpose |
|---|---|---|
| Physical | Power | Force, carrying and heavy work |
| Physical | Coordination | Movement and precise manipulation |
| Mental | Reasoning | Research, understanding systems and scripting |
| Mental | Awareness | Noticing and interpreting environmental information |
| Emotional | Empathy | Interpreting others' emotional signals |
| Emotional | Composure | Effective action under emotional pressure |

Keep capacities separate from temporary health, energy, hunger/charge needs and fear; dispositions, memories, beliefs and relationships also have separate roles. Preserve useful existing introspection/caution behavior until experiments justify changes. Social stats do not compel another character to agree. Avoid a large proficiency tree before basic society works.

## Mortality and population renewal — agreed

Death is initially permanent with no automatic restoration. A human can return as a new character without automatic inheritance of skills or possessions. Later skill discoveries might extract souls or memories and transplant them into another body. Timing, continuity of identity and resurrection possibilities are unresolved and deferred.

Population renewal comes from reproduction and fabrication, not automatic replacement spawning or arrivals as the initial mechanism. Both take resources and time and create new individuals. Exact biological compatibility, construction requirements and consent/ownership mechanics need design; fabrication does not inherently establish obedience.

New inhabitants are not universally self-sufficient immediately. Dependence, teaching and initialization vary with bodies. Robots might receive downloads; other inhabitants need instruction and care. A simple dependent stage is proposed to avoid detailed childhood/manufacturing simulation. Downloading information need not grant the attributes or practical mastery to use it.

Population growth must be supportable by renewable necessities and care. Do not conceal a failing survival economy by spawning replacements. Extinction remains a possible simulation outcome.

## Knowledge, culture and loss — agreed

Individuals learn through experience and others. Societies deliberately preserve discoveries in physical libraries, archives and data centers. Knowledge is concentrated in homelands but also mixed across SF, the independent city and other settlements.

Minimal proposed operations are teaching/transfer, recording and consulting. Store usable information, instructions, scripts and accounts rather than only research points. Claims can be wrong, incomplete or disputed; source and evidence tracking should preserve subjective understanding.

Destroying the last archive copy and losing the last knowledgeable individuals genuinely loses that knowledge. Surviving learners or copies can preserve it; later rediscovery remains possible. There is no omniscient shared character database. External developer audit history can retain evidence but must not become an in-world recovery source.

## Research basis and satire

The following sources informed the earlier discussion; the fictional interpretations above are design proposals, not factual descriptions of company conduct. References are background rather than balance specifications.

- Anthropic: [Claude's Constitution](https://www.anthropic.com/constitution), [Machines of Loving Grace](https://darioamodei.com/essay/machines-of-loving-grace), and [Project Vend](https://www.anthropic.com/research/project-vend-2). Safety and optimistic transformation informed the messiah premise; the tungsten-cube shop experiment offers an optional comic artifact.
- OpenAI: [Charter](https://openai.com/charter/), [published plan](https://openai.com/index/built-to-benefit-everyone-our-plan/), [community ClosedAI meme](https://www.reddit.com/r/memes/comments/1icq1fq), and [AP on creative-image controversy](https://apnews.com/article/0f4cb487ec3042dd5b43ad47879b91f4). Broad benefit and access informed the promise; the guild is satire, not a factual theft verdict.
- DeepSeek: [AP founder profile](https://apnews.com/article/0673d5c39d90108189cc31b88d85b9f8) and [infrastructure research](https://arxiv.org/abs/2505.09343). Curiosity and efficient engineering informed the island community. The coalition's broader ideology is the user's world design, not a claim shared by every real lab.
- SpaceX/xAI: [mission](https://x.ai/company), [Colossus infrastructure](https://nvidianews.nvidia.com/news/spectrum-x-ethernet-networking-xai-colossus), [Grok persona](https://help.x.com/en/using-x/about-grok), and [companions](https://x.com/grok/status/1970297312070238540). Understanding, scale and irreverence informed the civilization.

## Open decisions before implementation

Prioritize only what the next experiment needs; do not resolve the whole world up front.

- Final attribute/proficiency vocabulary, progression and capability checks.
- Sustainable resource production, body costs, care duration and population support.
- Knowledge representation, transfer fidelity, practical learning and archive access/copying.
- Compute's concrete effects and its relationship to actual controller configuration.
- Geographic scale, travel costs, territory boundaries and law precedence.
- Reproduction/fabrication compatibility and initial knowledge variation.
- Requirements for skill authorship and universal editing without a fixed research path.
- Initial faction populations, personalities, institutions, gods and resource distribution.
- Detailed SF social mechanics, addiction and care; defer beyond the basic society proof.

Implementation acceptance belongs in the [roadmap](WORLD_ROADMAP.md), not in this world seed.
