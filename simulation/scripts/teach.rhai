fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"target,record"});
    if error != "" { return error; }
    if c.action.duration != 1 { return "knowledge action uses fixed elapsed duration; set duration to 1"; }
    if c.action.target == () || c.action.target == c.actor.id { return "teach requires another target"; }
    if c.action.record == () || c.action.record.trim() == "" || c.action.record.len() > 80 { return "knowledge action requires record ID of 1..80 characters"; }
    ""
}
fn step(c) {
    if c.knowledge.record == () { return law::failed("you do not hold that knowledge record"); }
    if c.knowledge.target == () { return law::failed("recipient dead or not at this cell"); }
    if !c.knowledge.target.has_record && c.knowledge.target.knowledge_count >= c.knowledge.target.capacity { return law::failed("recipient knowledge capacity reached"); }
    if c.actor.energy < 2 { return law::failed("insufficient energy for teach"); }
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms })+c.delta_ms;
    if elapsed < 2000 {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+2000-elapsed;
        return result;
    }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-2}},#{kind:"teach",target:c.action.target,record:c.action.record}])
}
