//! A player's throng in `seen_throng` (docs/ATTENTION_BUDGET.md, "`seen_throng`"; the
//! `heed_players` law): whom it sees but does not keep track of, counted in 6 m cells and never
//! named. Written by the player's sweep from `heed::split`'s throng, on change only.
//!
//! **When a viewer's cells are worked out.** At its sweep, when its heed pass ran (at most once a
//! second) or the throng's members changed (one came in or left, or one became an individual): a
//! member that leaves the individuals is counted at the same sweep that drops its `perceived` row.
//! Between, nobody's moving rewrites anything.
//!
//! **Change only.** The viewer's rows are read by its `viewer` index and compared field by field:
//! a cell whose quantized fields did not change writes nothing; a changed one is updated in place
//! (its `id` kept); a new one is inserted; one no longer there is deleted.
//!
//! **Module memory** ([`LAST`]: each viewer's last throng and when its cells were worked out) is a
//! hint only: a rolled-back step may leave it ahead of the table, and the next pass (within a
//! second) writes the cells again from the rows. [`ANY`] says whether rows may exist, so the
//! law's kill switch costs nothing while there are none; a fresh instance asks the table once.

use crate::common::{self, NearCreature};
use crate::tables::*;
use living_rules::look::{cloth_index, CLOTH, NO_CLOTH};
use spacetimedb::{Identity, ReducerContext, Table};
use std::cell::{Cell, RefCell};
use std::collections::BTreeMap;

/// A cell's side (metres; the owner's decision).
pub const CELL_M: f32 = 6.0;
/// At most this many rows a viewer: past it, the farthest cells merge 2 x 2.
pub const MAX_ROWS: usize = 48;
/// `kinds` bits.
pub const PEOPLE: u8 = 1;
pub const WOLVES: u8 = 2;
pub const DEER: u8 = 4;
pub const OTHERS: u8 = 8;
/// `heading` when most stand or their ways cancel.
pub const STILL: u8 = 255;
/// A cell's mean speed below this (m/s) has no heading.
const HEADING_MIN_MPS: f32 = 0.3;

thread_local! {
    /// Per viewer (its character): the throng's members at its last cells (sorted ids).
    /// (BTree maps here and below: a std map would shift the hash keys of every later one,
    /// docs/GATE216_GROWTH.md.)
    static LAST: RefCell<BTreeMap<u32, Vec<u32>>> = const { RefCell::new(BTreeMap::new()) };
    /// Whether `seen_throng` may hold rows (`None`: not known in this instance).
    static ANY: Cell<Option<bool>> = const { Cell::new(None) };
}

/// About how many: exact to 5, then to the nearest 5.
pub fn about(n: usize) -> u16 {
    let n = if n <= 5 { n } else { (n + 2) / 5 * 5 };
    n.min(u16::MAX as usize) as u16
}

/// The 6 m cell a point falls in (map metres).
pub fn cell_of(p: (f32, f32)) -> (u32, u32) {
    ((p.0 / CELL_M).floor().max(0.0) as u32, (p.1 / CELL_M).floor().max(0.0) as u32)
}

fn key(cx: u32, cy: u32) -> u32 {
    (cx.min(0xFFFF) << 16) | cy.min(0xFFFF)
}

/// The square a row covers, in metres: its top-left corner and its side.
pub fn square(cell: u32, size: u8) -> ((f32, f32), f32) {
    (((cell >> 16) as f32 * CELL_M, (cell & 0xFFFF) as f32 * CELL_M), size.max(1) as f32 * CELL_M)
}

/// One row's fields (without its id and viewer).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Cell6 {
    pub cell: u32,
    pub size: u8,
    pub count: u16,
    pub spread: u8,
    pub heading: u8,
    pub moving: u16,
    pub fighting: u16,
    pub kinds: u8,
    /// The three colours most worn ([`living_rules::look::CLOTH`] indices, most first, ties by
    /// index) with their counts quantized as `count` is; `(NO_CLOTH, 0)` for a place none fills.
    pub colours: [Colour; 3],
}

/// One of a cell's colours: a cloth index and its quantized count.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Colour {
    pub index: u8,
    pub count: u16,
}

const NO_COLOUR: Colour = Colour { index: NO_CLOTH, count: 0 };

/// The three colours most worn among `cloths` (one [`CLOTH`] index per member; [`NO_CLOTH`] wears
/// none and is not counted).
fn top_colours(cloths: impl Iterator<Item = u8>) -> [Colour; 3] {
    let mut n = [0usize; CLOTH.len()];
    for c in cloths {
        if let Some(k) = n.get_mut(c as usize) {
            *k += 1;
        }
    }
    let mut order: Vec<(usize, usize)> = n.iter().enumerate().filter(|(_, k)| **k > 0).map(|(i, k)| (i, *k)).collect();
    order.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    let mut out = [NO_COLOUR; 3];
    for (slot, (i, k)) in out.iter_mut().zip(order) {
        *slot = Colour { index: i as u8, count: about(k) };
    }
    out
}

/// The cells of `throng` seen from `here`: one per occupied 6 m square, the farthest merged 2 x 2
/// until at most [`MAX_ROWS`] remain (and, should even that not do, the farthest left out).
/// `moving(id)` gives a member's velocity when it moves; `fighting(id)` whether it visibly fights;
/// `cloth(id)` the [`CLOTH`] index of what it wears ([`NO_CLOTH`] for none).
pub fn cells(here: (f32, f32), throng: &[NearCreature], moving: impl Fn(u32) -> Option<(f32, f32)>, fighting: impl Fn(u32) -> bool, cloth: impl Fn(u32) -> u8) -> Vec<Cell6> {
    if throng.is_empty() {
        return Vec::new();
    }
    // Squares (top-left x, y, side) -> members.
    let mut by: BTreeMap<(u32, u32, u32), Vec<&NearCreature>> = BTreeMap::new();
    for c in throng {
        let (cx, cy) = cell_of(c.pos);
        by.entry((cx, cy, 1)).or_default().push(c);
    }
    if by.len() > MAX_ROWS {
        // Farthest first: each far single square joins its 2 x 2 block, with every single square
        // of that block, until the rows fit.
        let centre = |(x, y, s): (u32, u32, u32)| ((x as f32 + s as f32 / 2.0) * CELL_M, (y as f32 + s as f32 / 2.0) * CELL_M);
        let mut singles: Vec<(u32, u32, u32)> = by.keys().copied().collect();
        singles.sort_by(|a, b| common::dist(here, centre(*b)).total_cmp(&common::dist(here, centre(*a))).then(a.cmp(b)));
        for sq in singles {
            if by.len() <= MAX_ROWS {
                break;
            }
            if !by.contains_key(&sq) {
                continue;
            }
            let block = (sq.0 & !1, sq.1 & !1, 2);
            let mut members = by.remove(&block).unwrap_or_default();
            for dx in 0..2 {
                for dy in 0..2 {
                    if let Some(m) = by.remove(&(block.0 + dx, block.1 + dy, 1)) {
                        members.extend(m);
                    }
                }
            }
            by.insert(block, members);
        }
    }
    let mut out: Vec<(f32, Cell6)> = by
        .into_iter()
        .map(|((x, y, s), cs)| {
            let n = cs.len();
            let (cx, cy) = (cs.iter().map(|c| c.pos.0).sum::<f32>() / n as f32, cs.iter().map(|c| c.pos.1).sum::<f32>() / n as f32);
            let spread = cs.iter().map(|c| (c.pos.0 - cx).hypot(c.pos.1 - cy)).fold(0.0f32, f32::max) * 2.0;
            let (mut vx, mut vy, mut movers, mut fighters, mut kinds) = (0.0f32, 0.0f32, 0usize, 0usize, 0u8);
            for c in &cs {
                if let Some((a, b)) = moving(c.id) {
                    movers += 1;
                    vx += a;
                    vy += b;
                }
                if fighting(c.id) {
                    fighters += 1;
                }
                kinds |= match &*c.kind {
                    "person" => PEOPLE,
                    "wolf" => WOLVES,
                    "deer" => DEER,
                    _ => OTHERS,
                };
            }
            let heading = if movers * 2 >= n && movers > 0 && (vx / movers as f32).hypot(vy / movers as f32) >= HEADING_MIN_MPS {
                ((vy.atan2(vx).to_degrees() / 45.0).round().rem_euclid(8.0)) as u8
            } else {
                STILL
            };
            let colours = top_colours(cs.iter().map(|c| cloth(c.id)));
            let row = Cell6 { cell: key(x, y), size: s as u8, count: about(n), spread: ((spread / 2.0).round() * 2.0).min(254.0) as u8, heading, moving: about(movers), fighting: about(fighters), kinds, colours };
            (common::dist(here, (cx, cy)), row)
        })
        .collect();
    if out.len() > MAX_ROWS {
        out.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cell.cmp(&b.1.cell)));
        out.truncate(MAX_ROWS);
    }
    let mut rows: Vec<Cell6> = out.into_iter().map(|(_, r)| r).collect();
    rows.sort_by_key(|r| (r.cell, r.size));
    rows
}

/// Bring `viewer`'s rows to its throng now (its character `id` at `here`), when its heed pass
/// ran at this sweep (`passed`) or the throng's members changed since its last cells.
pub fn show(ctx: &ReducerContext, id: u32, viewer: Identity, here: (f32, f32), throng: &[NearCreature], passed: bool, now: u64) {
    let mut ids: Vec<u32> = throng.iter().map(|c| c.id).collect();
    ids.sort_unstable();
    let same = LAST.with(|l| l.borrow().get(&id).is_some_and(|v| *v == ids));
    if same && !passed {
        return;
    }
    let _span = common::detail_span("sweep.throng");
    LAST.with(|l| l.borrow_mut().insert(id, ids));
    let sc = common::scripts(ctx);
    let moving = |c: u32| ctx.db.body().id().find(c).filter(|b| now < b.next_ms && (b.vx != 0.0 || b.vy != 0.0)).map(|b| (b.vx, b.vy));
    let fighting = |c: u32| crate::perception::visibly(ctx, &sc, c, now).is_some_and(|v| v.combat);
    // What one sees them wear: the cloth word of their look's top (a point lookup; none for animals
    // and lookless people).
    let cloth = |c: u32| ctx.db.look().id().find(c).map_or(NO_CLOTH, |l| cloth_index(&l.words.top));
    let new = cells(here, throng, moving, fighting, cloth);
    write(ctx, viewer, &new);
}

/// Make `viewer`'s rows exactly `new`, writing only what changed.
fn write(ctx: &ReducerContext, viewer: Identity, new: &[Cell6]) {
    let old: Vec<SeenThrong> = ctx.db.seen_throng().viewer().filter(viewer).collect();
    let mut kept: BTreeMap<(u32, u8), SeenThrong> = BTreeMap::new();
    for r in old {
        // Two rows of one square (should not happen): the second goes.
        if let Some(dup) = kept.insert((r.cell, r.size), r) {
            ctx.db.seen_throng().id().delete(dup.id);
        }
    }
    let (mut ins, mut upd) = (0u64, 0u64);
    for c in new {
        let [a, b, k] = c.colours;
        let fields = |id: u64| SeenThrong {
            id,
            viewer,
            cell: c.cell,
            size: c.size,
            count: c.count,
            spread: c.spread,
            heading: c.heading,
            moving: c.moving,
            fighting: c.fighting,
            kinds: c.kinds,
            colour_a: a.index,
            colour_a_count: a.count,
            colour_b: b.index,
            colour_b_count: b.count,
            colour_c: k.index,
            colour_c_count: k.count,
        };
        match kept.remove(&(c.cell, c.size)) {
            Some(r) => {
                let want = fields(r.id);
                if r != want {
                    ctx.db.seen_throng().id().update(want);
                    upd += 1;
                }
            }
            None => {
                ctx.db.seen_throng().insert(fields(0));
                ins += 1;
            }
        }
    }
    let del = kept.len() as u64;
    for (_, r) in kept {
        ctx.db.seen_throng().id().delete(r.id);
    }
    if ins > 0 {
        ANY.with(|a| a.set(Some(true)));
    }
    common::diag(|| "throng:insert", ins);
    common::diag(|| "throng:update", upd);
    common::diag(|| "throng:delete", del);
}

/// `viewer`'s rows go (heed no longer applies to it, its character died, another is played).
pub fn clear(ctx: &ReducerContext, id: u32, viewer: Identity) {
    LAST.with(|l| l.borrow_mut().remove(&id));
    if ANY.with(|a| a.get()) == Some(false) {
        return;
    }
    for r in ctx.db.seen_throng().viewer().filter(viewer).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.seen_throng().id().delete(r);
    }
}

/// The kill switch, once a tick: while heed does not apply to players, every row goes in this
/// tick. Nothing is read while none can exist.
pub fn off_tick(ctx: &ReducerContext) {
    if crate::heed::applies_player(ctx) {
        return;
    }
    if ANY.with(|a| a.get()) == Some(false) {
        return;
    }
    let rows: Vec<u64> = ctx.db.seen_throng().iter().map(|r| r.id).collect();
    LAST.with(|l| {
        if !l.borrow().is_empty() {
            l.borrow_mut().clear();
        }
    });
    if rows.is_empty() {
        ANY.with(|a| a.set(Some(false)));
        return;
    }
    common::diag(|| "throng:off_delete", rows.len() as u64);
    for r in rows {
        ctx.db.seen_throng().id().delete(r);
    }
    // Known empty only once a tick has found it so: this one may yet roll back.
    ANY.with(|a| a.set(None));
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::rc::Rc;

    fn c(id: u32, x: f32, y: f32) -> NearCreature {
        NearCreature { id, kind: Rc::from("person"), pos: (x, y), dist: 0.0, facing: 0.0 }
    }

    #[test]
    fn about_rounds_past_five() {
        assert_eq!([0, 1, 5, 6, 7, 8, 12, 13, 98].map(about), [0, 1, 5, 5, 5, 10, 10, 15, 100]);
    }

    #[test]
    fn one_row_per_square_keyed_by_its_top_left() {
        let t = [c(1, 1.0, 1.0), c(2, 5.9, 5.9), c(3, 6.1, 1.0)];
        let rows = cells((0.0, 0.0), &t, |_| None, |_| false, |_| NO_CLOTH);
        assert_eq!(rows.len(), 2);
        assert_eq!((rows[0].cell, rows[0].size, rows[0].count), (key(0, 0), 1, 2));
        assert_eq!((rows[1].cell, rows[1].size, rows[1].count), (key(1, 0), 1, 1));
        assert!(rows.iter().all(|r| r.heading == STILL && r.kinds == PEOPLE));
    }

    #[test]
    fn heading_in_eight_sectors_clockwise_from_east() {
        let t = [c(1, 1.0, 1.0), c(2, 2.0, 2.0)];
        let south = cells((0.0, 0.0), &t, |_| Some((0.0, 1.5)), |_| false, |_| NO_CLOTH);
        assert_eq!((south[0].heading, south[0].moving), (2, 2));
        let north = cells((0.0, 0.0), &t, |_| Some((0.0, -1.5)), |_| true, |_| NO_CLOTH);
        assert_eq!((north[0].heading, north[0].fighting), (6, 2));
        // One of two moving, the other standing: half move, so a heading; none: still.
        let half = cells((0.0, 0.0), &t, |id| (id == 1).then_some((1.0, 0.0)), |_| false, |_| NO_CLOTH);
        assert_eq!(half[0].heading, 0);
        let slow = cells((0.0, 0.0), &t, |_| Some((0.1, 0.0)), |_| false, |_| NO_CLOTH);
        assert_eq!(slow[0].heading, STILL);
    }

    #[test]
    fn colours_most_worn_first_quantized_as_count() {
        // 7 in green (2), 2 in navy (7), 2 in black (1), 1 in red (5), 1 with no look.
        let t: Vec<NearCreature> = (0..13).map(|i| c(i, 1.0 + (i % 5) as f32, 1.0)).collect();
        let cloth = |id: u32| match id { 0..=6 => 2, 7 | 8 => 7, 9 | 10 => 1, 11 => 5, _ => NO_CLOTH };
        let rows = cells((0.0, 0.0), &t, |_| None, |_| false, cloth);
        assert_eq!(rows.len(), 1);
        // Green's 7 reads as about 5; black and navy tie at 2 (black first, the lower index); red
        // is fourth and left out; the member with no look counts in `count` but wears no colour.
        assert_eq!(rows[0].colours, [Colour { index: 2, count: 5 }, Colour { index: 1, count: 2 }, Colour { index: 7, count: 2 }]);
        assert_eq!(rows[0].count, about(13));
        // No looks at all: no colours.
        let none = cells((0.0, 0.0), &t[..3], |_| None, |_| false, |_| NO_CLOTH);
        assert_eq!(none[0].colours, [NO_COLOUR; 3]);
    }

    #[test]
    fn the_farthest_merge_until_the_rows_fit() {
        // 60 single squares in a row eastward: the far ones merge 2 x 2.
        let t: Vec<NearCreature> = (0..60).map(|i| c(i, i as f32 * CELL_M + 1.0, 1.0)).collect();
        let rows = cells((0.0, 0.0), &t, |_| None, |_| false, |_| NO_CLOTH);
        assert!(rows.len() <= MAX_ROWS, "{}", rows.len());
        let total: u16 = rows.iter().map(|r| r.count).sum();
        assert_eq!(total, 60, "nobody is lost by merging");
        let merged: Vec<&Cell6> = rows.iter().filter(|r| r.size == 2).collect();
        assert!(!merged.is_empty());
        // The merged squares are the far ones, keyed by an even top-left.
        let nearest_merged = merged.iter().map(|r| r.cell >> 16).min().unwrap();
        assert!(rows.iter().filter(|r| r.size == 1).all(|r| (r.cell >> 16) < nearest_merged));
        assert!(merged.iter().all(|r| (r.cell >> 16) % 2 == 0 && (r.cell & 0xFFFF) % 2 == 0));
    }
}
