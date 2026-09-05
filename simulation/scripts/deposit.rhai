fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn perform(c) {
    if c.site == () || c.actor.food < 1 { return law::failed("deposit requires a site and carried food"); }
    law::done([#{kind:"transfer_food",target:(),amount:1},#{kind:"observe"}])
}

fn step(c) { law::paced(perform(c), c, law::action_interval_ms("deposit")) }
