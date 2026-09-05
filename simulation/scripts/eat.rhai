fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn step(c) {
    if c.actor.food <= 0 { return law::failed("no carried food"); }
    law::done([#{kind:"actor",fields:#{food:c.actor.food-1,hunger:law::bounded(c.actor.hunger-35,0,100)}}])
}
