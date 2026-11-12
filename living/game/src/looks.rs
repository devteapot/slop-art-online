//! What I call the people I perceive (interface D, 2026-11-11).
//!
//! - **A name only when the rules give it:** the projection's `name` from `seen_characters`
//!   (empty until my character knows it: kin, community, or someone who told it their name,
//!   docs/PERCEPTION.md). The client never shows a name from anywhere else.
//! - **Strangers by looks only:** the projection's own label ("a stranger", "a child", "an old
//!   stranger", "a baby") with the colour of their clothes as this client draws them (the recipe
//!   seeded by the land and their id, in the projection's folk and dress: `live::recipe_for`),
//!   "a child in red". When two strangers shown read alike, the second colour tells them apart
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
/// bottom.
fn clothes(r: &crate::characters::Recipe) -> (Option<String>, Option<String>) {
    let over = ["torso", "coat", "jacket", "top", "body"].iter().find_map(|s| r.colors.outfit.get(*s).cloned());
    (over.or_else(|| r.colors.top.clone()), r.colors.bottom.clone())
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
        // The recipe is fixed by the land, the id and the projection's folk and dress.
        let (top, bottom) = match (looks.colours.get(&c.id), seed) {
            (Some(k), _) => k.clone(),
            (None, Some(s)) => {
                let k = clothes(&crate::live::recipe_for(s, c, false));
                looks.colours.insert(c.id, k.clone());
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
    use super::colour_name;

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
