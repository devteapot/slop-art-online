//! How long a line takes to say aloud: the pace an exchange keeps (docs/COMMUNICATION.md §21).
//! The mind service holds a reply's place in the exchange's rhythm until the line it answers is
//! done being said (`talk.rs` `saying_ms`, `Pace::of`), and the game client shows a reply's
//! bubble at that same place (`ui/live.rs` `paced`), now that the reply itself is said as soon
//! as it is ready.

/// Milliseconds a word: people speak about three words a second.
pub const MS_PER_WORD: u64 = 330;
/// The shortest saying time, for a line of a word or two.
pub const MIN_MS: u64 = 1_500;
/// The longest, for the longest lines.
pub const MAX_MS: u64 = 8_000;

/// About how long `text` takes to say aloud, in ms.
pub fn saying_ms(text: &str) -> u64 {
    (text.split_whitespace().count() as u64 * MS_PER_WORD).clamp(MIN_MS, MAX_MS)
}

#[cfg(test)]
mod tests {
    use super::saying_ms;

    #[test]
    fn a_line_takes_a_third_of_a_second_a_word_from_a_floor() {
        assert_eq!(saying_ms("Hi."), 1_500);
        assert_eq!(saying_ms("Good morning to you, how is the bread today?"), 9 * 330);
        assert_eq!(saying_ms(&"word ".repeat(40)), 8_000);
    }
}
