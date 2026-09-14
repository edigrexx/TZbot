"""Пересчёт зон и форматирование с подменой ответа модели."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import parse_timezones
from bot.convert import convert, split_message
from bot.parsing import MAX_MEETINGS, UserFacingError, parse_model_output
from bot.service import resolve

ZONES = parse_timezones("Almaty:Asia/Almaty,MSK:Europe/Moscow,Bishkek:Asia/Bishkek,Vietnam:Asia/Ho_Chi_Minh")
ALMATY = ZoneInfo("Asia/Almaty")
MOSCOW = ZoneInfo("Europe/Moscow")
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
REF = datetime(2026, 9, 14, 10, 0, tzinfo=ALMATY)  # понедельник
NOW = REF


def meeting(date=None, time=None, tz=None, **extra):
    fields = {"title": None, "date": date, "time": time, "offset_minutes": None,
              "tz": tz, "tz_explicit": None, "approximate": None}
    fields.update(extra)
    return fields


def payload(*meetings):
    return {"meetings": list(meetings)}


def fake_model(response):
    """Подменяет OpenRouterExtractor: возвращает заранее заданный ответ и запоминает вызовы."""
    calls = []

    async def extract(text, ref):
        calls.append((text, ref))
        return response if isinstance(response, str) else json.dumps(response)

    extract.calls = calls
    return extract


def run_resolve(response, text="сообщение", ref=REF, now=NOW):
    extract = fake_model(response)
    result = asyncio.run(resolve(text, ref, ZONES, extract, now=now))
    return result, extract


def rows_by_label(moment):
    return {row.label: row for row in convert(moment, ZONES)}


class ConversionTest(unittest.TestCase):
    def test_moscow_late_evening_is_next_day_in_vietnam(self):
        result, extract = run_resolve(payload(meeting("2026-09-14", "23:30", "Europe/Moscow")), text="в 23:30 по мск")
        self.assertTrue(result.found)
        self.assertEqual(extract.calls, [("в 23:30 по мск", REF)])

        moment = datetime(2026, 9, 14, 23, 30, tzinfo=MOSCOW)
        rows = rows_by_label(moment)
        self.assertEqual(rows["MSK"].day_shift, 0)
        self.assertEqual(rows["Vietnam"].local.replace(tzinfo=None), datetime(2026, 9, 15, 3, 30))
        self.assertEqual(rows["Vietnam"].day_shift, 1)
        self.assertEqual(rows["Almaty"].local, moment.astimezone(ALMATY))

        self.assertIn("📅 <b>Понедельник, 14 сентября (сегодня), 23:30</b> (MSK)", result.reply)
        self.assertIn("03:30  UTC+7     +1 день, вт 15.09", result.reply)

    def test_vietnam_early_morning_is_previous_day_in_moscow(self):
        result, _ = run_resolve(payload(meeting("2026-09-15", "02:00", "Asia/Ho_Chi_Minh")))
        rows = rows_by_label(datetime(2026, 9, 15, 2, 0, tzinfo=VIETNAM))
        self.assertEqual(rows["MSK"].local.replace(tzinfo=None), datetime(2026, 9, 14, 22, 0))
        self.assertEqual(rows["MSK"].day_shift, -1)
        self.assertIn("Вторник, 15 сентября (завтра), 02:00", result.reply)
        self.assertIn("22:00  UTC+3     −1 день, пн 14.09", result.reply)

    def test_year_boundary(self):
        result, _ = run_resolve(payload(meeting("2026-12-31", "23:00", "Europe/Moscow")))
        rows = rows_by_label(datetime(2026, 12, 31, 23, 0, tzinfo=MOSCOW))
        self.assertEqual(rows["Vietnam"].local.replace(tzinfo=None), datetime(2027, 1, 1, 3, 0))
        self.assertIn("Четверг, 31 декабря, 23:00", result.reply)
        self.assertIn("пт 01.01", result.reply)

    def test_rows_sorted_by_utc_offset(self):
        rows = convert(datetime(2026, 9, 14, 12, 0, tzinfo=ALMATY), ZONES)
        offsets = [row.local.utcoffset() for row in rows]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(rows[0].label, "MSK")
        self.assertEqual(rows[-1].label, "Vietnam")

    def test_source_zone_outside_team(self):
        result, _ = run_resolve(payload(meeting("2026-09-14", "09:00", "Europe/London")))
        self.assertIn("(Europe/London)", result.reply)
        self.assertIn("11:00  UTC+3", result.reply)  # BST +1 → MSK +3

    def test_offset_minutes_computed_in_python(self):
        ref = datetime(2026, 9, 14, 23, 40, 27, tzinfo=ALMATY)
        raw = json.dumps(payload(meeting(tz="Asia/Almaty", offset_minutes=60, tz_explicit=False)))
        self.assertEqual(parse_model_output(raw, ref).meetings[0].moment, datetime(2026, 9, 15, 0, 40, tzinfo=ALMATY))

    def test_not_found(self):
        result, extract = run_resolve(payload(), text="ок, договорились")
        self.assertFalse(result.found)
        self.assertIsNone(result.reply)
        self.assertEqual(len(extract.calls), 1)

    def test_approximate_and_implicit_zone_notes(self):
        result, _ = run_resolve(payload(meeting("2026-09-15", "14:00", "Asia/Almaty", approximate=True, tz_explicit=False)))
        self.assertIn("приблизительно, взял 14:00", result.reply)
        self.assertIn("Пояс в сообщении не назван — считаю по Almaty", result.reply)

    def test_exact_time_has_no_notes(self):
        result, _ = run_resolve(payload(meeting("2026-09-15", "14:00", "Asia/Almaty", approximate=False, tz_explicit=True)))
        self.assertNotIn("приблизительно", result.reply)
        self.assertNotIn("не назван", result.reply)

    def test_year_shown_for_other_year_and_no_relative_label(self):
        result, _ = run_resolve(payload(meeting("2027-01-05", "10:00", "Asia/Almaty")))
        self.assertIn("Вторник, 5 января 2027, 10:00", result.reply)

    def test_title_in_header(self):
        result, _ = run_resolve(payload(
            meeting("2026-09-21", "12:00", "Europe/Moscow", title="P2P (Overpay) — демо технического ядра"),
        ))
        self.assertTrue(result.reply.startswith(
            "📅 <b>P2P (Overpay) — демо технического ядра</b>\nПонедельник, 21 сентября, 12:00 (MSK)\n<pre>"
        ))

    def test_title_is_escaped_and_normalized(self):
        long_title = "Созвон   <b>важный</b>\n" + "очень " * 30
        raw = json.dumps(payload(meeting("2026-09-15", "10:00", "Asia/Almaty", title=long_title)))
        title = parse_model_output(raw, REF).meetings[0].title
        self.assertLessEqual(len(title), 80)
        self.assertTrue(title.startswith("Созвон <b>важный</b> очень"))
        self.assertTrue(title.endswith("…"))

        result, _ = run_resolve(payload(meeting("2026-09-15", "10:00", "Asia/Almaty", title="<b>x</b> & y")))
        self.assertIn("📅 <b>&lt;b&gt;x&lt;/b&gt; &amp; y</b>", result.reply)

    def test_several_meetings_in_message_order(self):
        result, _ = run_resolve(payload(
            meeting("2026-09-17", "16:00", "Asia/Almaty", title="Ретро"),
            meeting("2026-09-15", "12:00", "Europe/Moscow", title="Демо P2P"),
        ))
        self.assertEqual(result.reply.count("<pre>"), 2)
        self.assertLess(result.reply.index("Ретро"), result.reply.index("Демо P2P"))
        self.assertIn("</pre>\n\n📅 <b>Демо P2P</b>", result.reply)

    def test_partial_errors_are_reported(self):
        result, _ = run_resolve(payload(
            meeting("2026-09-15", "12:00", "Europe/Moscow", title="Демо"),
            meeting("2026-09-16", "10:00", "Mars/Base", title="Ретро"),
        ))
        self.assertEqual(result.reply.count("<pre>"), 1)
        self.assertIn("⚠️ Не удалось разобрать:\n• «Ретро»: Не знаю часовой пояс «Mars/Base».", result.reply)

    def test_too_many_meetings(self):
        items = [meeting("2026-09-15", f"{9 + i:02d}:00", "Asia/Almaty", title=f"Встреча {i}") for i in range(MAX_MEETINGS + 2)]
        result, _ = run_resolve(payload(*items))
        self.assertEqual(result.reply.count("<pre>"), MAX_MEETINGS)
        self.assertIn("и ещё 2 встречи", result.reply)


class SplitMessageTest(unittest.TestCase):
    def test_short_message_is_one_chunk(self):
        self.assertEqual(split_message("a\n\nb"), ["a\n\nb"])

    def test_splits_on_block_boundaries(self):
        blocks = [f"блок {i} " + "x" * 90 for i in range(10)]
        chunks = split_message("\n\n".join(blocks), limit=250)
        self.assertTrue(all(len(chunk) <= 250 for chunk in chunks))
        self.assertEqual("\n\n".join(chunks), "\n\n".join(blocks))
        self.assertGreater(len(chunks), 1)


class ModelOutputValidationTest(unittest.TestCase):
    def assert_user_error(self, raw, fragment=""):
        with self.assertRaises(UserFacingError) as ctx:
            parse_model_output(raw if isinstance(raw, str) else json.dumps(raw), REF)
        self.assertIn(fragment, ctx.exception.message)

    def test_invalid_json(self):
        self.assert_user_error("Сейчас посчитаю: 15:00", "разобрать")

    def test_markdown_fence_tolerated(self):
        self.assertFalse(parse_model_output('```json\n{"meetings": []}\n```', REF).found)

    def test_wrong_shape(self):
        self.assert_user_error([1, 2], "формате")
        self.assert_user_error({"found": False}, "формате")
        self.assert_user_error({"meetings": "завтра"}, "формате")
        self.assert_user_error(payload("завтра в 10"), "формате")

    def test_unknown_timezone(self):
        self.assert_user_error(payload(meeting("2026-09-14", "10:00", "Asia/Almaaty")), "Asia/Almaaty")
        self.assert_user_error(payload(meeting("2026-09-14", "10:00", "MSK", title="Демо")), "«Демо»: Не знаю часовой пояс «MSK»")

    def test_missing_timezone(self):
        self.assert_user_error(payload(meeting("2026-09-14", "10:00")), "часовой пояс")

    def test_invalid_dates_and_times(self):
        self.assert_user_error(payload(meeting("2026-02-30", "10:00", "Asia/Almaty")), "не бывает")
        self.assert_user_error(payload(meeting("2026-09-14", "24:00", "Asia/Almaty")), "не бывает")
        self.assert_user_error(payload(meeting("2026-09-14", "9:30", "Asia/Almaty")), "время")
        self.assert_user_error(payload(meeting("14.09.2026", "10:00", "Asia/Almaty")), "дата")
        self.assert_user_error(payload(meeting(tz="Asia/Almaty")), "дата")

    def test_nonexistent_local_time_in_dst_gap(self):
        self.assert_user_error(payload(meeting("2026-03-29", "02:30", "Europe/Berlin")), "переводят часы")

    def test_bad_offset(self):
        for offset in (True, "60", int(timedelta(days=60).total_seconds() // 60)):
            with self.subTest(offset=offset):
                self.assert_user_error(payload(meeting(tz="Asia/Almaty", offset_minutes=offset)), "смещение")

    def test_null_flags_have_safe_defaults(self):
        parsed = parse_model_output(json.dumps(payload(meeting("2026-09-15", "09:30", "Asia/Almaty"))), REF).meetings[0]
        self.assertEqual(parsed.moment, datetime(2026, 9, 15, 9, 30, tzinfo=ALMATY))
        self.assertIsNone(parsed.title)
        self.assertFalse(parsed.approximate)
        self.assertTrue(parsed.tz_explicit)

    def test_model_error_propagates_from_resolve(self):
        with self.assertRaises(UserFacingError):
            run_resolve("not json")


if __name__ == "__main__":
    unittest.main()
