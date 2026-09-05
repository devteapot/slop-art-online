fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target"});
    if error != "" { return error; }
    if c.action.target == () || c.action.target == c.actor.id { return "give requires another target"; }
    ""
}
fn perform(c) {
    if c.actor.food < 1 { return law::failed("no carried food to give"); }
    if c.target == () || c.target.health <= 0 || c.target.position != c.actor.position { return law::failed("recipient dead or not at this cell"); }
    law::done([#{kind:"transfer_food",target:c.target.id,amount:1}])
}

fn step(c) { law::paced(perform(c), c, law::action_interval_ms("give")) }
