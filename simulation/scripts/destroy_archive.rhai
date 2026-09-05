fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"archive"});
    if error != "" { return error; }
    if c.action.duration != 1 { return "knowledge action uses fixed elapsed duration; set duration to 1"; }
    if c.action.archive == () { return "destroy_archive requires archive ID"; }

    ""
}
fn step(c) {
    if c.knowledge.archive == () || c.knowledge.archive.destroyed { return law::failed("no intact archive at this cell"); }
    if c.actor.energy < 8 { return law::failed("insufficient energy for destroy_archive"); }
    let elapsed=(if c.state == () { 0 } else { c.state.elapsed_ms })+c.delta_ms;
    if elapsed < 5000 {
        let result=law::outcome("running","",1,#{elapsed_ms:elapsed},[],#{});
        result.wake_at_ms=c.time_ms+5000-elapsed;
        return result;
    }
    law::done([#{kind:"actor",fields:#{energy:c.actor.energy-8}},#{kind:"destroy_archive",archive:c.action.archive}])
}
