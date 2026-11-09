//! Stable presentation codes (docs/COMBAT.md, "Presentation codes"). Public rows carry a
//! skill as a one-byte code (`fighter.act`, `combat_seen.skill`, `doing.code`) that clients
//! name through `skill_card` and `act_card`. A skill keeps its code across script installs;
//! a new skill takes the next code never used in its space, and a removed skill's code stays
//! reserved, so no row ever comes to name a different skill.

use crate::tables::*;
use living_rules::script::Scripts;
use spacetimedb::{ReducerContext, Table};
use std::collections::BTreeMap;

/// Combat skills (`<skill>_combat()`).
pub const COMBAT: &str = "combat";
/// Skills others see being done (`<skill>_shows()`).
pub const SHOWN: &str = "shown";

/// The codes given so far in `space`, by skill.
pub fn known(ctx: &ReducerContext, space: &str) -> BTreeMap<String, u8> {
    let prefix = format!("{space}:");
    ctx.db.skill_code().iter().filter_map(|c| Some((c.key.strip_prefix(&prefix)?.to_string(), c.code))).collect()
}

/// The codes clients were last shown in `space` (`skill_card`, `act_card`). A world that
/// predates this registry keeps them: they are taken over at its next install.
fn published(ctx: &ReducerContext, space: &str) -> BTreeMap<String, u8> {
    match space {
        COMBAT => ctx.db.skill_card().iter().filter(|c| c.code != 0).map(|c| (c.skill, c.code)).collect(),
        _ => ctx.db.act_card().iter().filter(|c| c.code != 0).map(|c| (c.skill, c.code)).collect(),
    }
}

/// Give every skill in `names` a code in `space`, keeping the ones already given; the codes
/// of all of `space`'s skills, old and new.
fn assign<'a>(ctx: &ReducerContext, space: &str, names: impl Iterator<Item = &'a str>) -> Result<BTreeMap<String, u8>, String> {
    let mut codes = known(ctx, space);
    if codes.is_empty() {
        for (name, code) in published(ctx, space) {
            ctx.db.skill_code().insert(SkillCode { key: format!("{space}:{name}"), code });
            codes.insert(name, code);
        }
    }
    let mut next = codes.values().copied().max().unwrap_or(0);
    for name in names {
        if codes.contains_key(name) {
            continue;
        }
        if next == u8::MAX {
            return Err(format!("no {space} code left for `{name}`: 255 have been given"));
        }
        next += 1;
        ctx.db.skill_code().insert(SkillCode { key: format!("{space}:{name}"), code: next });
        codes.insert(name.to_string(), next);
    }
    Ok(codes)
}

/// Register the codes of a script about to be installed and apply them to it.
pub fn install(ctx: &ReducerContext, sc: &mut Scripts) -> Result<(), String> {
    let combat = assign(ctx, COMBAT, sc.shapes().names())?;
    let shown = assign(ctx, SHOWN, sc.shows().names())?;
    sc.set_codes(&combat, &shown);
    Ok(())
}

/// Apply the codes already given to a compiled script (the installed one); before a world's
/// first install under this registry, the codes its cards carry.
pub fn apply(ctx: &ReducerContext, sc: &mut Scripts) {
    let get = |space| {
        let k = known(ctx, space);
        if k.is_empty() { published(ctx, space) } else { k }
    };
    sc.set_codes(&get(COMBAT), &get(SHOWN));
}
