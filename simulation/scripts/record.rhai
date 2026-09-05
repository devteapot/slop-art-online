fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"archive,record"});
    if error != "" { return error; }
    if c.action.duration != 1 { return "knowledge action uses fixed elapsed duration; set duration to 1"; }
    if c.action.archive == () { return "record requires archive ID"; }
    if c.action.record == () || c.action.record.trim() == "" || c.action.record.len() > 80 { return "knowledge action requires record ID of 1..80 characters"; }
    ""
}
fn step(c) {
    if c.knowledge.record == () { return law::failed("you do not hold that knowledge record"); }
    if c.knowledge.archive == () || c.knowledge.archive.destroyed { return law::failed("no intact archive at this cell"); }
    if !c.knowledge.archive.contains_record && c.knowledge.archive.record_count >= c.knowledge.archive.capacity { return law::failed("archive capacity reached"); }
    if c.actor.energy < 4 { return law::failed("insufficient energy for record"); }
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms })+c.delta_ms;
    if elapsed < 2500 {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+2500-elapsed;
        return result;
    }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-4}},#{kind:"record_knowledge",archive:c.action.archive,record:c.action.record}])
}
