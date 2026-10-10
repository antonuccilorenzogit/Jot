import unittest

from jot.utils.dedup_utils import local_macro_cleanup


class TestLocalMacroCleanupNearAdjacent(unittest.TestCase):
    """Tests for the near-adjacent deduplication thresholds in local_macro_cleanup.

    Threshold reference (dedup_utils.py):
      r >= 0.995 → removed_adj  (paragraph removed)
      r >= 0.975 → near_adj     (paragraph kept, counter incremented)
    Both paragraphs must be >= 100 chars in normalised form to trigger the check.
    """

    def test_ratio_above_995_removes_adjacent_paragraph(self):
        """Adjacent paragraphs with SequenceMatcher ratio >= 0.995 must be removed
        (removed_adj += 1) and excluded from the cleaned output.

        Ratio calculation: p1='a'*400, p2='a'*399+'b'
          M=399 matching chars, T=800 → ratio=2*399/800=0.9975 >= 0.995
        """
        p1 = "a" * 400
        p2 = "a" * 399 + "b"
        text = p1 + "\n\n" + p2

        cleaned, removed_exact, removed_adj, near_adj, total = local_macro_cleanup(text)

        self.assertEqual(removed_exact, 0)
        self.assertEqual(removed_adj, 1, "ratio 0.9975 must trigger removed_adj")
        self.assertEqual(near_adj, 0)
        self.assertEqual(total, 2)
        self.assertIn(p1, cleaned)
        self.assertNotIn(p2, cleaned)

    def test_ratio_975_to_995_keeps_paragraph_but_increments_near_adj(self):
        """Adjacent paragraphs with 0.975 <= ratio < 0.995 must be kept in output
        but increment near_adj (suspicious near-duplicate counter).

        Ratio calculation: p1='a'*200, p2='a'*197+'bbb'
          M=197 matching chars, T=400 → ratio=2*197/400=0.985 (0.975 <= 0.985 < 0.995)
        """
        p1 = "a" * 200
        p2 = "a" * 197 + "bbb"
        text = p1 + "\n\n" + p2

        cleaned, removed_exact, removed_adj, near_adj, total = local_macro_cleanup(text)

        self.assertEqual(removed_exact, 0)
        self.assertEqual(removed_adj, 0, "ratio 0.985 must NOT remove the paragraph")
        self.assertEqual(near_adj, 1, "ratio 0.985 must increment near_adj")
        self.assertEqual(total, 2)
        self.assertIn(p1, cleaned)
        self.assertIn(p2, cleaned)

    def test_ratio_below_975_has_no_dedup_effect(self):
        """Adjacent paragraphs with ratio < 0.975 must pass through unchanged."""
        p1 = "a" * 100
        p2 = "b" * 100
        text = p1 + "\n\n" + p2

        cleaned, removed_exact, removed_adj, near_adj, total = local_macro_cleanup(text)

        self.assertEqual(removed_exact, 0)
        self.assertEqual(removed_adj, 0)
        self.assertEqual(near_adj, 0)
        self.assertEqual(total, 2)
        self.assertIn(p1, cleaned)
        self.assertIn(p2, cleaned)

    def test_exact_duplicate_uses_removed_exact_not_removed_adj(self):
        """Exact duplicates (same normalised form) must increment removed_exact,
        not removed_adj, because the seen-set check fires before the ratio check."""
        p = "q" * 80
        text = p + "\n\n" + p

        cleaned, removed_exact, removed_adj, _near_adj, total = local_macro_cleanup(
            text
        )

        self.assertEqual(removed_exact, 1)
        self.assertEqual(removed_adj, 0)
        self.assertEqual(total, 2)
        self.assertIn(p, cleaned)

    def test_short_paragraphs_skip_ratio_check(self):
        """Paragraphs shorter than 100 normalised chars must skip the ratio check
        entirely, so near_adj stays 0 even for near-identical short text."""
        p1 = "a" * 99
        p2 = "a" * 98 + "b"
        text = p1 + "\n\n" + p2

        cleaned, _removed_exact, removed_adj, near_adj, _total = local_macro_cleanup(
            text
        )

        self.assertEqual(removed_adj, 0)
        self.assertEqual(near_adj, 0)
        self.assertIn(p1, cleaned)
        self.assertIn(p2, cleaned)

    def test_empty_or_whitespace_input(self):
        self.assertEqual(local_macro_cleanup(""), ("", 0, 0, 0, 0))
        self.assertEqual(local_macro_cleanup("   \n\n  "), ("", 0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
