fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"archive,record"});
    if error != "" { return error; }
    if c.action.duration != 1 { return "knowledge action uses fixed elapsed duration; set duration to 1"; }
    if c.action.archive == () { return "consult requires archive ID"; }
    if c.action.record == () || c.action.record.trim() == "" || c.action.record.len() > 80 { return "knowledge action requires record ID of 1..80 characters"; }
    ""
}
fn step(c) {
    if c.knowledge.archive == () || c.knowledge.archive.destroyed || !c.knowledge.archive.contains_record { return law::failed("record unavailable in a local intact archive"); }
    if c.knowledge.record == () && c.knowledge.own_count >= c.knowledge.own_capacity { return law::failed("personal knowledge capacity reached"); }
    if c.actor.energy < 1 { return law::failed("insufficient energy for consult"); }
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms })+c.delta_ms;
    if elapsed < 1500 {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+1500-elapsed;
        return result;
    }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-1}},#{kind:"consult_knowledge",archive:c.action.archive,record:c.action.record}])
}
