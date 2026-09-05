fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"destination"});
    if error != "" { return error; }
    if c.action.destination == () || !law::valid_location(c.map, c.action.destination) { return "invalid destination"; }
    if c.map != () && c.map.blocked.contains(c.action.destination) { return "destination is blocked"; }
    ""
}
fn perform(c) {
    if c.actor.position == c.action.destination { return law::done([]); }
    let cost=law::cost("move");
    if c.actor.energy < cost { return law::failed("exhausted"); }
    let position=c.actor.position;
    if c.map != () {
        if c.navigation == () { return law::failed("no route to destination"); }
        position=c.navigation.next;
    } else if c.action.destination > position { position+=1; } else if c.action.destination < position { position-=1; }
    let effects=[#{kind:"actor",fields:#{position:position,energy:c.actor.energy-cost}},#{kind:"observe"}];
    if position != c.action.destination { return law::outcome("running","",c.remaining,c.state,effects,#{position:position,navigation:c.navigation}); }
    law::done(effects)
}

fn step(c) { law::paced(perform(c), c, law::action_interval_ms("move")) }
