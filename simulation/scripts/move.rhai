fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"destination"});
    if error != "" { return error; }
    if c.action.destination == () || c.action.destination < -10 || c.action.destination > 10 { return "invalid destination"; }
    ""
}
fn perform(c) {
    if c.actor.position == c.action.destination { return law::done([]); }
    let cost=law::cost("move");
    if c.actor.energy < cost { return law::failed("exhausted"); }
    let position=c.actor.position;
    if c.action.destination > position { position+=1; } else if c.action.destination < position { position-=1; }
    let effects=[#{kind:"actor",fields:#{position:position,energy:c.actor.energy-cost}},#{kind:"observe"}];
    if position != c.action.destination { return law::outcome("running","",c.remaining,c.state,effects,#{position:position}); }
    law::done(effects)
}

fn step(c) { law::paced(perform(c), c, law::action_interval_ms("move")) }
