// Default world policy. Rust supplies facts and commits validated effects.
fn bounded(v, lo, hi) { if v < lo { lo } else if v > hi { hi } else { v } }
fn distance(a, b) { if a > b { a-b } else { b-a } }
fn authorize_update(c) { c.operator }
fn authorize_effect(c) { true } // Installed definitions are operator-controlled in this slice.
fn cost(name) {
    switch name { "move" => 1, "gather" => 4, "attack" => 8, _ => 0 }
}
fn validate_common(c) {
    let a = c.action;
    if a.duration < 1 || a.duration > 5 { return "duration must be 1..5"; }
    if (c.allowed != "destination" && a.destination != ()) ||
       (c.allowed != "target" && a.target != ()) ||
       (c.allowed != "text" && a.text != ()) { return "skill contains arguments for a different skill"; }
    ""
}
fn outcome(status, reason, remaining, state, effects, progress) {
    #{status:status, reason:reason, remaining:remaining, state:state, effects:effects, progress:progress}
}
fn done(effects) { outcome("success", "", 0, (), effects, #{}) }
fn failed(reason) { outcome("failure", reason, 0, (), [], #{}) }
fn metabolism(p) { #{hunger:bounded(p.hunger+2,0,100), fear:bounded(p.fear-1,0,100)} }
fn aftermath(c) { #{starvation:if c.actor.hunger >= 100 { 8 } else { 0 }, hazard:if c.site == () { 0 } else { c.site.hazard }} }
fn on_damage(c) {
    let p=c.actor;
    let health=bounded(p.health-c.amount,0,100);
    #{health:health, fear:bounded(p.fear+15,0,100), caution:bounded(p.caution+1+p.introspection/25,0,100),
      learn_danger:c.nature != "starvation", confidence:95, interrupt:true, dead:health == 0}
}
fn reflection(c) {
    #{caution:bounded(c.actor.caution+c.caution_delta,0,100), trust:bounded(c.trust+c.trust_delta,-100,100), confidence:60}
}
fn validate_reflection(r) {
    if r.interpretation.trim() == "" || r.interpretation.len() > 2000 ||
       r.caution_delta < -10 || r.caution_delta > 10 || r.trust_delta < -10 || r.trust_delta > 10 {
        return "invalid interpretation/delta";
    }
    ""
}
fn visible(c) {
    c.viewer.health > 0 && (c.other.health > 0 || c.kind == "death") && c.viewer.id != c.other.id &&
    distance(c.viewer.position,c.other.position) <= (if c.kind == "speech" { 2 } else { 1 })
}
fn observation(site) { #{food:if site == () { 0 } else { site.food }} }
fn memory_limit(c) { 16 }
fn reconsider_interval(p) { 4+(100-p.introspection)/10 }
fn bootstrap(p) { if p.food > 0 && p.hunger >= 25 { "eat" } else if p.energy < 35 { "rest" } else { "wait" } }
fn guard(c) {
    let p=c.player; let cond=c.condition;
    switch cond.kind {
        "all" | "any" => {
            let result=cond.kind == "all"; let sources=[];
            for child in cond.conditions {
                let item=guard(#{player:p,condition:child});
                if cond.kind == "all" { result=result && item[0]; } else { result=result || item[0]; }
                for source in item[1] { sources.push(source); }
            }
            [result,sources]
        },
        "not" => { let item=guard(#{player:p,condition:cond.condition}); [!item[0],item[1]] },
        "at" => [p.position == cond.location,[]],
        "danger" => {
            let location=if cond.location == () { p.position } else { cond.location };
            for belief in p.beliefs { if belief.claim.location == location { return [belief.claim.danger,[belief.source]]; } }
            [false,[]]
        },
        "food_at" => {
            let found=false; let enough=false; let source=0;
            for memory in p.memories {
                if memory.kind == "site" && memory.location == cond.location {
                    found=true; enough=memory.content.food >= cond.minimum; source=memory.source;
                }
            }
            [found && enough,if found { [source] } else { [] }]
        },
        "resource" => {
            let actual=p[cond.resource];
            [if cond.comparison == "below" { actual < cond.value } else { actual >= cond.value },[]]
        },
        _ => throw "unknown condition"
    }
}

fn validate_dialogue(c) {
    if c.expires_tick <= c.tick || c.expires_tick > c.tick+30 {
        return "speech expiry must be within next 30 ticks";
    }
    ""
}
fn validate_condition(c) {
    if (c.kind == "at" || c.kind == "food_at" || c.kind == "danger") && c.location != () &&
       (c.location < -10 || c.location > 10) { return "condition location outside known world bounds"; }
    if c.kind == "resource" && (c.value < 0 || c.value > 100) { return "resource threshold must be 0..100"; }
    if c.kind == "food_at" && (c.minimum < 1 || c.minimum > 100) { return "food minimum must be 1..100"; }
    ""
}
