fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn perform(c) { law::done([#{kind:"observe"}]) }

fn step(c) { law::paced(perform(c), c, law::action_interval_ms("observe")) }
