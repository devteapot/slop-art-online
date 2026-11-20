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
//! uses. One rule depends on an id's value: an experience's insert checks its observer's window
//! when `id % 32 == 0` (`perceive::percept`); under the law it checks on every 32nd insert instead
//! ([`window_due`]), the same cadence without the server's skips.

use crate::attention::{applied_gaze, attention};
use crate::floor::genesis;
use crate::records::{record, record_clock, record_party};
use crate::tables::*;
use living_rules::script::FAR_HANDLE_BASE;
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
        brain, mind_state, wake, infant_cry, speech_card, slumber, deliberation, persona, standing,
        rearing, genome, pasture, skill_card, fighter, readiness, character_senses, character_earshot,
        act_outcome, weather, skill_code, act_card, doing, heard, knowledge_epoch, hear_salt,
        fighter_seen, player, motion_seen, line_seen, doing_seen, motion_near, fighter_near, doing_near,
        seen_body_copy, copy_state, seen_character_copy, rhythm, attention, applied_gaze, record_clock,
        genesis, last_look, fast_ask, mind_cursor,
    );
    hash_ranked!(ctx, r, out;
        acquaintance, act_queue, artifact, audience, belief, bond_offer, character, chronicle, combat_seen,
        community, cue, expecting, ground_edit, guest, heard_asleep, join_request, judged, judgment,
        know_how, known_ground, law_change, look_line, membership, perceived, place, practice, projected,
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
    out.push(("resource_node", table_hash(r, ctx.db.resource_node().iter())));
    let all = out.iter().fold(0u64, |a, (_, (h, _))| a.rotate_left(5) ^ h);
    let tables: Vec<String> = out.iter().map(|(t, (h, n))| format!("{t}={h:016x}/{n}")).collect();
    log::info!("det tick {tick} all={all:016x} {}", tables.join(" "));
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
