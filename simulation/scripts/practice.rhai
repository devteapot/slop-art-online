fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target,record"});
    if error != "" { return error; }
    if c.action.duration != 1 || c.action.target == () || c.action.target == c.actor.id { return "practice needs another guide target and duration 1"; }
    if c.action.record == () || c.action.record.trim() == "" || c.action.record.len() > 80 { return "practice needs a personal record ID"; }
    ""
}
fn step(c) {
    if !c.lifecycle.enabled || !c.lifecycle.own.dependent { return law::failed("guided practice is for a dependent learner"); }
    if !c.lifecycle.guided || !c.lifecycle.record_ready { return law::failed("practice needs a living local prior caregiver and an interpreted personal report about this location"); }
    let costs=law::population_costs(#{});
    if c.lifecycle.site_food < 1 || c.actor.energy < costs.practice_energy { return law::failed("practice requires actual food at this site and enough energy to gather it"); }
    let elapsed=(if c.state == () {0} else {c.state.elapsed_ms})+c.delta_ms;
    if elapsed < costs.practice_ms {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+costs.practice_ms-elapsed;
        return result;
    }
    law::done([#{kind:"practice",guide:c.action.target,record:c.action.record,energy:costs.practice_energy}])
}
