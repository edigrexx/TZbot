import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.config import parse_timezones
from bot.mentions import Entity, strip_bot_mentions
from bot.prompt import build_system_prompt

BOT_ID = 777


class MentionsTest(unittest.TestCase):
    def test_mention_after_emoji_uses_utf16_offsets(self):
        text = "👋 @TZ_Bot созвон в 15:00"  # эмодзи = 2 единицы UTF-16
        mentioned, cleaned = strip_bot_mentions(text, [Entity("mention", 3, 7)], "tz_bot", BOT_ID)
        self.assertTrue(mentioned)
        self.assertEqual(cleaned, "👋 созвон в 15:00")

    def test_other_user_mention_is_kept(self):
        text = "@alice созвон в 15:00"
        mentioned, cleaned = strip_bot_mentions(text, [Entity("mention", 0, 6)], "tz_bot", BOT_ID)
        self.assertFalse(mentioned)
        self.assertEqual(cleaned, text)

    def test_text_mention_by_id(self):
        text = "Бот, в пол десятого"
        mentioned, cleaned = strip_bot_mentions(text, [Entity("text_mention", 0, 3, BOT_ID)], "tz_bot", BOT_ID)
        self.assertTrue(mentioned)
        self.assertEqual(cleaned, ", в пол десятого")

    def test_only_mention(self):
        mentioned, cleaned = strip_bot_mentions("@tz_bot", [Entity("mention", 0, 7)], "tz_bot", BOT_ID)
        self.assertTrue(mentioned)
        self.assertEqual(cleaned, "")


class PromptTest(unittest.TestCase):
    def test_contains_reference_calendar_and_zones(self):
        zones = parse_timezones("Almaty:Asia/Almaty,MSK:Europe/Moscow")
        ref = datetime(2026, 9, 14, 23, 50, tzinfo=ZoneInfo("Asia/Almaty"))
        prompt = build_system_prompt(ref, zones)
        self.assertIn("Сообщение написано: 2026-09-14 23:50, понедельник, зона автора Asia/Almaty (UTC+5)", prompt)
        self.assertIn("- 2026-09-15, вторник (завтра)", prompt)
        self.assertIn("- 2026-09-21, понедельник", prompt)
        self.assertIn("- MSK → Europe/Moscow", prompt)
        self.assertIn("НЕ нужно", prompt)


if __name__ == "__main__":
    unittest.main()
