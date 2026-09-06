fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"record"});
    if error != "" { return error; }
    if c.action.duration != 1 { return "knowledge action uses fixed elapsed duration; set duration to 1"; }
    if c.action.record == () || c.action.record.trim() == "" || c.action.record.len() > 80 { return "knowledge action requires record ID of 1..80 characters"; }
    ""
}
fn step(c) {
    if c.actor.health <= 0 { return law::failed("dead characters cannot reread knowledge"); }
    if c.knowledge.record == () { return law::failed("record is not personally held"); }
    if c.actor.energy < 1 { return law::failed("insufficient energy for reread_record"); }
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms })+c.delta_ms;
    if elapsed < 1500 {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+1500-elapsed;
        return result;
    }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-1}},#{kind:"read_record",record:c.action.record}])
}
