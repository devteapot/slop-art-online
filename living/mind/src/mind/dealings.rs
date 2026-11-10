//! Dealings: the records a character is a party to (agreements, demands, its community's
//! regard for others; docs/WORLD_RULES.md), as the world's rules word them (`record_text`) and
//! named as the character knows the people in them. Only the character's own records are
//! shown: the record table is audit truth, and others learn of a record by perception.

use super::Minds;
use living_bindings::*;
use living_rules::records::{RecordFacts, COMMUNITY};
use spacetimedb_sdk::Table;

impl Minds {
    /// The records `me` is a party to, itself or through its community.
    fn records_of(&self, me: u32) -> Vec<RecordFacts> {
        let now = crate::llm::now_ms();
        let community = self.conn.db.membership().member().find(&me).map_or(0, |m| COMMUNITY | m.community as u64);
        let mine = |p: u64| p == me as u64 || (community != 0 && p == community);
        let mut out: Vec<RecordFacts> = Vec::new();
        for p in self.conn.db.record_party().iter().filter(|p| mine(p.party)) {
            if out.iter().any(|r| r.id == p.record) {
                continue;
            }
            let Some(r) = self.conn.db.record().id().find(&p.record) else { continue };
            let mut parties: Vec<(String, u64)> = self.conn.db.record_party().iter().filter(|x| x.record == r.id).map(|x| (x.role, x.party)).collect();
            parties.sort();
            out.push(RecordFacts {
                id: r.id,
                kind: r.kind,
                status: r.status,
                open: r.open,
                terms: serde_json::from_str(&r.terms).unwrap_or_default(),
                parties,
                me: p.role,
                by: r.by,
                age_s: now.saturating_sub(r.made_ms) as f32 / 1000.0,
                due_s: (r.due_ms != u64::MAX).then(|| (r.due_ms as i64 - now as i64) as f32 / 1000.0),
            });
        }
        out.sort_by_key(|r| r.id);
        out
    }

    /// A record's words with `{id:N}` named as `me` knows N (a community by its name).
    fn record_words(&self, me: u32, text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        let mut rest = text;
        while let Some(i) = rest.find("{id:") {
            out.push_str(&rest[..i]);
            let Some(j) = rest[i..].find('}') else { break };
            let n = rest[i + 4..i + j].trim().parse::<u64>().unwrap_or(0);
            if n >= COMMUNITY {
                out.push_str(&self.conn.db.community().id().find(&((n - COMMUNITY) as u32)).map(|c| c.name).unwrap_or_else(|| "another people".into()));
            } else if n == me as u64 {
                out.push_str("you");
            } else {
                out.push_str(&self.known_as(me, n as u32));
            }
            rest = &rest[i + j + 1..];
        }
        out.push_str(rest);
        out
    }

    /// `me`'s open dealings and its people's standing, one line each.
    pub(super) fn dealings(&self, me: u32) -> Vec<String> {
        self.records_of(me).iter().filter(|r| r.open).filter_map(|r| crate::prompts::record_text(r).map(|t| self.record_words(me, &t))).collect()
    }

    /// `me`'s dealings with `other` (records naming both of them), open or just closed.
    pub(super) fn dealings_with(&self, me: u32, other: u32) -> Vec<String> {
        self.records_of(me)
            .iter()
            .filter(|r| r.parties.iter().any(|(_, p)| *p == other as u64))
            .filter_map(|r| crate::prompts::record_text(r).map(|t| self.record_words(me, &t)))
            .collect()
    }
}
