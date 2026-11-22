// The heed experiments' laws (docs/ATTENTION_BUDGET.md §3.2): the `watch` skill and the
// `keeping_watch` technique. Seed content on the attention-exp branch only: an overlay over the
// shipped script (living/scripts/skills.rhai), composed by `floors::compose` for a seed that
// names it (`laws_file`), so no shipped world changes. The capacity law itself
// (`heed_capacity(a)`) is the shipped script's; this adds what widens it.

// Keeping many people in view at once: a technique one can be taught or learn from writing.
fn know_how() {
    let k = base_know_how();
    k.push(#{ name: "keeping_watch", help: "keep many people in view at once: you keep track of more of them as individuals" });
    k
}

// Standing and looking about: its practice is what `heed_capacity(a)` reads as
// `a.actor.factor` (the skill `heed_knack()` names).
fn watch_spec() {
    #{ moment: true,
       about: "Stand and look about you for a while. Practice at keeping watch lets you keep track of more people at once.",
       takes: "4 seconds standing", gives: "practice at keeping watch" }
}
fn watch_check(a) { "" }
fn watch_duration(a) { 4000 }
fn watch_done(a) { [] }
