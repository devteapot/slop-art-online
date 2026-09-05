fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target"});
    if error != "" { return error; }
    if c.action.duration != 1 || c.action.target == () || c.action.target == c.actor.id { return "reproduce needs another target and duration 1"; }
    ""
}
fn step(c) {
    if !c.lifecycle.enabled || !c.lifecycle.capacity { return law::failed("population renewal unavailable or capacity reached"); }
    if c.lifecycle.target == () || c.lifecycle.own.dependent || c.lifecycle.target.dependent || c.lifecycle.own.body != "biological" || c.lifecycle.target.body != "biological" { return law::failed("both biological parents must remain living, independent and at this cell"); }
    let own=c.lifecycle.own_offer; let partner=c.lifecycle.partner_offer;
    if own == () || partner == () { return law::failed("both people must explicitly offer reproduction to each other"); }
    if c.state != () && (c.state.own_offer != own.source || c.state.partner_offer != partner.source) { return law::failed("the consent that began this attempt was withdrawn, expired or replaced"); }
    if c.actor.food < own.food_commitment || c.actor.energy < own.energy_commitment || c.lifecycle.target.food < partner.food_commitment || c.lifecycle.target.energy < partner.energy_commitment { return law::failed("both people must meet their quoted food and energy commitments"); }
    let elapsed=(if c.state == () {0} else {c.state.elapsed_ms})+c.delta_ms;
    let duration=law::population_costs(#{}).reproduction_ms;
    if elapsed < duration {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed,own_offer:own.source,partner_offer:partner.source},[],#{});
        result.wake_at_ms=c.time_ms+duration-elapsed;
        return result;
    }
    law::done([#{kind:"reproduce",partner:c.action.target,own_offer:own.source,partner_offer:partner.source}])
}
