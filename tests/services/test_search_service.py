"""Unit tests for jot.services.search_service."""

from jot.services.search_service import (
    count_matches,
    extract_text_from_html,
    find_snippets,
)


class TestExtractTextFromHtml:
    def test_simple_paragraph(self):
        html = "<p>Ciao mondo</p>"
        assert "Ciao mondo" in extract_text_from_html(html)

    def test_strips_tags(self):
        html = "<h1>Titolo</h1><p>Contenuto <b>in grassetto</b>.</p>"
        text = extract_text_from_html(html)
        assert "Titolo" in text
        assert "Contenuto" in text
        assert "in grassetto" in text
        assert "<" not in text

    def test_collapses_whitespace(self):
        html = "<p>  testo   con   spazi  </p>"
        text = extract_text_from_html(html)
        assert "  " not in text

    def test_empty_html(self):
        assert extract_text_from_html("") == ""

    def test_html_entities_decoded(self):
        html = "<p>uno &amp; due</p>"
        text = extract_text_from_html(html)
        assert "&" in text
        assert "&amp;" not in text

    def test_nested_tags(self):
        html = "<div><ul><li><em>Krebs</em></li></ul></div>"
        text = extract_text_from_html(html)
        assert "Krebs" in text


class TestFindSnippets:
    def test_single_match(self):
        text = "La prima legge di Ohm dice che."
        snippets, total = find_snippets(text, "Ohm")
        assert len(snippets) == 1
        assert snippets[0]["match"] == "Ohm"
        assert total == 1

    def test_case_insensitive(self):
        text = "ciclo di KREBS è importante."
        snippets, _ = find_snippets(text, "krebs")
        assert len(snippets) == 1
        assert "KREBS" in snippets[0]["match"]

    def test_multiple_matches_capped(self):
        text = " ".join(["alfa" for _ in range(10)])
        snippets, total = find_snippets(text, "alfa", max_snippets=3)
        assert len(snippets) == 3
        assert total == 10

    def test_no_match_returns_empty(self):
        text = "nessuna corrispondenza qui"
        snippets, total = find_snippets(text, "xyz")
        assert snippets == []
        assert total == 0

    def test_empty_query_returns_empty(self):
        snippets, total = find_snippets("qualcosa", "")
        assert snippets == []
        assert total == 0

    def test_empty_text_returns_empty(self):
        snippets, total = find_snippets("", "krebs")
        assert snippets == []
        assert total == 0

    def test_before_after_context(self):
        text = "la " + "x " * 50 + "parola cercata " + "y " * 50 + "fine"
        snippets, _ = find_snippets(text, "parola cercata", context_chars=30)
        assert snippets[0]["before"] != ""
        assert snippets[0]["after"] != ""

    def test_match_at_start(self):
        text = "Krebs cycle starts here and continues."
        snippets, _ = find_snippets(text, "Krebs")
        assert snippets[0]["before"] == ""
        assert "cycle" in snippets[0]["after"]

    def test_match_at_end(self):
        text = "This is the end Krebs"
        snippets, _ = find_snippets(text, "Krebs")
        assert snippets[0]["after"] == ""

    def test_snippet_dict_keys(self):
        snippets, _ = find_snippets("test query here", "query")
        assert set(snippets[0].keys()) == {"before", "match", "after"}


class TestCountMatches:
    def test_single_occurrence(self):
        assert count_matches("alfa beta alfa", "beta") == 1

    def test_multiple_occurrences_exceeds_snippet_cap(self):
        text = " ".join(["alfa"] * 10)
        assert count_matches(text, "alfa") == 10

    def test_case_insensitive(self):
        assert count_matches("Krebs krebs KREBS", "krebs") == 3

    def test_no_match(self):
        assert count_matches("nessuna corrispondenza", "xyz") == 0

    def test_empty_query(self):
        assert count_matches("testo", "") == 0

    def test_empty_text(self):
        assert count_matches("", "query") == 0
