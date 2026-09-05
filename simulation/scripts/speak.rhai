fn validate(c) {
    let error=law::validate_common(#{action:c.action,allowed:"text"});
    if error != "" { return error; }
    if c.action.text == () || c.action.text.trim() == "" || c.action.text.len() > 1000 { return "speech must contain 1..1000 characters"; }
    ""
}
fn step(c) {
    if c.spoke { return law::outcome("running","",c.remaining,c.state,[],#{}); }
    law::done([#{kind:"speech",text:c.action.text}])
}
