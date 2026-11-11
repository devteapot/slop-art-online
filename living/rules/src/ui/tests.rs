use super::*;

/// The shipped bar's declarations (ui-1 step 4, INTERFACE.md step 2): they parse with no
/// errors, the script validates, and they place Q block, E heal and R fire bolt, LMB strike, RMB
/// the bow shot, Space the jump and the double tap the dodge.
#[cfg(feature = "scripting")]
#[test]
fn the_shipped_bar_is_declared_and_placed() {
    let sc = crate::script::Scripts::with_day(include_str!("../../../scripts/skills.rhai"), crate::DEFAULT_DAY_MS).expect("the shipped script compiles");
    assert!(sc.ui_errors().is_empty(), "{:?}", sc.ui_errors());
    sc.validate().expect("the shipped script validates");
    let bar = bar_places(&sc);
    assert_eq!(bar.primary.as_deref(), Some("strike"));
    assert_eq!(bar.secondary.as_deref(), Some("bowshot"));
    assert_eq!(bar.skill[..3].iter().map(|s| s.as_deref()).collect::<Vec<_>>(), vec![Some("block"), Some("heal"), Some("firebolt")]);
    assert_eq!(bar.jump.as_deref(), Some("jump"));
    assert_eq!(bar.dodge.as_deref(), Some("dodge"));
    assert!(bar.extra.is_empty(), "{:?}", bar.extra);
    for n in ["strike", "bowshot", "block", "heal", "firebolt", "dodge", "jump"] {
        let u = sc.ui(n).expect("a bar skill has a UiSpec");
        assert!(u.declared, "{n} is declared");
        assert!(u.look.icon.is_some() && !u.look.clips.is_empty(), "{n}: {:?}", u.look);
    }
    assert_eq!(sc.ui("strike").unwrap().look.clips, vec!["slash", "overhead", "thrust"]);
    assert_eq!(sc.ui("firebolt").unwrap().label, "Fire bolt");
}
