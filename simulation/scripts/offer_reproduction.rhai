fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target"});
    if error != "" { return error; }
    if c.action.duration != 1 || c.action.target == () || c.action.target == c.actor.id { return "offer_reproduction needs another target and duration 1"; }
    ""
}
fn step(c) {
    if !c.lifecycle.enabled { return law::failed("population renewal is not configured here"); }
    if c.lifecycle.own.dependent || c.lifecycle.own.body != "biological" || c.lifecycle.target == () || c.lifecycle.target.dependent || c.lifecycle.target.body != "biological" { return law::failed("reproduction requires two living independent biological people at this cell"); }
    if !c.lifecycle.capacity { return law::failed("retained population capacity reached"); }
    let costs=law::population_costs(#{});
    // Repeating the same offer does not replace its source and disrupt a partner's work.
    if c.lifecycle.own_offer != () { return law::paced(law::done([]),c,1000); }
    law::paced(law::done([#{kind:"offer_reproduction",partner:c.action.target,
        expires_ms:c.time_ms+costs.offer_ms,food:costs.parent_food,energy:costs.parent_energy}]),c,1000)
}
