fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn step(c) {
    let energy=law::bounded(c.actor.energy+12,0,100);
    let effects=[#{kind:"actor",fields:#{energy:energy}}];
    if c.remaining > 1 { return law::outcome("running","",c.remaining-1,c.state,effects,#{energy:energy,remaining:c.remaining-1}); }
    law::done(effects)
}
