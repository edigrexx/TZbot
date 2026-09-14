"""Пересчёт зон с подменой ответа модели."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import parse_timezones
from bot.convert import convert
from bot.parsing import UserFacingError, parse_model_output
from bot.service import resolve

ZONES = parse_timezones("Almaty:Asia/Almaty,MSK:Europe/Moscow,Bishkek:Asia/Bishkek,Vietnam:Asia/Ho_Chi_Minh")
ALMATY = ZoneInfo("Asia/Almaty")
MOSCOW = ZoneInfo("Europe/Moscow")
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
REF = datetime(2026, 9, 14, 10, 0, tzinfo=ALMATY)  # понедельник


def fake_model(payload):
    """Подменяет ClaudeExtractor: возвращает заранее заданный ответ и запоминает вызовы."""
    calls = []

    async def extract(text, ref):
        calls.append((text, ref))
        return payload if isinstance(payload, str) else json.dumps(payload)

    extract.calls = calls
    return extract


def run_resolve(payload, text="сообщение", ref=REF):
    extract = fake_model(payload)
    result = asyncio.run(resolve(text, ref, ZONES, extract))
    return result, extract


def found(date, time, tz, **extra):
    return dict({"found": True, "date": date, "time": time, "tz": tz}, **extra)


def rows_by_label(moment):
    return {row.label: row for row in convert(moment, ZONES)}


class ConversionTest(unittest.TestCase):
    def test_moscow_late_evening_is_next_day_in_vietnam(self):
        result, extract = run_resolve(found("2026-09-14", "23:30", "Europe/Moscow"), text="в 23:30 по мск")
        self.assertTrue(result.found)
        self.assertEqual(extract.calls, [("в 23:30 по мск", REF)])

        moment = parse_model_output(json.dumps(found("2026-09-14", "23:30", "Europe/Moscow")), REF).moment
        rows = rows_by_label(moment)
        self.assertEqual(rows["MSK"].local, datetime(2026, 9, 14, 23, 30, tzinfo=MOSCOW))
        self.assertEqual(rows["MSK"].day_shift, 0)
        self.assertEqual(rows["Vietnam"].local.replace(tzinfo=None), datetime(2026, 9, 15, 3, 30))
        self.assertEqual(rows["Vietnam"].day_shift, 1)
        self.assertEqual(rows["Almaty"].local, moment.astimezone(ALMATY))

        self.assertIn("📅 <b>Понедельник, 14 сентября, 23:30</b> (MSK)", result.reply)
        self.assertIn("03:30  UTC+7     +1 день, вт 15.09", result.reply)

    def test_vietnam_early_morning_is_previous_day_in_moscow(self):
        result, _ = run_resolve(found("2026-09-15", "02:00", "Asia/Ho_Chi_Minh"))
        moment = datetime(2026, 9, 15, 2, 0, tzinfo=VIETNAM)
        rows = rows_by_label(moment)
        self.assertEqual(rows["MSK"].local.replace(tzinfo=None), datetime(2026, 9, 14, 22, 0))
        self.assertEqual(rows["MSK"].day_shift, -1)
        self.assertEqual(rows["Vietnam"].day_shift, 0)
        self.assertIn("22:00  UTC+3     −1 день, пн 14.09", result.reply)

    def test_year_boundary(self):
        result, _ = run_resolve(found("2026-12-31", "23:00", "Europe/Moscow"))
        rows = rows_by_label(datetime(2026, 12, 31, 23, 0, tzinfo=MOSCOW))
        self.assertEqual(rows["Vietnam"].local.replace(tzinfo=None), datetime(2027, 1, 1, 3, 0))
        self.assertEqual(rows["Vietnam"].day_shift, 1)
        self.assertIn("пт 01.01", result.reply)

    def test_rows_sorted_by_utc_offset(self):
        rows = convert(datetime(2026, 9, 14, 12, 0, tzinfo=ALMATY), ZONES)
        offsets = [row.local.utcoffset() for row in rows]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(rows[0].label, "MSK")
        self.assertEqual(rows[-1].label, "Vietnam")

    def test_source_zone_outside_team(self):
        result, _ = run_resolve(found("2026-09-14", "09:00", "Europe/London"))
        self.assertIn("(Europe/London)", result.reply)
        self.assertIn("11:00  UTC+3", result.reply)  # BST +1 → MSK +3

    def test_offset_minutes_computed_in_python(self):
        ref = datetime(2026, 9, 14, 23, 40, 27, tzinfo=ALMATY)
        payload = {"found": True, "offset_minutes": 60, "tz": "Asia/Almaty", "tz_explicit": False}
        extraction = parse_model_output(json.dumps(payload), ref)
        self.assertEqual(extraction.moment, datetime(2026, 9, 15, 0, 40, tzinfo=ALMATY))

    def test_not_found(self):
        result, extract = run_resolve({"found": False}, text="ок, договорились")
        self.assertFalse(result.found)
        self.assertIsNone(result.reply)
        self.assertEqual(len(extract.calls), 1)

    def test_approximate_and_implicit_zone_notes(self):
        result, _ = run_resolve(
            found("2026-09-15", "14:00", "Asia/Almaty", approximate=True, tz_explicit=False)
        )
        self.assertIn("приблизительно, взял 14:00", result.reply)
        self.assertIn("Пояс в сообщении не назван — считаю по Almaty", result.reply)

    def test_exact_time_has_no_notes(self):
        result, _ = run_resolve(found("2026-09-15", "14:00", "Asia/Almaty", approximate=False, tz_explicit=True))
        self.assertNotIn("приблизительно", result.reply)
        self.assertNotIn("не назван", result.reply)

    def test_year_shown_for_other_year(self):
        result, _ = run_resolve(found("2027-01-05", "10:00", "Asia/Almaty"))
        self.assertIn("Вторник, 5 января 2027", result.reply)


class ModelOutputValidationTest(unittest.TestCase):
    def assert_user_error(self, raw, fragment=""):
        with self.assertRaises(UserFacingError) as ctx:
            parse_model_output(raw if isinstance(raw, str) else json.dumps(raw), REF)
        self.assertIn(fragment, ctx.exception.message)

    def test_invalid_json(self):
        self.assert_user_error("Сейчас посчитаю: 15:00", "разобрать")

    def test_markdown_fence_tolerated(self):
        extraction = parse_model_output('```json\n{"found": false}\n```', REF)
        self.assertFalse(extraction.found)

    def test_wrong_shape(self):
        self.assert_user_error([1, 2])
        self.assert_user_error({"date": "2026-09-14"})
        self.assert_user_error({"found": "yes"})

    def test_unknown_timezone(self):
        self.assert_user_error(found("2026-09-14", "10:00", "Asia/Almaaty"), "Asia/Almaaty")
        self.assert_user_error(found("2026-09-14", "10:00", "MSK"), "MSK")

    def test_missing_timezone(self):
        self.assert_user_error({"found": True, "date": "2026-09-14", "time": "10:00"}, "часовой пояс")

    def test_invalid_dates_and_times(self):
        self.assert_user_error(found("2026-02-30", "10:00", "Asia/Almaty"), "не бывает")
        self.assert_user_error(found("2026-09-14", "24:00", "Asia/Almaty"), "не бывает")
        self.assert_user_error(found("2026-09-14", "9:30", "Asia/Almaty"), "время")
        self.assert_user_error(found("14.09.2026", "10:00", "Asia/Almaty"), "дата")
        self.assert_user_error({"found": True, "tz": "Asia/Almaty"}, "дата")

    def test_nonexistent_local_time_in_dst_gap(self):
        self.assert_user_error(found("2026-03-29", "02:30", "Europe/Berlin"), "переводят часы")

    def test_bad_offset(self):
        self.assert_user_error({"found": True, "offset_minutes": True, "tz": "Asia/Almaty"}, "смещение")
        self.assert_user_error({"found": True, "offset_minutes": "60", "tz": "Asia/Almaty"}, "смещение")
        self.assert_user_error(
            {"found": True, "offset_minutes": int(timedelta(days=60).total_seconds() // 60), "tz": "Asia/Almaty"},
            "смещение",
        )

    def test_model_error_propagates_from_resolve(self):
        with self.assertRaises(UserFacingError):
            run_resolve("not json")


if __name__ == "__main__":
    unittest.main()
