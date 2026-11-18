//! A deliberation reads its request when its model call's turn comes (docs/MIND_HARNESS.md,
//! "Requests read at their turn").
//!
//! The authority merges every reason for a character into its one pending request and retakes
//! its scene at each merge (perceive.rs, `request`); the mind service deliberates one request
//! per character at a time (`schedule`). Before 2026-11-13 the prompt was built from the
//! request as it stood when the deliberation began, and the call then waited for a model slot:
//! in a 200-fighter battle about 5 s at the median and 17 s at p90 for an urgent one. Each blow
//! or alarm that arrived in that wait was left for a follow-up deliberation, which queued again.
//!
//! Now the request is read when its ticket is nominated for prompt preparation ([`Llm::turn`]): the
//! merged reasons are all in the prompt, beside the scene the request carries at that read
//! (scene-since). What it consumes is what it read (`seen_ms` is that row's `updated_ms`), so a
//! reason arriving after the read, while the call runs, stays pending and is the next
//! deliberation's. Every mind does this: persons, animals, the animal choice.
//!
//! The ticket keeps its lane and position. It holds no model slot during prompt preparation.
//!
//! Recorded in the journal's `outcomes/turn.jsonl`: per deliberation the lines it was asked
//! with, the lines it read and how many merged while it waited.

use super::Minds;
use crate::llm::{Attention, Lane, Msg, Reply, Turn};
use anyhow::Result;
use living_bindings::*;
use serde_json::json;
use spacetimedb_sdk::Table;

/// Reason lines in `taken` that arrived after `asked` was read: those that merged while the
/// deliberation waited for its turn.
pub fn merged_lines(asked: &Deliberation, taken: &Deliberation) -> usize {
    living_rules::reasons::lines(&taken.reason, &taken.arrived).iter().filter(|(_, at)| *at > asked.updated_ms).count()
}

impl Minds {
    /// The character's pending request as the mind service sees it (with the level of detail
    /// on, its own copy, which gathers the same merges).
    pub(super) fn request_row(&self, actor: u32) -> Option<Deliberation> {
        if self.lod.on {
            self.pending.lock().unwrap().get(&actor).map(|p| p.row.clone())
        } else {
            self.conn.db.my_deliberations().iter().find(|d| d.actor == actor)
        }
    }

    /// Wait for the first call's preparation turn, then read the request: `asked` with whatever merged into
    /// it meanwhile. The turn is `None` when the slot could not be had (the call is then made
    /// as before, and fails or recovers as before).
    pub(super) async fn take_turn(&self, asked: &Deliberation, route: &str, at: Attention, purpose: &str, lane: Lane) -> (Option<Turn<'_>>, Deliberation) {
        let mut turn = self.llm.turn(route, at, purpose, lane).await.ok();
        let taken = self.request_row(asked.actor).filter(|d| d.updated_ms >= asked.updated_ms).unwrap_or_else(|| asked.clone());
        let merged = merged_lines(asked, &taken);
        if let Some(turn) = turn.as_mut().filter(|_| lane == Lane::Routine && merged > 0) {
            let first_urgent = living_rules::reasons::lines(&taken.reason, &taken.arrived)
                .into_iter()
                .filter(|(line, at)| *at > asked.updated_ms && Lane::deliberation(line, false) == Lane::Urgent)
                .map(|(_, at)| at)
                .min();
            turn.record_urgent_arrival(first_urgent);
        }
        self.actors.lock().unwrap().entry(asked.actor).or_default().taken_ms = taken.updated_ms;
        self.llm
            .outcome(
                "turn",
                &json!({
                    "at_ms": crate::llm::now_ms(),
                    "actor": asked.actor,
                    "lane": lane,
                    "purpose": purpose,
                    "queue_wait_ms": turn.as_ref().map(|t| t.queue_wait_ms),
                    "asked_ms": asked.updated_ms,
                    "taken_ms": taken.updated_ms,
                    "asked_lines": living_rules::reasons::lines(&asked.reason, &asked.arrived).len(),
                    "taken_lines": living_rules::reasons::lines(&taken.reason, &taken.arrived).len(),
                    "merged": merged,
                }),
            )
            .await;
        if merged > 0 {
            log::info!("{}: {merged} reason(s) merged while its deliberation waited for its turn", self.name(asked.actor));
        }
        (turn, taken)
    }

    /// Dispatch the first call on its queued ticket, any other as usual.
    pub(super) async fn call_on_turn(&self, turn: &mut Option<Turn<'_>>, route: &str, at: Attention, purpose: &str, actor: &str, messages: &[Msg], lane: Lane) -> Result<Reply> {
        match turn.take() {
            Some(t) => self.llm.chat_in_turn(t, at, purpose, actor, messages).await,
            None => self.llm.chat_in_lane(route, at, purpose, actor, messages, lane).await,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(reason: &str, arrived: &str, updated_ms: u64) -> Deliberation {
        Deliberation { actor: 7, controller: spacetimedb_sdk::Identity::ZERO, reason: reason.into(), requested_ms: 1_000, updated_ms, scene: "{}".into(), revision: 0, arrived: arrived.into() }
    }

    /// Three blows in a few seconds: the deliberation asked at the first reads all three at its
    /// turn and consumes them; a fourth arriving while its call runs stays for a follow-up.
    #[test]
    fn blows_merged_while_waiting_are_read_and_a_later_one_is_the_next_deliberations() {
        let (mut reason, mut arrived) = ("Brak is attacking you!".to_string(), living_rules::reasons::first("Brak is attacking you!", 1_000));
        let asked = row(&reason, &arrived, 1_000);
        living_rules::reasons::add(&mut reason, &mut arrived, "Brak hit you again.", 2_500);
        living_rules::reasons::add(&mut reason, &mut arrived, "Brak hit you a third time.", 4_000);
        let taken = row(&reason, &arrived, 4_000);
        assert_eq!(merged_lines(&asked, &taken), 2);
        // the turn's read consumes what it read, all three
        assert_eq!(living_rules::reasons::consume(&reason, &arrived, taken.updated_ms, true), None);
        // a blow mid-flight (after the read) is kept
        living_rules::reasons::add(&mut reason, &mut arrived, "Brak hit you a fourth time.", 6_000);
        assert_eq!(living_rules::reasons::consume(&reason, &arrived, taken.updated_ms, true), Some(("Brak hit you a fourth time.".to_string(), "6000".to_string())));
        // read as before (at the first blow), two of them would have been left for a follow-up
        assert_eq!(living_rules::reasons::consume(&reason, &arrived, asked.updated_ms, true).map(|(r, _)| r.lines().count()), Some(3));
    }
}
