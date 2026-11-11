//! The reasons of a pending deliberation request: newline-separated lines, each with the time
//! it arrived (`arrived`, aligned with the lines). A deliberation consumes the lines its prompt
//! contained, those that arrived no later than the request it read (`seen_ms`); lines that
//! arrived while the model was thinking stay pending.

/// Reasons about the plan being replaced; a new plan makes them obsolete.
pub const PLAN_STATE: &[&str] = &["Nothing in my current plan works", "My actions keep failing", "I finished my plan", "A quiet moment to take stock"];

/// Longest reason text a request gathers; later reasons only refresh it.
pub const MAX_LEN: usize = 900;

/// Arrival times aligned with `reason`'s lines, from the space-separated `arrived`. Rows
/// written before arrival times were kept have none: their lines count as old (arrived at 0).
fn aligned(reason: &str, arrived: &str) -> Vec<u64> {
    let n = reason.split('\n').count();
    let mut a: Vec<u64> = arrived.split_whitespace().map(|t| t.parse().unwrap_or(0)).take(n).collect();
    a.resize(n, 0);
    a
}

fn encode(times: &[u64]) -> String {
    times.iter().map(|t| t.to_string()).collect::<Vec<_>>().join(" ")
}

/// The arrival times of a new request's first reason.
pub fn first(reason: &str, now: u64) -> String {
    encode(&vec![now; reason.split('\n').count()])
}

/// Add a reason that arrived at `now`. A reason already pending is not repeated, and keeps
/// its first arrival time: the deliberation that saw it once has seen it.
pub fn add(reason: &mut String, arrived: &mut String, line: &str, now: u64) {
    if reason.contains(line) || reason.len() >= MAX_LEN {
        return;
    }
    let mut a = aligned(reason, arrived);
    reason.push('\n');
    reason.push_str(line);
    a.extend(std::iter::repeat(now).take(line.split('\n').count()));
    *arrived = encode(&a);
}

/// What stays pending after a deliberation that read the request as of `seen_ms`: the lines
/// that arrived later, without reasons about the old plan when a new one was installed
/// (`new_plan`). `None`: nothing stays, and the request is removed.
pub fn consume(reason: &str, arrived: &str, seen_ms: u64, new_plan: bool) -> Option<(String, String)> {
    let (lines, times): (Vec<&str>, Vec<u64>) = reason
        .split('\n')
        .zip(aligned(reason, arrived))
        .filter(|(l, t)| *t > seen_ms && !l.trim().is_empty() && !(new_plan && PLAN_STATE.iter().any(|p| l.starts_with(p))))
        .unzip();
    (!lines.is_empty()).then(|| (lines.join("\n"), encode(&times)))
}

/// Each pending line with its arrival time (for the record of what a deliberation carried).
pub fn lines(reason: &str, arrived: &str) -> Vec<(String, u64)> {
    reason.split('\n').zip(aligned(reason, arrived)).filter(|(l, _)| !l.trim().is_empty()).map(|(l, t)| (l.to_string(), t)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(line: &str, at: u64) -> (String, String) {
        (line.to_string(), first(line, at))
    }

    #[test]
    fn a_seen_reason_is_consumed_even_when_plan_churn_arrives_during_the_call() {
        // The defect: a one-off feeling seen by the prompt, then "I finished my plan" while the
        // model thinks. Before, the feeling stayed pending and was the reason of the next thought.
        let (mut r, mut a) = request("You wonder about the stranger by the well.", 1_000);
        let seen = 1_000;
        add(&mut r, &mut a, "I finished my plan.", 2_000);
        assert_eq!(consume(&r, &a, seen, true), None);
        // A failed or empty deliberation (no new plan) keeps only the later plan reason.
        assert_eq!(consume(&r, &a, seen, false), Some(("I finished my plan.".to_string(), "2000".to_string())));
    }

    #[test]
    fn reasons_that_arrive_during_the_call_stay_pending() {
        let (mut r, mut a) = request("You long for another child.", 1_000);
        add(&mut r, &mut a, "I finished my plan.", 1_500);
        add(&mut r, &mut a, "Aro (#4) is attacking you!", 2_000);
        add(&mut r, &mut a, "You are starving and have no food.", 2_500);
        let (rest, times) = consume(&r, &a, 1_500, true).unwrap();
        assert_eq!(rest, "Aro (#4) is attacking you!\nYou are starving and have no food.");
        assert_eq!(times, "2000 2500");
        // The next deliberation reads them, and they are gone after it.
        assert_eq!(consume(&rest, &times, 2_500, true), None);
    }

    #[test]
    fn a_repeated_reason_is_not_renewed() {
        let (mut r, mut a) = request("You wonder about the stranger by the well.", 1_000);
        add(&mut r, &mut a, "You wonder about the stranger by the well.", 3_000);
        assert_eq!(a, "1000");
        assert_eq!(consume(&r, &a, 1_000, false), None);
    }

    #[test]
    fn churn_cannot_keep_a_feeling_alive_over_many_deliberations() {
        let (mut r, mut a) = request("You long for another child.", 0);
        let mut carried = 0;
        let mut seen = 0;
        for i in 1..=40u64 {
            if r.contains("another child") {
                carried += 1;
            }
            add(&mut r, &mut a, "I finished my plan.", seen + 1);
            match consume(&r, &a, seen, true) {
                Some((rest, times)) => (r, a) = (rest, times),
                None => {
                    (r, a) = request("I finished my plan.", seen + 2);
                }
            }
            seen = i * 10;
        }
        assert_eq!(carried, 1);
    }

    #[test]
    fn legacy_rows_and_multiline_reasons() {
        // Without arrival times every line counts as old.
        assert_eq!(consume("old one\nold two", "", 5, false), None);
        let mut r = "a".to_string();
        let mut a = String::new();
        add(&mut r, &mut a, "b\nc", 7);
        assert_eq!(a, "0 7 7");
        assert_eq!(lines(&r, &a), vec![("a".into(), 0), ("b".into(), 7), ("c".into(), 7)]);
        assert_eq!(consume(&r, &a, 5, false).unwrap().0, "b\nc");
    }

    #[test]
    fn a_full_request_takes_no_more_lines() {
        let (mut r, mut a) = request(&"x".repeat(MAX_LEN), 1);
        add(&mut r, &mut a, "late", 2);
        assert_eq!((r.len(), a.as_str()), (MAX_LEN, "1"));
    }
}
