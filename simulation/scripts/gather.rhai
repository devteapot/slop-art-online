fn validate(c) { law::validate_common(#{action:c.action,allowed:""}) }
fn step(c) {
    let cost=law::cost("gather");
    if c.site == () || c.site.food <= 0 || c.actor.energy < cost { return law::failed("no food here or insufficient energy"); }
    law::done([#{kind:"site_food",value:c.site.food-1},
        #{kind:"actor",fields:#{food:c.actor.food+1,energy:c.actor.energy-cost}},#{kind:"observe"}])
}
