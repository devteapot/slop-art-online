fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:""});
    if error != "" { return error; }
    if c.action.duration != 1 { return "fabricate uses fixed work duration; set duration 1"; }
    ""
}
fn step(c) {
    if !c.lifecycle.enabled || !c.lifecycle.capacity { return law::failed("population renewal unavailable or capacity reached"); }
    if c.lifecycle.own.dependent || !c.lifecycle.workshop { return law::failed("fabrication requires an independent person at a workshop"); }
    let costs=law::population_costs(#{});
    if c.actor.food < costs.fabrication_food || c.actor.energy < costs.fabrication_energy { return law::failed("insufficient nutrients or energy for fabrication"); }
    let elapsed=(if c.state == () {0} else {c.state.elapsed_ms})+c.delta_ms;
    if elapsed < costs.fabrication_ms {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+costs.fabrication_ms-elapsed;
        return result;
    }
    law::done([#{kind:"fabricate",food:costs.fabrication_food,energy:costs.fabrication_energy}])
}
