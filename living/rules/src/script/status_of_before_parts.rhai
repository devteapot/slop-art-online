fn status_of(a) {
    let out = [];
    if a.hunger != () { out.push(hunger_status(a.hunger)); }
    if a.energy != () { out.push(energy_status(a.energy)); }
    let f = a.share.health;
    if f != () { out.push(health_status(f)); }
    let falling = if a.hp_rate == () { 0.0 } else { a.hp_rate };
    // Losing health in the night air without starving: the cold (an alarm the mind acts on).
    if a.night && a.kind == "person" && falling < 0.0 && a.hunger != () && a.hunger < 100.0 {
        out.push(#{ name: "freezing", tone: "bad", text: "Freezing", alarm: "You are freezing in the night air; you need a fire or shelter.", salience: 0.6, think: "always" });
    }
    if a.hurt_ago_s != () && a.hurt_ago_s >= 0.0 && a.hurt_ago_s < 15.0 { out.push(#{ name: "in_combat", tone: "bad", text: "In combat" }); }
    // Breath: short of it after a run or in a fight (the refusal's words); slowed, and why.
    if a.stamina != () && a.stamina < 20.0 { out.push(#{ name: "out_of_breath", tone: "warn", text: "Out of breath", meter: "stamina", felt: "out of breath" }); }
    if a.energy != () {
        let slow = slow_words(a.kind, a.energy);
        if slow != "" { out.push(#{ name: "slowed", tone: "warn", text: "Walking slower", meter: "energy", felt: "walking slower" }); }
    }
    if falling < -0.01 { out.push(#{ name: "wasting", tone: "bad", text: "Wasting", felt: "you are growing weaker" }); }
    else if falling > 0.01 && f != () && f < 0.99 { out.push(#{ name: "recovering", tone: "good", text: "Recovering", felt: "your wounds are mending" }); }
    out
}
