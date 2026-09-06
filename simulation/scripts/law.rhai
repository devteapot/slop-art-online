// Default world policy. Rust supplies facts and commits validated effects.
fn bounded(v, lo, hi) { if v < lo { lo } else if v > hi { hi } else { v } }
fn distance(a, b) { if a > b { a-b } else { b-a } }
fn authorize_update(c) { c.operator }
fn authorize_effect(c) { true } // Actor-authored scope overlays can replace this permission policy.
fn cost(name) {
    switch name { "move" => 1, "gather" => 4, "attack" => 8, _ => 0 }
}
fn validate_common(c) {
    let a = c.action;
    if a.duration < 1 || a.duration > 5 { return "duration must be 1..5"; }
    if (!c.allowed.contains("destination") && a.destination != ()) ||
       (!c.allowed.contains("target") && a.target != ()) ||
       (!c.allowed.contains("text") && a.text != ()) ||
       (!c.allowed.contains("record") && a.record != ()) ||
       (!c.allowed.contains("archive") && a.archive != ()) ||
       (!c.allowed.contains("infrastructure") && a.infrastructure != ()) { return "skill contains arguments for a different skill"; }
    ""
}
fn outcome(status, reason, remaining, state, effects, progress) {
    #{status:status, reason:reason, remaining:remaining, state:state, effects:effects, progress:progress}
}
fn done(effects) { outcome("success", "", 0, (), effects, #{}) }
fn failed(reason) { outcome("failure", reason, 0, (), [], #{}) }
fn metabolism(p) { #{hunger:if p.body != () && p.body.support == "electric" {0} else {bounded(p.hunger+2*p.pulses,0,100)}, fear:bounded(p.fear-p.pulses,0,100)} }
fn food_renewal(c) { bounded(c.source.amount*c.pulses,0,if c.food < c.source.capacity { c.source.capacity-c.food } else { 0 }) }
fn needs_care(c) { c.health > 0 && c.dependent && c.hunger >= 35 }
fn development(c) { c.age_ms >= 60000 && c.care_meals >= 2 && c.practice >= 1 }
fn population_costs(c) {
    #{offer_ms:90000, reproduction_ms:30000, parent_food:2, parent_energy:10,
      fabrication_ms:45000, fabrication_food:6, fabrication_energy:30,
      care_ms:3000, care_energy:2, nutrition:35, practice_ms:5000, practice_energy:4}
}
fn aftermath(c) {
    let cold=0;
    if c.weather != () && c.time_ms >= c.weather.cold_after_ms {
        let shelter=if c.site == () { 0 } else { c.site.shelter };
        let boundary=if c.weather.cold_after_ms > 0 { c.weather.cold_after_ms-1 } else { 0 };
        let period=c.elapsed_ms/c.pulses;
        // Newborn hazard clocks start at birth. Count their actual due pulse
        // timestamps, including when an update batches pulses across cold onset.
        let cold_pulses=if c.last_hazard_pulse_ms == () {
            bounded(c.time_ms/period-boundary/period,0,c.pulses)
        } else if c.last_hazard_pulse_ms < c.weather.cold_after_ms { 0 }
        else { bounded((c.last_hazard_pulse_ms-c.weather.cold_after_ms)/period+1,0,c.pulses) };
        if shelter < c.weather.shelter_required { cold=c.weather.damage_per_pulse*cold_pulses; }
    }
    #{starvation:if c.body != () && c.body.support == "electric" {0} else if c.actor.hunger >= 100 { 8*c.pulses } else { 0 },
      power_depletion:if c.body != () && c.body.support == "electric" {8*c.body.unpaid_support_pulses} else {0},
      hazard:if c.site == () { 0 } else { c.site.hazard*c.pulses }, cold:cold}
}
fn on_damage(c) {
    let p=c.actor;
    let health=bounded(p.health-c.amount,0,100);
    #{health:health, fear:bounded(p.fear+15,0,100), caution:bounded(p.caution+1+p.introspection/25,0,100),
      learn_danger:c.nature != "starvation" && c.nature != "weather" && c.nature != "power_depletion", confidence:95,
      interrupt:health == 0 || (c.nature != "starvation" && c.nature != "weather" && c.nature != "power_depletion"), dead:health == 0}
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
    c.distance <= (if c.kind == "speech" { 2 } else { 1 })
}
fn observation(site) { #{food:if site == () { 0 } else { site.food }, shelter:if site == () { 0 } else { site.shelter }, buildable:site != ()} }
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
        "has_knowledge" => {
            for holding in p.knowledge { if holding.record.id == cond.record { return [true,[holding.source]]; } }
            [false,[]]
        },
        "needs_care" => {
            for seen in p.care_observations {
                if seen.id == cond.target {
                    return [seen.location == p.position && seen.dependent && seen.needs_care,[seen.source]];
                }
            }
            [false,[]]
        },
        "danger" => {
            let location=if cond.location == () { p.position } else { cond.location };
            for belief in p.beliefs { if belief.claim.location == location { return [belief.claim.danger,[belief.source]]; } }
            [false,[]]
        },
        "food_at" | "shelter_at" => {
            let found=false; let enough=false; let source=0;
            for memory in p.site_observations {
                if memory.kind == "site" && memory.location == cond.location {
                    found=true; enough=memory.content[if cond.kind == "food_at" { "food" } else { "shelter" }] >= cond.minimum; source=memory.source;
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
fn valid_location(map, p) {
    if map == () { return p >= -10 && p <= 10; }
    if p < 0 || p >= map.width * map.height { return false; }
    if "bounds" in map && map.bounds != () {
        let b = map.bounds; let x = p % map.width; let y = p / map.width;
        return x >= b.x && x < b.x+b.width && y >= b.y && y < b.y+b.height;
    }
    true
}
fn validate_condition(c) {
    if c.kind == "has_knowledge" && (c.record.trim() == "" || c.record.len() > 80) { return "knowledge condition needs a record ID of 1..80 characters"; }
    if (c.kind == "at" || c.kind == "food_at" || c.kind == "shelter_at" || c.kind == "danger") && c.location != () &&
       !valid_location(c.map, c.location) { return "condition location outside known world bounds"; }
    if c.kind == "resource" && (c.value < 0 || c.value > 100) { return "resource threshold must be 0..100"; }
    if c.kind == "shelter_at" && (c.minimum < 1 || c.minimum > 12) { return "shelter minimum must be 1..12"; }
    if c.kind == "food_at" && (c.minimum < 1 || c.minimum > 100) { return "food minimum must be 1..100"; }
    ""
}

// Periods are game content, independent of how frequently the authority wakes.
fn system_periods_ms(c) { #{needs_ms:2500, hazard_ms:2500} }
fn action_interval_ms(skill) {
    switch skill { "move" => 250, "gather" | "eat" | "speak" | "give" | "deposit" | "observe" => 1000, "attack" => 750, _ => 2500 }
}
fn retry_delay_ms(c) { 250 }
fn paced(result, c, interval) {
    let base=if c.ready_at_ms > c.time_ms-c.delta_ms { c.ready_at_ms } else { c.time_ms-c.delta_ms };
    result.wake_at_ms=if base+interval < c.time_ms { c.time_ms } else { base+interval };
    result.cooldown_until_ms=result.wake_at_ms;
    result
}

// Research capabilities derive from personally assessed, physically paid work.
// These booleans are authority-derived evidence facts, not participant assertions.
fn research_authoring(c) { c.own_forecast_assessed || c.own_practice_assessed || c.own_prototype_assessed }
fn research_use(c) { c.held_interpreted && c.own_matching_practice_assessed }

// Scope and evidence facts are supplied by the authority, never the proposed law.
fn authorize_law_edit(c) { if c.scope == "universal" { c.own_matching_assessed_experiment } else { c.local_grant || c.own_matching_assessed_experiment } }
