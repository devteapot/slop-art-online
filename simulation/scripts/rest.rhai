fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn step(c) {
    let interval=law::action_interval_ms("rest");
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms }) + c.delta_ms;
    let count=law::bounded(elapsed/interval,0,c.remaining);
    let remaining=c.remaining-count;
    let state=#{elapsed_ms:elapsed % interval};
    let shelter=if c.site == () { 0 } else { c.site.shelter };
    let energy=law::bounded(c.actor.energy+(12+2*shelter)*count,0,100);
    let effects=if count > 0 { [#{kind:"actor",fields:#{energy:energy}}] } else { [] };
    let status=if remaining > 0 { "running" } else { "success" };
    let progress=if count > 0 { #{remaining:remaining} } else { #{} };
    let result=law::outcome(status,"",remaining,state,effects,progress);
    result.wake_at_ms=if remaining > 0 { c.time_ms+interval-state.elapsed_ms } else { c.time_ms };
    result
}
