import unittest
from datetime import datetime, timedelta, timezone

from material_search import Material, SearchReport, extract_material_topic, format_material_report, select_materials


class MaterialSearchTests(unittest.TestCase):
    def test_extracts_topic_from_natural_language_request(self):
        request = "Can you help me to get the materials about Neural Network?"

        self.assertEqual(extract_material_topic(request), "Neural Network")

    def test_extracts_topic_from_short_search_command(self):
        self.assertEqual(extract_material_topic("search Python tutorials"), "Python tutorials")

    def test_selects_five_unique_popular_and_recent_materials(self):
        materials = [
            Material(
                title=f"Resource {number}",
                url=f"https://example.com/{number}",
                source="Test",
                engagement_count=100 - number,
                engagement_label="views",
                published_at=datetime(2026, 1, number, tzinfo=timezone.utc),
            )
            for number in range(1, 13)
        ]

        popular, recent = select_materials(materials)

        self.assertEqual(len(popular), 5)
        self.assertEqual(len(recent), 5)
        self.assertTrue({item.url for item in popular}.isdisjoint(item.url for item in recent))
        self.assertEqual(popular[0].title, "Resource 1")
        self.assertEqual(recent[0].title, "Resource 12")

    def test_report_shows_urls_and_metric_disclaimer(self):
        material = Material(
            title="Example", url="https://example.com", source="Test", engagement_count=2,
            engagement_label="views", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        report = SearchReport("example", [material], [], ["Test"], [])

        output = format_material_report(report)

        self.assertIn("https://example.com", output)
        self.assertIn("do not provide one comparable visitor count", output)

    def test_excludes_future_dated_materials_from_results(self):
        future = Material(
            title="Future", url="https://example.com/future", source="Test", engagement_count=999,
            engagement_label="views", published_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        current = Material(
            title="Current", url="https://example.com/current", source="Test", engagement_count=1,
            engagement_label="views", published_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        popular, recent = select_materials([future, current])

        self.assertEqual(popular, [current])
        self.assertEqual(recent, [])


if __name__ == "__main__":
    unittest.main()
