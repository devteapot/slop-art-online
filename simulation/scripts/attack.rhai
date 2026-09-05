fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target"});
    if error != "" { return error; }
    if c.action.target == () || c.action.target == c.actor.id { return "attack requires another target"; }
    ""
}
fn step(c) {
    let cost=law::cost("attack");
    if c.target == () || c.actor.energy < cost { return law::failed("target unavailable or insufficient energy"); }
    if c.target.health <= 0 || c.target.position != c.actor.position { return law::failed("target dead or out of range"); }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-cost}},#{kind:"damage",target:c.target.id,amount:20}])
}
