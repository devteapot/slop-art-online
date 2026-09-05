fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target"});
    if error != "" { return error; }
    if c.action.duration != 1 || c.action.target == () || c.action.target == c.actor.id { return "care needs another target and duration 1"; }
    ""
}
fn step(c) {
    if !c.lifecycle.enabled || c.lifecycle.own.dependent || c.lifecycle.target == () || !c.lifecycle.target.dependent { return law::failed("care requires an independent caregiver and a living dependent at this cell"); }
    let costs=law::population_costs(#{});
    if c.actor.food < 1 || c.actor.energy < costs.care_energy || c.lifecycle.target.hunger < costs.nutrition { return law::failed("care needs one carried meal, caregiver energy, and enough recipient hunger for that meal"); }
    let elapsed=(if c.state == () {0} else {c.state.elapsed_ms})+c.delta_ms;
    if elapsed < costs.care_ms {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+costs.care_ms-elapsed;
        return result;
    }
    law::done([#{kind:"care",target:c.action.target,energy:costs.care_energy,nutrition:costs.nutrition}])
}
