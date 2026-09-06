fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"infrastructure"});
    if error != "" {return error;}
    if c.action.infrastructure == () {return "infrastructure operation required";}
    if c.action.duration != 1 {return "infrastructure operations use duration 1";}
    ""
}
fn step(c) {
    if c.infrastructure_error != "" {return law::failed(c.infrastructure_error);}
    let result=law::done([#{kind:"infrastructure",operation:c.action.infrastructure}]);
    result.cooldown_until_ms=c.time_ms+1000;
    result
}
