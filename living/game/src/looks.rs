//! What I call the people I perceive (interface D, 2026-11-11).
//!
//! - **A name only when the rules give it:** the projection's `name` from `seen_characters`
//!   (empty until my character knows it: kin, community, or someone who told it their name,
//!   docs/PERCEPTION.md). The client never shows a name from anywhere else.
//! - **Strangers by looks only:** the projection's own label ("a stranger", "a child", "an old
//!   stranger", "a baby") with the colour of their clothes as this client draws them
//!   (`live::recipe_for`: their look's line, else the VRoid recipe seeded by the land and their
//!   id), "a child in red". A line's chips are its pieces' own colours ([`clothes`]). When two strangers shown read alike, the second colour tells them apart
//!   ("a stranger in blue and brown"). No role and no place.
//! - Animals keep the projection's label ("a wolf").
//! - **Too far to make out** (far-label: beyond the world's recognising range, Cullet's
//!   `known_within` 24 m, known or not): the projection says "someone too far away to make out"
//!   and no name. That text is what the Log, the talk target, act titles and notes show. Plates
//!   and hover ([`Looks::plate`]) show "someone in blue" from the colours drawn: presentation only,
//!   never in anything sent back (speech, addressing, acts, offers carry ids and my own words).
//!
//! Labels are kept for people no longer perceived, so a window or the log still names them as
//! they were last seen. [`Looks::of`] is what every part of the UI shows.

use crate::net::Net;
use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashMap;

/// The projection's label for a person too far away to make out (far-label).
pub const FAR: &str = "someone too far away to make out";

#[derive(Resource, Default)]
pub struct Looks {
    labels: HashMap<u32, String>,
    /// Plates and hover for someone too far to make out: "someone in blue" (presentation only).
    plates: HashMap<u32, String>,
    /// The top and second colours drawn, by id (sRGB hex), for portraits.
    pub colours: HashMap<u32, (Option<String>, Option<String>)>,
    /// The look key each one's colours were read from (empty: a VRoid recipe), so a new look
    /// reads them again.
    drawn_from: HashMap<u32, String>,
    /// When a name first arrived for someone (they were a stranger to me before).
    pub named: Vec<(u32, String)>,
    known: HashMap<u32, bool>,
}

impl Looks {
    /// How I name someone now, or as last perceived.
    pub fn of(&self, id: u32) -> Option<&str> {
        self.labels.get(&id).map(|s| s.as_str())
    }

    /// How a plate or hover names them: as [`Looks::of`], except someone too far away to make
    /// out, by the colours drawn ("someone in blue"). Never sent anywhere.
    pub fn plate(&self, id: u32) -> Option<&str> {
        self.plates.get(&id).or_else(|| self.labels.get(&id)).map(|s| s.as_str())
    }

    /// The same, capitalised for the start of a line.
    pub fn cap(&self, id: u32) -> String {
        crate::ui::label(self.of(id).unwrap_or("someone"))
    }
}

/// The names the authority has given me to show (for the UI dump's guard): everyone my character
/// knows by name (`my_known_names`: itself, family, community, introductions, its community's
/// remembered dead), everyone I perceive by name, and my own characters.
pub fn known_names(net: &Net) -> Vec<String> {
    let Some(c) = net.conn.as_ref() else { return Vec::new() };
    c.db.my_known_names().iter().map(|x| x.name).chain(c.db.seen_characters().iter().map(|x| x.name)).chain(c.db.my_characters().iter().map(|x| x.name)).filter(|n| !n.trim().is_empty()).collect()
}

/// A structure as my character may call it (owner-known, docs/PERCEPTION.md "Whose a thing is,
/// and what places are called"): my own "your house"; one whose owner my character knows by
/// name (`my_known_names`) "Bram's house"; else the kind alone, "house". The authority's law is
/// `owner_shown(#{knows, shows, kind})`, shipped `knows || shows`; `shows` (a sign trait) is set
/// by no shipped kind and has no client field yet, so `knows` is the whole rule here. Nothing
/// else in the client names an owner: not `land.params` (no names since owner-known), not the
/// seed, not `structure.owner` alone.
pub fn structure_name(conn: &DbConnection, me: u32, kind: &str, owner: u32) -> String {
    let kind = kind.replace('_', " ");
    if owner == 0 {
        return kind;
    }
    if owner == me {
        return format!("your {kind}");
    }
    match conn.db.my_known_names().id().find(&owner).map(|k| k.name).filter(|n| !n.trim().is_empty()) {
        Some(name) => format!("{name}'s {kind}"),
        None => kind,
    }
}

/// Whom I perceive now (`seen_characters` ids), for the UI dump.
pub fn perceived_ids(net: &Net) -> Vec<u32> {
    let Some(c) = net.conn.as_ref() else { return Vec::new() };
    let mut v: Vec<u32> = c.db.seen_characters().iter().map(|x| x.id).collect();
    v.sort_unstable();
    v
}

/// The places the rules say my character knows (`my_places`), by name.
pub fn given_places(net: &Net) -> Vec<String> {
    let Some(c) = net.conn.as_ref() else { return Vec::new() };
    c.db.my_places().iter().map(|p| p.name).filter(|n| !n.trim().is_empty()).collect()
}

/// A colour's name, from its hue, saturation and value (a few plain words).
pub fn colour_name(hex: &str) -> Option<&'static str> {
    let h = hex.trim_start_matches('#');
    if h.len() != 6 {
        return None;
    }
    let n = u32::from_str_radix(h, 16).ok()?;
    let (r, g, b) = (((n >> 16) & 255) as f32 / 255.0, ((n >> 8) & 255) as f32 / 255.0, (n & 255) as f32 / 255.0);
    let (max, min) = (r.max(g).max(b), r.min(g).min(b));
    let (v, d) = (max, max - min);
    let s = if max > 0.0 { d / max } else { 0.0 };
    if s < 0.16 || d < 0.06 {
        return Some(match v {
            v if v < 0.22 => "black",
            v if v < 0.5 => "dark grey",
            v if v < 0.8 => "grey",
            _ => "white",
        });
    }
    let hue = if max == r {
        60.0 * (((g - b) / d) % 6.0)
    } else if max == g {
        60.0 * ((b - r) / d + 2.0)
    } else {
        60.0 * ((r - g) / d + 4.0)
    };
    let hue = (hue + 360.0) % 360.0;
    Some(match hue {
        h if !(12.0..345.0).contains(&h) => {
            if v < 0.45 {
                "dark red"
            } else {
                "red"
            }
        }
        h if h < 45.0 => {
            if v < 0.55 {
                "brown"
            } else if s < 0.5 {
                "tan"
            } else {
                "orange"
            }
        }
        h if h < 70.0 => {
            if v < 0.55 {
                "olive"
            } else {
                "yellow"
            }
        }
        h if h < 165.0 => "green",
        h if h < 195.0 => "teal",
        h if h < 255.0 => "blue",
        h if h < 300.0 => "purple",
        _ => "plum",
    })
}

/// The colours a person is seen wearing: the top (or an outfit piece worn over it), then the
/// bottom. A composed line's are its outermost upper and lower pieces' own colours
/// (`colors.outfit` by piece name; which piece is which from [`place`]).
fn clothes(r: &crate::characters::Recipe) -> (Option<String>, Option<String>) {
    if let Some(p) = &r.person {
        let outer = |want: Part| p.styles.outfit.iter().filter_map(|piece| place(piece).filter(|(part, _)| *part == want).map(|(_, layer)| (layer, piece))).max_by_key(|(layer, _)| *layer).and_then(|(_, piece)| p.colors.outfit.get(piece).cloned());
        return (outer(Part::Upper), outer(Part::Lower));
    }
    let over = ["torso", "coat", "jacket", "top", "body"].iter().find_map(|s| r.colors.outfit.get(*s).cloned());
    (over.or_else(|| r.colors.top.clone()), r.colors.bottom.clone())
}

/// Which part of the body an outfit piece covers, for its chip.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Part {
    Upper,
    Lower,
}

/// An outfit style's part and layer (higher is worn over lower): `slot` and `layer` from the style
/// file's glTF extras (char-4 writes them; the scene's, else the first node's or the asset's that
/// carries a `slot`), else by its name until they are written. None for what gives no chip (boots,
/// caps, an apron or a smock's bands over the clothes).
fn place(piece: &str) -> Option<(Part, i32)> {
    static CACHE: std::sync::OnceLock<std::sync::Mutex<HashMap<String, Option<(Part, i32)>>>> = std::sync::OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(p) = cache.lock().unwrap().get(piece) {
        return *p;
    }
    let part = |slot: &str| match slot {
        "upper" | "top" | "torso" => Some(Part::Upper),
        "lower" | "bottom" | "legs" => Some(Part::Lower),
        _ => None,
    };
    let from_file = || {
        let file = format!("{}/outfit/{piece}.glb", crate::characters::compose::STYLES);
        let j = crate::lookdev::glb_json(&file)?;
        let scene = &j["scenes"][j["scene"].as_u64().unwrap_or(0) as usize]["extras"];
        let nodes = j["nodes"].as_array().into_iter().flatten().map(|n| &n["extras"]);
        let x = std::iter::once(scene).chain(nodes).chain(std::iter::once(&j["asset"]["extras"])).find(|x| x["slot"].is_string())?;
        Some(part(x["slot"].as_str()?).map(|p| (p, x["layer"].as_i64().unwrap_or(0) as i32)))
    };
    let p = from_file().unwrap_or_else(|| place_by_name(piece));
    cache.lock().unwrap().insert(piece.to_string(), p);
    p
}

/// A piece's part and layer by its name's stem (`smock_58-f` → `smock`), until its file says.
fn place_by_name(piece: &str) -> Option<(Part, i32)> {
    let stem = piece.trim_end_matches("-f").trim_end_matches("-m");
    let stem = stem.rsplit_once('_').filter(|(_, n)| n.chars().all(|c| c.is_ascii_digit())).map_or(stem, |(s, _)| s);
    match stem {
        "jersey" | "jersey_smock" | "jersey_coat" => Some((Part::Upper, 1)),
        "smock" => Some((Part::Upper, 2)),
        "coat" => Some((Part::Upper, 3)),
        "trousers" | "skirt" => Some((Part::Lower, 1)),
        _ => None,
    }
}

/// Keep the labels of everyone perceived (Mirror phase, after the rows arrive).
pub fn update(net: NonSend<Net>, island: Option<Res<crate::island::Island>>, mut looks: ResMut<Looks>, time: Res<Time>, mut next: Local<f64>) {
    let Some(conn) = net.conn.as_ref() else { return };
    // Labels change rarely (a new face, a name learned): four times a second is enough.
    let now = time.elapsed_secs_f64();
    if now < *next {
        return;
    }
    *next = now + 0.25;
    let me = net.my_id;
    let seed = island.as_ref().map(|i| i.land.seed);
    let seen: Vec<SeenCharacter> = conn.db.seen_characters().iter().filter(|c| Some(c.id) != me).collect();
    let mut base: Vec<(u32, String, Option<String>, Option<String>)> = Vec::with_capacity(seen.len());
    for c in &seen {
        if !c.name.trim().is_empty() {
            let was = looks.known.insert(c.id, true);
            if was == Some(false) {
                looks.named.push((c.id, c.name.clone()));
            }
            base.push((c.id, c.name.clone(), None, None));
            continue;
        }
        // Too far to make out says nothing of whether I know them: no "name learned" later.
        if c.label != FAR {
            looks.known.entry(c.id).or_insert(false);
        }
        if c.kind != "person" {
            base.push((c.id, c.label.clone(), None, None));
            continue;
        }
        // The recipe is fixed by their look (else the land, the id and the projection's folk and
        // dress); read again when the look changes.
        let key = crate::characters::seen::of(c).look;
        let fresh = looks.drawn_from.get(&c.id) == Some(&key);
        let (top, bottom) = match (looks.colours.get(&c.id).filter(|_| fresh), seed) {
            (Some(k), _) => k.clone(),
            (None, Some(s)) => {
                let k = clothes(&crate::live::recipe_for(crate::characters::book::book(), s, c));
                looks.colours.insert(c.id, k.clone());
                looks.drawn_from.insert(c.id, key);
                k
            }
            (None, None) => (None, None),
        };
        base.push((c.id, c.label.clone(), top, bottom));
    }
    // "a child in red"; a second colour where two read alike. Someone too far away to make out
    // keeps the projection's words, and gets "someone in blue" for plates and hover only.
    let far = |l: &str| l == FAR;
    let shown = |l: &str| if far(l) { "someone".to_string() } else { l.to_string() };
    let first: Vec<String> = base.iter().map(|(_, l, t, _)| match t.as_deref().and_then(colour_name) {
        Some(col) => format!("{} in {col}", shown(l)),
        None => shown(l),
    }).collect();
    for (i, (id, l, t, b)) in base.iter().enumerate() {
        let twin = t.is_some() && first.iter().enumerate().any(|(j, f)| j != i && *f == first[i]);
        let dressed = match (twin, t.as_deref().and_then(colour_name), b.as_deref().and_then(colour_name)) {
            (true, Some(a), Some(c)) if a != c => format!("{} in {a} and {c}", shown(l)),
            _ => first[i].clone(),
        };
        let label = if far(l) { l.clone() } else { dressed.clone() };
        if far(l) {
            if looks.plates.get(id) != Some(&dressed) {
                looks.plates.insert(*id, dressed);
            }
        } else {
            looks.plates.remove(id);
        }
        if looks.labels.get(id) != Some(&label) {
            looks.labels.insert(*id, label);
        }
    }
    if looks.labels.len() > 4096 {
        let live: std::collections::HashSet<u32> = seen.iter().map(|c| c.id).collect();
        looks.labels.retain(|id, _| live.contains(id));
        looks.plates.retain(|id, _| live.contains(id));
    }
}

#[cfg(test)]
mod tests {
    use super::{clothes, colour_name, place_by_name, Part};

    /// A composed line's chips are its outermost upper and lower pieces' own colours.
    #[test]
    fn a_lines_chips_are_its_outer_pieces() {
        assert_eq!(place_by_name("smock_58-f"), Some((Part::Upper, 2)));
        assert_eq!(place_by_name("jersey_smock-m"), Some((Part::Upper, 1)));
        assert_eq!(place_by_name("trousers-f"), Some((Part::Lower, 1)));
        assert_eq!(place_by_name("apron_58-f"), None);
        assert_eq!(place_by_name("smock_bands-f"), None);
        let person: crate::characters::compose::Person = serde_json::from_value(serde_json::json!({
            "type": "adult-f-a", "height": 1.66,
            "colors": { "outfit": { "smock_58-f": "#c8bfa8", "smock_bands-f": "#5a4a3a", "jersey_smock-f": "#3a3a3a", "apron_58-f": "#e0d8c8", "trousers-f": "#33363e" } },
            "styles": { "outfit": ["smock_58-f", "smock_bands-f", "jersey_smock-f", "apron_58-f", "trousers-f"] }
        }))
        .unwrap();
        let r = crate::characters::Recipe { person: Some(person), ..crate::characters::Recipe::default_for("lookdev/types/adult-f-a.glb") };
        assert_eq!(clothes(&r), (Some("#c8bfa8".into()), Some("#33363e".into())));
    }

    #[test]
    fn clothes_colours_read_as_plain_words() {
        assert_eq!(colour_name("#7a2a2a"), Some("red"));
        assert_eq!(colour_name("#2c3c6a"), Some("blue"));
        assert_eq!(colour_name("#3c5a32"), Some("green"));
        assert_eq!(colour_name("#6b4a2e"), Some("brown"));
        assert_eq!(colour_name("#e0d8c8"), Some("white"));
        assert_eq!(colour_name("#2a2a30"), Some("black"));
        assert_eq!(colour_name("#6a3a5a"), Some("plum"));
        assert_eq!(colour_name("#3a6a6a"), Some("teal"));
        assert_eq!(colour_name("bad"), None);
    }
}
