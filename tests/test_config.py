import unittest

from bot.config import (
    DEFAULT_FALLBACK_MODELS,
    DEFAULT_MODEL,
    ConfigError,
    load_config,
    parse_timezones,
    parse_user_timezones,
)

SPEC_TIMEZONES = "Almaty:Asia/Almaty,MSK:Europe/Moscow,Bishkek:Asia/Bishkek,Vietnam:Asia/Ho_Chi_Minh"


class ParseTimezonesTest(unittest.TestCase):
    def test_spec_example(self):
        zones = parse_timezones(SPEC_TIMEZONES)
        self.assertEqual([z.label for z in zones], ["Almaty", "MSK", "Bishkek", "Vietnam"])
        self.assertEqual(
            [z.tz.key for z in zones],
            ["Asia/Almaty", "Europe/Moscow", "Asia/Bishkek", "Asia/Ho_Chi_Minh"],
        )

    def test_whitespace_is_tolerated(self):
        zones = parse_timezones("  MSK : Europe/Moscow ,  Vietnam:Asia/Ho_Chi_Minh ")
        self.assertEqual([(z.label, z.tz.key) for z in zones],
                         [("MSK", "Europe/Moscow"), ("Vietnam", "Asia/Ho_Chi_Minh")])

    def test_invalid_values(self):
        cases = {
            "": "пуста",
            "   ": "пуста",
            "MSK:Europe/Moskva": "Europe/Moskva",
            "MSK=Europe/Moscow": "двоеточие",
            "MSK:Europe/Moscow:extra": "двоеточие",
            ":Europe/Moscow": "пустая метка",
            "MSK:": "не указана зона",
            "MSK:Europe/Moscow,": "пустой элемент",
            "MSK:Europe/Moscow,,Vietnam:Asia/Ho_Chi_Minh": "пустой элемент",
            "MSK:Europe/Moscow,msk:Asia/Almaty": "повторяется",
            "Local:localtime": "localtime",
        }
        for raw, fragment in cases.items():
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigError) as ctx:
                    parse_timezones(raw)
                self.assertIn(fragment, str(ctx.exception))


class ParseUserTimezonesTest(unittest.TestCase):
    def test_usernames_and_ids(self):
        mapping = parse_user_timezones("@Nguyen:Asia/Ho_Chi_Minh, 123456:Europe/Moscow")
        self.assertEqual(mapping["nguyen"].key, "Asia/Ho_Chi_Minh")
        self.assertEqual(mapping["123456"].key, "Europe/Moscow")

    def test_empty_is_allowed(self):
        self.assertEqual(parse_user_timezones(""), {})

    def test_unknown_zone(self):
        with self.assertRaises(ConfigError):
            parse_user_timezones("@nick:Mars/Olympus")


class LoadConfigTest(unittest.TestCase):
    ENV = {
        "BOT_TOKEN": "123:abc",
        "OPENROUTER_API_KEY": "sk-or-test",
        "TIMEZONES": SPEC_TIMEZONES,
        "DEFAULT_TZ": "Asia/Almaty",
    }

    def test_loads_with_defaults(self):
        config = load_config(self.ENV)
        self.assertEqual(config.default_tz.key, "Asia/Almaty")
        self.assertEqual(len(config.zones), 4)
        self.assertEqual(config.model, DEFAULT_MODEL)
        self.assertEqual(config.fallback_models, DEFAULT_FALLBACK_MODELS)
        self.assertIsNone(config.reasoning_effort)

    def test_missing_variables(self):
        for name in self.ENV:
            with self.subTest(name=name):
                env = dict(self.ENV, **{name: ""})
                with self.assertRaises(ConfigError) as ctx:
                    load_config(env)
                self.assertIn(name, str(ctx.exception))

    def test_bad_default_tz(self):
        with self.assertRaises(ConfigError):
            load_config(dict(self.ENV, DEFAULT_TZ="Asia/Almaaty"))

    def test_user_zone_lookup(self):
        config = load_config(dict(self.ENV, USER_TIMEZONES="@Nguyen:Asia/Ho_Chi_Minh,42:Europe/Moscow"))
        self.assertEqual(config.zone_for_user(1, "nguyen").key, "Asia/Ho_Chi_Minh")
        self.assertEqual(config.zone_for_user(42, None).key, "Europe/Moscow")
        self.assertEqual(config.zone_for_user(7, "someone").key, "Asia/Almaty")

    def test_fallback_models(self):
        config = load_config(dict(
            self.ENV,
            OPENROUTER_MODEL="openai/gpt-5.4-nano",
            OPENROUTER_FALLBACK_MODELS=" google/gemini-3.1-flash-lite, openai/gpt-5.4-nano,google/gemini-3.1-flash-lite ",
        ))
        self.assertEqual(config.model, "openai/gpt-5.4-nano")
        self.assertEqual(config.fallback_models, ("google/gemini-3.1-flash-lite",))

    def test_empty_fallback_disables(self):
        config = load_config(dict(self.ENV, OPENROUTER_FALLBACK_MODELS=""))
        self.assertEqual(config.fallback_models, ())

    def test_reasoning_effort(self):
        self.assertEqual(load_config(dict(self.ENV, OPENROUTER_REASONING_EFFORT="Minimal")).reasoning_effort, "minimal")
        with self.assertRaises(ConfigError):
            load_config(dict(self.ENV, OPENROUTER_REASONING_EFFORT="turbo"))


if __name__ == "__main__":
    unittest.main()
