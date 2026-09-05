fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn perform(c) {
    if c.site == () || c.site.shelter >= 12 || c.actor.energy < 8 { return law::failed("shelter complete, no site, or insufficient energy"); }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-8}},#{kind:"site_shelter",amount:1},#{kind:"observe"}])
}

fn step(c) { law::paced(perform(c), c, law::action_interval_ms("build")) }
