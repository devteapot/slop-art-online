fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn step(c) {
    let interval=law::action_interval_ms("wait");
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms }) + c.delta_ms;
    let count=law::bounded(elapsed/interval,0,c.remaining);
    let remaining=c.remaining-count;
    let state=#{elapsed_ms:elapsed % interval};
    let result=law::outcome(if remaining > 0 { "running" } else { "success" }, "", remaining, state,
        if count > 0 { [] } else { [] },
        if count > 0 { #{remaining:remaining} } else { #{} });
    result.wake_at_ms=if remaining > 0 { c.time_ms+interval-state.elapsed_ms } else { c.time_ms };
    result
}
