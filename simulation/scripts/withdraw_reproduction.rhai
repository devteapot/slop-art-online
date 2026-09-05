fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:""});
    if error != "" { return error; }
    if c.action.duration != 1 { return "withdraw_reproduction uses duration 1"; }
    ""
}
fn step(c) {
    if !c.lifecycle.enabled { return law::failed("population renewal is not configured here"); }
    law::paced(law::done([#{kind:"withdraw_reproduction"}]),c,1000)
}
