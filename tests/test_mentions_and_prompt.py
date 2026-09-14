import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.config import parse_timezones
from bot.mentions import Entity, strip_bot_triggers
from bot.prompt import build_system_prompt

BOT = "IQTimeDateSync_bot"
BOT_ID = 777


def strip(text, *entities):
    return strip_bot_triggers(text, entities, BOT, BOT_ID)


def entity(text, fragment, type_="mention"):
    """Сущность с UTF-16 смещением, как её присылает Telegram."""
    offset = len(text[: text.index(fragment)].encode("utf-16-le")) // 2
    return Entity(type_, offset, len(fragment.encode("utf-16-le")) // 2)


class TriggersTest(unittest.TestCase):
    def test_mention_at_end(self):
        text = "Встреча в четверг в 17 00 по алматы @IQTimeDateSync_bot"
        self.assertEqual(strip(text, entity(text, "@IQTimeDateSync_bot")), (True, "Встреча в четверг в 17 00 по алматы"))

    def test_mention_is_case_insensitive_and_after_emoji(self):
        text = "👋 @iqtimedatesync_BOT созвон в 15:00"
        self.assertEqual(strip(text, entity(text, "@iqtimedatesync_BOT")), (True, "👋 созвон в 15:00"))

    def test_only_mention(self):
        text = "@IQTimeDateSync_bot"
        self.assertEqual(strip(text, entity(text, text)), (True, ""))

    def test_command_in_the_middle_or_end(self):
        text = "Встреча в 12 00 завтра по бишкеку /time"
        self.assertEqual(strip(text, entity(text, "/time", "bot_command")), (True, "Встреча в 12 00 завтра по бишкеку"))
        text = "созвон /time@IQTimeDateSync_bot в 10 по мск"
        self.assertEqual(strip(text, entity(text, "/time@IQTimeDateSync_bot", "bot_command")), (True, "созвон в 10 по мск"))

    def test_foreign_command_or_mention_is_ignored(self):
        text = "в 15:00 /time@other_bot @alice /start"
        result = strip(
            text,
            entity(text, "/time@other_bot", "bot_command"),
            entity(text, "@alice"),
            entity(text, "/start", "bot_command"),
        )
        self.assertEqual(result, (False, text))

    def test_text_mention_by_id(self):
        text = "Бот, в пол десятого"
        self.assertEqual(strip(text, Entity("text_mention", 0, 3, BOT_ID)), (True, ", в пол десятого"))

    def test_plain_chat_message(self):
        text = "Коллеги, всем привет"
        self.assertEqual(strip(text), (False, text))


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
