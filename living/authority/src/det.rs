//! Deterministic stepping, a diagnostic (the `det_clock` law, off in play; docs/COMBAT_PHASE.md,
//! "Step 3 results"). With it on, a tick's clock is the last tick's plus 1/60 s, its random draws
//! come from a generator seeded from the tick number ([`crate::seed::Creating`]), and housekeeping
//! runs inside every 60th tick instead of on its own wall-clock schedule. Two copies of one world
//! (the same server volume copied while paused) then step alike on one build, and a difference
//! between two builds shows as a difference in a tick's table hashes, which each tick logs
//! (`det tick …`). Nothing here runs with the law off.
//!
//! **Ids.** SpacetimeDB 2.14.1 skips an auto-increment sequence ahead to its next block of 4,096
//! at random, about once in 4,096 values (`should_simulate_sequence_reallocation` in its
//! datastore, seeded from the operating system each time a database is loaded), so the same rows
//! get other ids on two servers. The hashes therefore name each auto-increment row by its rank
//! among its table's rows (the order ids are given in, which a skip keeps), and the references to
//! such ids that the battle writes are renamed the same way: far handles in text and in
//! experiences, structures (remains) in inventories, rot and familiarity, lines heard, missiles'
//! uses, and typed ids in deliberation scenes. One rule depends on an id's value: an experience's insert checks its observer's window
//! when `id % 32 == 0` (`perceive::percept`); under the law it checks on every 32nd insert instead
//! ([`window_due`]), the same cadence without the server's skips.

use crate::attention::{applied_gaze, attention};
use crate::floor::genesis;
use crate::records::{record, record_clock, record_party};
use crate::tables::*;
use living_rules::script::FAR_HANDLE_BASE;
use serde_json::Value;
use spacetimedb::{ReducerContext, Table};
use std::collections::HashMap;

/// The seed of the tick draws (any constant: both copies use the same).
pub const SEED: u64 = 0xDE7_C10C_u64;

/// The time of tick `t + 1`, `t` being the clock's last tick: the last tick's time plus 1/60 s,
/// in whole milliseconds by the tick count (16 or 17 ms a tick, 1,000 ms every 60).
pub fn next_ms(last_ms: u64, t: u64) -> u64 {
    last_ms + ((t + 1) * 1000 / 60 - t * 1000 / 60)
}

thread_local! {
    /// Experiences inserted under the law since this module instance began (`window_due`).
    static INSERTS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

/// Whether an experience's insert checks its observer's window: `id % 32 == 0` in play; under the
/// `det_clock` law every 32nd insert (both copies start from a fresh module instance).
pub fn window_due(ctx: &ReducerContext, id: u64) -> bool {
    if !crate::common::laws(ctx).det_clock {
        return id % 32 == 0;
    }
    INSERTS.with(|n| {
        let k = n.get() + 1;
        n.set(k);
        k % 32 == 0
    })
}

/// FNV-1a over bytes, with a final mix (so the sum below of rows that differ in one byte differs well).
fn row_hash(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    h ^= h >> 33;
    h = h.wrapping_mul(0xff51_afd7_ed55_8ccd);
    h ^= h >> 33;
    h
}

/// The sorted ids of each auto-increment table, for ranks.
struct Ranks(HashMap<&'static str, Vec<u64>>);

impl Ranks {
    /// An id's rank among its table's ids; one no longer in the table, its place among them
    /// marked (bit 40) so it never equals a present row's rank.
    fn of(&self, table: &str, id: u64) -> u64 {
        let v = &self.0[table];
        match v.binary_search(&id) {
            Ok(i) => i as u64,
            Err(i) => (1 << 40) | i as u64,
        }
    }

    /// A far handle's number (`FAR_HANDLE_BASE + id`) by its rank.
    fn far(&self, n: u32) -> u32 {
        if n >= FAR_HANDLE_BASE {
            FAR_HANDLE_BASE.saturating_add((self.of("far_handle", (n - FAR_HANDLE_BASE) as u64) & 0x0fff_ffff) as u32)
        } else {
            n
        }
    }

    /// Far handles written into text ("(#1000004143)": `#` and ten digits from `FAR_HANDLE_BASE`)
    /// by rank, in place (the same length, so the row's encoding keeps its shape).
    fn text(&self, bytes: &mut [u8]) {
        let mut i = 0;
        while i + 11 <= bytes.len() {
            if bytes[i] == b'#' && bytes[i + 1..i + 11].iter().all(u8::is_ascii_digit) && bytes.get(i + 11).map_or(true, |b| !b.is_ascii_digit()) {
                let n: u64 = std::str::from_utf8(&bytes[i + 1..i + 11]).unwrap().parse().unwrap();
                if n >= FAR_HANDLE_BASE as u64 && n < u32::MAX as u64 {
                    let r = self.far(n as u32);
                    bytes[i + 1..i + 11].copy_from_slice(format!("{r:010}").as_bytes());
                }
                i += 11;
            } else {
                i += 1;
            }
        }
    }

    /// Deliberation's JSON carries ids in several namespaces. Rank them where the
    /// scene builder provides the type, since unrelated tables may allocate the same number.
    fn scene(&self, source: &str) -> Option<String> {
        let mut scene: Value = serde_json::from_str(source).ok()?;
        let character = |id| self.of("character", id);
        if let Some(you) = scene.get_mut("you") {
            rank_field(you, "id", character);
        }
        for key in ["creatures", living_rules::species::SMELLED] {
            if let Some(rows) = scene.get_mut(key).and_then(Value::as_array_mut) {
                for row in rows {
                    rank_field(row, "id", |id| {
                        if (FAR_HANDLE_BASE as u64..=u32::MAX as u64).contains(&id) {
                            self.far(id as u32) as u64
                        } else {
                            character(id)
                        }
                    });
                    if let Some(visibly) = row.get_mut("visibly") {
                        rank_field(visibly, "at", character);
                    }
                }
            }
        }
        for (key, table) in [("structures", "structure"), ("resources", "resource_node")] {
            if let Some(rows) = scene.get_mut(key).and_then(Value::as_array_mut) {
                for row in rows {
                    let row = if table == "resource_node" {
                        let Some(nearest) = row.get_mut("nearest") else { continue };
                        nearest
                    } else {
                        row
                    };
                    rank_field(row, "id", |id| self.of(table, id));
                }
            }
        }
        for (key, party) in [("asked of you", "from"), ("you are waiting on", "to")] {
            if let Some(rows) = scene.get_mut("you").and_then(|you| you.get_mut(key)).and_then(Value::as_array_mut) {
                for row in rows {
                    rank_field(row, party, character);
                    rank_field(row, "offer", |id| self.of("trade_offer", id));
                    rank_field(row, "bond", |id| self.of("bond_offer", id));
                }
            }
        }
        if let Some(words) = scene.get_mut(living_rules::script::speech::EARSHOT) {
            if let Some(source) = words.as_str() {
                *words = replace_ids(source, "(#", &[")"], |id| {
                    if (FAR_HANDLE_BASE as u64..=u32::MAX as u64).contains(&id) {
                        Some(format!("far_handle:{}", self.of("far_handle", id - FAR_HANDLE_BASE as u64)))
                    } else {
                        Some(format!("character:{}", character(id)))
                    }
                }).into();
            }
        }
        if let Some(acts) = scene.pointer_mut("/you/decided, not yet done").and_then(Value::as_array_mut) {
            for act in acts {
                if let Some(source) = act.as_str() {
                    *act = replace_ids(source, " → #", &[""], |id| {
                        let (table, rank) = self.target_rank(id)?;
                        Some(format!("{table}:{rank}"))
                    }).into();
                }
            }
        }
        Some(scene.to_string())
    }

    // Queued target descriptions erase the type. Follow brain::resolve's namespace
    // priority for extant ids and leave unresolvable numbers alone.
    fn target_rank(&self, id: u64) -> Option<(&'static str, u64)> {
        if (FAR_HANDLE_BASE as u64..=u32::MAX as u64).contains(&id) {
            return Some(("far_handle", self.of("far_handle", id - FAR_HANDLE_BASE as u64)));
        }
        ["character", "structure", "resource_node"].into_iter().find_map(|table| {
            self.0[table].binary_search(&id).ok().map(|rank| (table, rank as u64))
        })
    }

    fn reason(&self, source: &str) -> String {
        let character = |id| Some(self.of("character", id).to_string());
        let target = |id| self.target_rank(id).map(|(table, rank)| format!("{table}:{rank}"));
        source.split('\n').map(|line| {
            // These are authority-generated sentences. Leave other prose and its numbers alone.
            let line = replace_ids(line, "(offer ", &["), or let it pass."], |id| {
                Some(self.of("trade_offer", id).to_string())
            });
            let line = replace_ids(&line, "(bond ", &["); choose conceive"], |id| {
                Some(self.of("bond_offer", id).to_string())
            });
            let line = replace_ids(&line, "(#", &[") asks to start a family with you;", ") asks to start a family with you (bond "], character);
            if line.starts_with("You long for a child with ") || line.starts_with("You long for another child with ") {
                replace_ids(&line, "(#", &[")."], character)
            } else if line.starts_with("What you had decided did not work out: ") {
                let line = replace_ids(&line, " → #", &[":"], target);
                let line = replace_ids(&line, "no #", &[" in sight"], target);
                replace_ids(&line, "#", &[" is dead: their remains lie in sight"], character)
            } else {
                line
            }
        }).collect::<Vec<_>>().join("\n")
    }

    /// A structure's owner key (`STRUCTURE_BIT | id`) or familiarity key (`FAM_STRUCTURE | id`)
    /// by the structure's rank.
    fn structure_key(&self, key: u64, bit: u64) -> u64 {
        if key & (7 << 40) == bit {
            bit | (self.of("structure", key & ((1 << 40) - 1)) & ((1 << 40) - 1))
        } else {
            key
        }
    }
}

fn rank_field(row: &mut Value, key: &str, rank: impl Fn(u64) -> u64) {
    if let Some(field) = row.get_mut(key) {
        if let Some(id) = field.as_u64() {
            *field = rank(id).into();
        }
    }
}

fn replace_ids(source: &str, prefix: &str, suffixes: &[&str], rank: impl Fn(u64) -> Option<String>) -> String {
    let mut out = String::with_capacity(source.len());
    let mut rest = source;
    while let Some((before, after)) = rest.split_once(prefix) {
        out.push_str(before);
        out.push_str(prefix);
        let digits = after.bytes().take_while(u8::is_ascii_digit).count();
        let (number, tail) = after.split_at(digits);
        let matches = suffixes.iter().any(|suffix| if suffix.is_empty() { tail.is_empty() } else { tail.starts_with(suffix) });
        if let Some(replacement) = matches.then(|| number.parse().ok().and_then(&rank)).flatten() {
            out.push_str(&replacement);
        } else {
            out.push_str(number);
        }
        rest = tail;
    }
    out.push_str(rest);
    out
}

/// A table's rows as a multiset: the wrapping sum of the rows' hashes and the row count. The
/// order rows are stored in does not count (the same rows in another order hash the same).
fn table_hash<T: spacetimedb::Serialize>(ranks: &Ranks, rows: impl Iterator<Item = T>) -> (u64, u32) {
    let mut sum = 0u64;
    let mut n = 0u32;
    for r in rows {
        let mut bytes = spacetimedb::spacetimedb_lib::bsatn::to_vec(&r).expect("a row serializes");
        if bytes.contains(&b'#') {
            ranks.text(&mut bytes);
        }
        sum = sum.wrapping_add(row_hash(&bytes));
        n += 1;
    }
    (sum, n)
}

macro_rules! sorted_ids {
    ($ctx:expr, $m:expr; $($t:ident),* $(,)?) => {
        $( $m.insert(stringify!($t), { let mut v: Vec<u64> = $ctx.db.$t().iter().map(|r| r.id as u64).collect(); v.sort_unstable(); v }); )*
    };
}

macro_rules! hash_plain {
    ($ctx:expr, $ranks:expr, $out:expr; $($t:ident),* $(,)?) => {
        $( $out.push((stringify!($t), table_hash($ranks, $ctx.db.$t().iter()))); )*
    };
}

macro_rules! hash_ranked {
    ($ctx:expr, $ranks:expr, $out:expr; $($t:ident),* $(,)?) => {
        $( $out.push((stringify!($t), table_hash($ranks, $ctx.db.$t().iter().map(|mut r| { r.id = $ranks.of(stringify!($t), r.id as u64) as _; r })))); )*
    };
}

/// Log this tick's hash of every table that the world's state lives in. Left out: the clock and
/// stats rows (they hold wall-clock gaps), the scheduled timers, the installed script and the
/// static land (they never change in a run), connections and the event tables (never stored).
pub fn trace(ctx: &ReducerContext, tick: u64) {
    let mut m = HashMap::new();
    sorted_ids!(ctx, m;
        acquaintance, act_queue, artifact, audience, belief, bond_offer, character, chronicle, combat_seen,
        community, cue, expecting, experience, familiar, far_handle, fight_seen, ground_edit, guest,
        heard_asleep, inventory, join_request, judged, judgment, know_how, known_ground, law_change,
        look_line, membership, missile, perceived, place, practice, projected, record_party, record,
        relation, remembered, resource_node, reveal, routine, seen_stock, seen_structures, sex_seen,
        skill_use, structure, thought, trade_offer,
    );
    let ranks = Ranks(m);
    let r = &ranks;
    let mut out: Vec<(&str, (u64, u32))> = Vec::with_capacity(128);
    hash_plain!(ctx, r, out;
        world, look, sex, gate, routine_stat, background, world_law, law_override, law_revision,
        cover_law, cover_ground, land_plan, settlement, lot, body, steer, walk_route, vitals, activity,
        brain, mind_state, wake, infant_cry, speech_card, slumber,
    );
    out.push(("deliberation", table_hash(r, ctx.db.deliberation().iter().map(|mut d| {
        d.actor = r.of("character", d.actor as u64) as u32;
        d.reason = r.reason(&d.reason);
        if let Some(scene) = r.scene(&d.scene) {
            d.scene = scene;
        }
        d
    }))));
    hash_plain!(ctx, r, out;
        persona, standing,
        rearing, genome, pasture, skill_card, fighter, readiness, character_senses, character_earshot,
        weather, skill_code, act_card, doing, heard, knowledge_epoch, hear_salt,
        fighter_seen, player, motion_seen, doing_seen, motion_near, fighter_near, doing_near,
        seen_body_copy, copy_state, rhythm, attention, applied_gaze, record_clock,
        genesis, last_look, fast_ask, mind_cursor,
    );
    hash_ranked!(ctx, r, out;
        acquaintance, act_queue, artifact, audience, belief, bond_offer, character, chronicle, combat_seen,
        community, cue, expecting, ground_edit, guest, heard_asleep, join_request, judged, judgment,
        know_how, known_ground, law_change, look_line, membership, place, practice,
        record_party, record, relation, remembered, reveal, routine, seen_stock, seen_structures,
        sex_seen, skill_use, thought, trade_offer, far_handle, fight_seen,
    );
    out.push(("experience", table_hash(r, ctx.db.experience().iter().map(|mut e| {
        e.id = r.of("experience", e.id);
        e.subject = r.far(e.subject);
        e.object = r.far(e.object);
        e
    }))));
    out.push(("structure", table_hash(r, ctx.db.structure().iter().map(|mut s| {
        s.id = r.of("structure", s.id);
        s
    }))));
    out.push(("inventory", table_hash(r, ctx.db.inventory().iter().map(|mut i| {
        i.id = r.of("inventory", i.id);
        i.owner = r.structure_key(i.owner, STRUCTURE_BIT);
        i
    }))));
    out.push(("rot", table_hash(r, ctx.db.rot().iter().map(|mut x| {
        x.structure = r.of("structure", x.structure);
        x
    }))));
    out.push(("familiar", table_hash(r, ctx.db.familiar().iter().map(|mut f| {
        f.id = r.of("familiar", f.id);
        f.thing = r.structure_key(f.thing, FAM_STRUCTURE);
        f
    }))));
    out.push(("line_heard", table_hash(r, ctx.db.line_heard().iter().map(|mut l| {
        l.line = r.of("experience", l.line);
        l
    }))));
    out.push(("missile", table_hash(r, ctx.db.missile().iter().map(|mut x| {
        x.id = r.of("missile", x.id);
        x.use_id = r.of("skill_use", x.use_id);
        x
    }))));
    out.push(("resource_node", table_hash(r, ctx.db.resource_node().iter().map(|mut n| {
        n.id = r.of("resource_node", n.id);
        if n.pool != 0 {
            n.pool = r.of("resource_node", n.pool);
        }
        n
    }))));
    // Players' rows (det_compare with players). A sweep inserts a viewer's `perceived` and
    // `projected` rows in a hash set's order, which a module instance's history decides, so two
    // copies give the same rows other ids, and other ranks. These tables, and the rows that name
    // their ids (the mirror of projections by `projected` id; act outcomes and released lines by
    // `experience` id, whose deletes follow the same lines), are hashed by content with the id
    // columns left out; their row counts stay in the hash. (The gaps between their ids cannot be
    // compared: 2.14.1's random sequence skips put them anywhere, which ranks absorb only when
    // the order of inserts is the same.)
    out.push(("perceived", table_hash(r, ctx.db.perceived().iter().map(|mut x| {
        x.id = 0;
        x
    }))));
    out.push(("projected", table_hash(r, ctx.db.projected().iter().map(|mut x| {
        x.id = 0;
        x
    }))));
    out.push(("act_outcome", table_hash(r, ctx.db.act_outcome().iter().map(|mut x| {
        x.id = 0;
        x
    }))));
    out.push(("line_seen", table_hash(r, ctx.db.line_seen().iter().map(|mut l| {
        l.id = 0;
        l.line.id = 0;
        l.line.subject = r.far(l.line.subject);
        l.line.object = r.far(l.line.object);
        l
    }))));
    out.push(("seen_character_copy", table_hash(r, ctx.db.seen_character_copy().iter().map(|mut c| {
        c.id = 0;
        c
    }))));
    let all = out.iter().fold(0u64, |a, (_, (h, _))| a.rotate_left(5) ^ h);
    let tables: Vec<String> = out.iter().map(|(t, (h, n))| format!("{t}={h:016x}/{n}")).collect();
    log::info!("det tick {tick} all={all:016x} {}", tables.join(" "));
}

thread_local! {
    static PERTURBED: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// A control for the comparison, compiled in only when `LIVING_DET_PERTURB` is set at build time
/// (a number): that many extra hashers are made at the first tick under the law, which moves the
/// keys of every hash map made after them (std's `RandomState` counts up from per-instance keys).
/// A build so perturbed must still compare identical with its unperturbed self: nothing the world
/// does may depend on a hash map's order.
pub fn perturb() {
    if let Some(n) = option_env!("LIVING_DET_PERTURB").and_then(|v| v.parse::<u32>().ok()) {
        if !PERTURBED.with(|p| p.replace(true)) {
            for _ in 0..n {
                std::hint::black_box(std::collections::hash_map::RandomState::new());
            }
            log::info!("det: {n} hashers made at the first tick (LIVING_DET_PERTURB)");
        }
    }
}

/// Pause the world at the end of tick `tick` when the `det_stop` law names it (or an earlier one).
pub fn stop_at(ctx: &ReducerContext, tick: u64, stop: f32) {
    if stop > 0.0 && tick >= stop as u64 {
        if let Some(mut w) = ctx.db.world().id().find(0) {
            w.paused = true;
            ctx.db.world().id().update(w);
            crate::common::invalidate_world();
            log::info!("det tick {tick}: paused (det_stop {stop})");
        }
    }
}
