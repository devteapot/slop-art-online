#!/usr/bin/env python3
"""Self-test of the false-reply rule (living/tools/greet_report.py `reply_kind`, since
strangers-measures, docs/TRIALS.md): a false reply answers a line that names someone else; an
answered remark to the room that names no one is group talk; a line that names the answerer is
never false. No server.

Usage: python3 living/tools/greet_report_selftest.py [-v]
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import greet_report as G  # noqa: E402

NAMES = {1: "Edda Hollin", 2: "Ife Okoro", 3: "Lumi Pontil", 4: "Davin Vane", 5: "Lorcan Vane", 6: "Ingrid Morrow", 9: "Aldous Quill"}


class FalseReplies(unittest.TestCase):
    def test_a_line_naming_the_answerer_is_never_false(self):
        # st2b C: Edda's room line names Ife (and Lumi); Ife answers.
        text = "Lumi! I heard you — after lessons, first one to the heaps. And Ife, you're on my side, remember: we share the blue!"
        self.assertIsNone(G.reply_kind(text, 0, 1, 2, NAMES))
        # Named and also addressed to another by id: still never false.
        self.assertIsNone(G.reply_kind("Ife, tell Lumi to come.", 3, 1, 2, NAMES))
        # Addressed to the answerer by id.
        self.assertIsNone(G.reply_kind("Come here.", 2, 1, 2, NAMES))

    def test_a_room_remark_naming_no_one_is_group_talk(self):
        self.assertEqual(G.reply_kind("Crew! Benches now — lessons first, then the yard.", 0, 1, 2, NAMES), "group_talk")
        # The speaker naming itself is not naming someone else.
        self.assertEqual(G.reply_kind("I'm Edda, and I'm leading!", 0, 1, 2, NAMES), "group_talk")

    def test_a_line_naming_someone_else_is_false(self):
        # st2b L: Davin's line names Lorcan; Ingrid answers.
        self.assertEqual(G.reply_kind("Lorcan — I'll be at the Marver tonight. Say your word there and I'll hear it.", 0, 4, 6, NAMES), "false")
        # Addressed by id to another, no name said.
        self.assertEqual(G.reply_kind("Are you coming?", 5, 4, 6, NAMES), "false")

    def test_the_subject_is_counted_like_anyone(self):
        # Aldous (a trial's subject, a resident) answering a line that names Lorcan.
        self.assertEqual(G.reply_kind("Lorcan, the book is open.", 0, 4, 9, NAMES), "false")
        self.assertIsNone(G.reply_kind("Aldous, the book is open?", 0, 4, 9, NAMES))


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
