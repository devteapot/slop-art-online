fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn step(c) {
    if c.remaining > 1 { return law::outcome("running","",c.remaining-1,c.state,[],#{energy:c.actor.energy,remaining:c.remaining-1}); }
    law::done([])
}
