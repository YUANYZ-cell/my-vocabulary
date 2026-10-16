import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


class DictionaryParserTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_youdao_translation_dictionary_keeps_pos_and_both_accents(self):
        value = self.parse("""有道翻译
检测到英语 - 中文
grave
术语库
英 /ɡreɪv/ 美 /ɡreɪv/
查看全部
n. 坟墓，墓穴；死亡，终结
adj. 严峻的，严重的；严肃的，庄重的
adv. （用作演奏演唱指示）缓慢地，庄严地
v. <文>铭记，铭刻；<古>刻（铭文、图像）
【名】（Grave）（德、英）格拉维（人名）
CET4/CET6/考研/GRE
来自有道词典结果""")
        self.assertEqual("grave", value["term"])
        self.assertEqual("英 /ɡreɪv/ · 美 /ɡreɪv/", value["phonetic"])
        self.assertEqual("noun; adjective; adverb; verb", value["part_of_speech"])
        self.assertEqual("有道词典", value["detected_format"])
        for meaning in ("n. 坟墓", "adj. 严峻", "adv. （用作", "v. <文>铭记", "【名】"):
            self.assertIn(meaning, value["chinese_meaning"])
        for noise in ("有道", "查看全部", "术语库", "ɡreɪv", "CET4", "检测到"):
            self.assertNotIn(noise, value["chinese_meaning"])
        self.assertEqual("", value["english_definition"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_youdao_split_pos_and_bracketed_accents(self):
        value = self.parse("""record
英
[ˈrekɔːd]
美 [ˈrekərd]
n.
记录；唱片
vt.
记录，记载
vi.
录音""")
        self.assertEqual("英 /ˈrekɔːd/ · 美 /ˈrekərd/", value["phonetic"])
        self.assertEqual("noun; verb", value["part_of_speech"])
        self.assertIn("n. 记录；唱片", value["chinese_meaning"])
        self.assertIn("vt. 记录，记载", value["chinese_meaning"])
        self.assertEqual("有道词典", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_youdao_flat_copy_and_truncation_warning(self):
        value = self.parse("grave 英 /ɡreɪv/ 美 /ɡreɪv/ n. 坟墓，墓穴 adj. 严峻的，严重的 v. 铭刻…")
        self.assertEqual("grave", value["term"])
        self.assertEqual("noun; adjective; verb", value["part_of_speech"])
        self.assertIn("adj. 严峻的", value["chinese_meaning"])
        self.assertIn("截断", value["warnings"])
        self.assertIn("查看全部", value["warnings"])

    def parse(self, sample):
        script = f"""
import {{parseDictionaryText}} from {json.dumps((ROOT / 'app' / 'dictionary-parser.js').as_uri())};
console.log(JSON.stringify(parseDictionaryText({json.dumps(sample)})));
"""
        result = subprocess.run(
            [NODE, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(result.stdout)

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_dictionary_text_is_parsed_without_links(self):
        sample = """dip

/dip/

*verb*

verb: **dip**; 3rd person present: **dips**; past tense: **dipped**

1. 1\\.

put or let something down quickly or briefly in or into (liquid).

\"he dipped a brush in the paint\"

Similar:

**immerse**

2. 2\\.

put a hand or tool into (a bag or container) in order to take something out.
"""
        script = f"""
import {{parseDictionaryText}} from {json.dumps((ROOT / 'app' / 'dictionary-parser.js').as_uri())};
const value = parseDictionaryText({json.dumps(sample)});
if (value.term !== 'dip' || value.phonetic !== '/dip/' || value.part_of_speech !== 'verb') process.exit(2);
if (!value.english_definition.includes('put a hand or tool') || value.english_definition.includes('immerse')) process.exit(3);
if (!value.source_sentence.includes('he dipped a brush') || !value.notes.includes('Similar:')) process.exit(4);
if (!value.synonyms.includes('immerse') || value.item_type !== 'word') process.exit(5);
"""
        subprocess.run([NODE, "--input-type=module", "-e", script], check=True)

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_dictionary_syllabified_headword_uses_canonical_word(self):
        sample = """a·rith·me·tic
noun
noun: arithmetic
/əˈriTHməˌtik/
the branch of mathematics dealing with the properties and manipulation of numbers.
\"the laws of arithmetic\""""
        value = self.parse(sample)
        self.assertEqual("arithmetic", value["term"])
        self.assertEqual("noun", value["part_of_speech"])
        self.assertEqual("/əˈriTHməˌtik/", value["phonetic"])
        self.assertIn("the branch of mathematics", value["english_definition"])
        self.assertIn("the laws of arithmetic", value["source_sentence"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_parser_keeps_short_phrases_separate_from_long_sentence_patterns(self):
        short = self.parse("""peal of laughter
一阵笑声""")
        long = self.parse("""The figure saw a gradual decline over the period.
该数据在这一时期逐渐下降。""")
        self.assertEqual(short["item_type"], "phrase")
        self.assertEqual(long["item_type"], "sentence")

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_dictionary_dishearten_copy_keeps_headword_and_related_words(self):
        sample = """dis·heart·en
/disˈhärt(ə)n/
verb
past tense: disheartened; past participle: disheartened
cause (someone) to lose determination or confidence.
Similar:
discourage, dispirit, demoralize, depress, dismay, daunt"""
        value = self.parse(sample)
        self.assertEqual("dishearten", value["term"])
        self.assertEqual("/disˈhärt(ə)n/", value["phonetic"])
        self.assertEqual("verb", value["part_of_speech"])
        self.assertEqual(
            "cause (someone) to lose determination or confidence.",
            value["english_definition"],
        )
        self.assertEqual(
            ["discourage", "dispirit", "demoralize", "depress", "dismay", "daunt"],
            value["synonyms"],
        )

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_dictionary_pronunciation_button_does_not_enter_definitions(self):
        sample = """cum·ber·some
/ˈkəmbərsəm/
Learn to pronounce
adjective
Learn to pronounce · large or heavy and therefore difficult to carry or use; unwieldy.
\"cumbersome diving suits\"
Similar:
unwieldy, unmanageable
Learn to pronounce · slow or complicated and therefore inefficient.
\"organizations with cumbersome hierarchical structures\""""
        value = self.parse(sample)
        self.assertEqual("cumbersome", value["term"])
        self.assertEqual("adjective", value["part_of_speech"])
        self.assertEqual(
            "large or heavy and therefore difficult to carry or use; unwieldy.\n"
            "slow or complicated and therefore inefficient.",
            value["english_definition"],
        )
        self.assertNotIn("Learn to pronounce", value["notes"])
        self.assertEqual("", value["chinese_meaning"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_pronunciation_phrase_inside_real_definition_is_preserved(self):
        value = self.parse("articulate\nverb\nlearn to pronounce words clearly and accurately.")
        self.assertEqual(
            "learn to pronounce words clearly and accurately.",
            value["english_definition"],
        )

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_ai_headword_variants_do_not_use_definition_sentence_as_term(self):
        samples = (
            (
                """re·sil·ient
adjective
/rəˈzilyənt/
able to withstand or recover quickly from difficult conditions.""",
                "resilient",
            ),
            (
                """The word \"meticulous\" means showing great attention to detail.
It is an adjective used for someone who is very careful and precise.""",
                "meticulous",
            ),
            (
                """## What does \"pragmatic\" mean?
Pragmatic means dealing with problems in a practical way rather than relying on theory.""",
                "pragmatic",
            ),
            (
                """**Ubiquitous** means present, appearing, or found everywhere.
It is commonly used as an adjective.""",
                "ubiquitous",
            ),
            (
                """The phrase \"come across\" means to find or meet something by chance.
It is a common phrasal verb in everyday English.""",
                "come across",
            ),
            (
                """Arithmetic is the branch of mathematics concerned with numbers and calculation.
It includes addition, subtraction, multiplication, and division.""",
                "arithmetic",
            ),
            (
                """What is the meaning of \"lucid\"?
Lucid means expressed clearly and easy to understand.""",
                "lucid",
            ),
        )
        for sample, expected_term in samples:
            with self.subTest(expected_term=expected_term):
                value = self.parse(sample)
                self.assertEqual(expected_term, value["term"])
                self.assertLessEqual(len(value["term"].split()), 3)

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_ai_markdown_entry_identifies_word_and_meaning_sections(self):
        sample = """**resort**

/rəˈzôrt/

A **resort** is **a place people visit for vacation, relaxation, or recreation**, or an action you take when you turn to something for help or when no other options are left. [[1](https://example.com/one), [2](https://example.com/two)]

The word has two main uses as a noun and a verb:

**As a Noun (A Place)**

- **Holiday destination:** A self-contained establishment or town providing lodging, food, entertainment, and sports (e.g., a **ski resort** or beach resort).
- **Recourse or refuge:** A person or thing turned to for safety, aid, or support in a difficult situation (e.g., *a court of last resort*).

**As a Verb (To Resort To)**

- **Turning to an option:** Doing something—often undesirable—because you have no other way to reach a goal (e.g., *resorting to violence*).
- **Habitual visiting:** Going to a particular place often or regularly.
"""
        value = self.parse(sample)
        self.assertEqual("resort", value["term"])
        self.assertEqual("/rəˈzôrt/", value["phonetic"])
        self.assertEqual("noun; verb", value["part_of_speech"])
        self.assertIn("Holiday destination", value["english_definition"])
        self.assertIn("Turning to an option", value["english_definition"])
        self.assertNotIn("The word has two main uses", value["english_definition"])
        self.assertNotIn("[1", value["english_definition"])
        self.assertEqual("AI / Markdown 词条", value["detected_format"])
        self.assertIn("未检测到中文释义", value["warnings"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_ai_charming_intro_does_not_become_a_phrase(self):
        sample = (ROOT / "tests" / "fixtures" / "google-ai-charming.md").read_text(encoding="utf-8")
        # Plain-text clipboard content has no Markdown or citation links.
        plain = """charming
/ˈCHärmiNG/
Charming is an adjective that means extremely pleasing, delightful, or attractive.
Key Meanings & Usage
• Pleasing and Attractive: Used to describe people, places, or things that capture attention or make people feel happy (e.g., a charming village, a charming smile).
• Disapproving or Ironic: Sometimes used negatively to describe someone who uses superficial attractiveness to manipulate others, or used sarcastically as an exclamation ("Charming!") to show disapproval of rude behavior.
• Magical (Rare): Historically or literally relates to casting a spell or possessing supernatural charm."""
        for raw in (sample, plain):
            with self.subTest(markdown=raw == sample):
                value = self.parse(raw)
                self.assertEqual("charming", value["term"])
                self.assertEqual("word", value["item_type"])
                self.assertEqual("adjective", value["part_of_speech"])
                self.assertEqual("/ˈCHärmiNG/", value["phonetic"])
                self.assertEqual(4, value["definition_count"])
                for text in ("extremely pleasing", "Pleasing and Attractive:",
                             "Disapproving or Ironic:", "Magical (Rare):"):
                    self.assertIn(text, value["english_definition"])
                self.assertEqual("", value["chinese_meaning"])
                self.assertIn("未检测到中文释义", value["warnings"])
                self.assertNotIn("https://", value["notes"])
                self.assertNotIn("[1", value["english_definition"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_narrative_part_of_speech_intro_without_a_separate_headword(self):
        samples = (
            ("Charming is an adjective that means extremely pleasing, delightful, or attractive.",
             "charming", "adjective", "word"),
            ("charming is an adjective meaning very pleasant or attractive.",
             "charming", "adjective", "word"),
            ('The word "charming" is an adjective that means extremely pleasing, delightful, or attractive.',
             "charming", "adjective", "word"),
            ('"Come across" is a phrasal verb that means to find or meet something by chance.',
             "come across", "phrasal verb", "phrase"),
            ("Resort is a noun that means a place people visit for vacation, relaxation, or recreation, especially one offering accommodation and entertainment.",
             "resort", "noun", "word"),
            ("Immerse is a verb that means to put someone or something completely into a liquid, or to involve them deeply in a particular activity.",
             "immerse", "verb", "word"),
        )
        for sample, term, part, item_type in samples:
            with self.subTest(sample=sample):
                value = self.parse(sample)
                self.assertEqual(term, value["term"])
                self.assertEqual(part, value["part_of_speech"])
                self.assertEqual(item_type, value["item_type"])
                self.assertEqual(1, value["definition_count"])
                self.assertEqual("", value["chinese_meaning"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_ai_overview_keeps_dip_senses_without_headings_or_prompt(self):
        sample = """**dip**

/dip/

The word **dip** has multiple meanings depending on the context, most commonly referring to a dipping sauce for food, a physical action of submerging something, or a type of smokeless tobacco.

**Food and Cooking**

- **Dipping Sauce:** A thick, creamy or liquid condiment into which food is partially immersed before eating.
- **The Action:** Briefly placing an item into a liquid, such as dipping a strawberry into chocolate.

**Movement and Physical States**

- **Downward Motion:** To sink or drop down briefly.
- **Exercise:** A body-weight strength exercise performed on parallel bars.

**Other Meanings**

- **Tobacco:** A moist, finely ground smokeless tobacco product.
- **Slang:** To leave a place quickly.

If you had a specific context in mind, tell me which definition you want to explore."""
        value = self.parse(sample)
        definitions = value["english_definition"].splitlines()
        self.assertEqual("dip", value["term"])
        self.assertEqual("/dip/", value["phonetic"])
        self.assertEqual("", value["chinese_meaning"])
        self.assertEqual(6, value["definition_count"])
        self.assertIn("Food and Cooking · Dipping Sauce:", definitions[0])
        self.assertIn("Movement and Physical States · Downward Motion:", value["english_definition"])
        self.assertIn("Other Meanings · Slang:", value["english_definition"])
        self.assertNotIn("Food and Cooking\n", value["english_definition"])
        self.assertNotIn("The word dip has", value["english_definition"])
        self.assertNotIn("If you had", value["english_definition"])
        self.assertIn("未检测到中文释义", value["warnings"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_flattened_google_ai_copy_from_screenshot_is_recovered(self):
        sample = """dip/dip/The word dip has multiple meanings depending on the context, most commonly referring to a dipping sauce for food, a physical action of submerging something, or a type of smokeless tobacco. [1] (https://en.wikipedia.org/wiki/Dipping_tobacco), [2] (https://www.youtube.com/watch?v=vj23lh5QEmE&t=20), [3] (https://en.wikipedia.org/wiki/Dipping_sauce)Food and CookingDipping Sauce: A thick, creamy or liquid condiment into which food is partially immersed before eating.The Action: Briefly placing an item into a liquid, such as dipping a strawberry into chocolate.Movement and Physical StatesDownward Motion: To sink or drop down briefly.Exercise: A body-weight strength exercise performed on parallel bars.Other MeaningsTobacco: A moist, finely ground smokeless tobacco product.Slang: To leave a place quickly."""
        value = self.parse(sample)
        self.assertEqual("dip", value["term"])
        self.assertEqual("/dip/", value["phonetic"])
        self.assertGreaterEqual(value["definition_count"], 6)
        self.assertIn("Dipping Sauce:", value["english_definition"])
        self.assertIn("Downward Motion:", value["english_definition"])
        self.assertNotIn("wikipedia.org", value["english_definition"])
        self.assertNotIn("https://", value["notes"])
        self.assertEqual("AI / Markdown 词条", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_single_line_bilingual_copy_finds_term_phonetic_and_chinese(self):
        sample = "resort /rɪˈzɔːrt/ noun 度假胜地；旅游胜地"
        value = self.parse(sample)
        self.assertEqual("resort", value["term"])
        self.assertEqual("/rɪˈzɔːrt/", value["phonetic"])
        self.assertEqual("noun", value["part_of_speech"])
        self.assertEqual("度假胜地；旅游胜地", value["chinese_meaning"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_cambridge_copy_can_find_term_after_page_heading(self):
        sample = """Meaning of resort in English

resort
noun
uk
/rɪˈzɔːt/
us
/rɪˈzɔːrt/

resort noun (PLACE)
B1 [ C ]
a place where many people go for rest, sport, or another stated purpose:

tourist resort Even the busiest tourist resort can be quiet over the winter.

resort noun (ACTION)
[ U ]
the fact that you have to do something because there is no other way of achieving something:
"""
        value = self.parse(sample)
        self.assertEqual("resort", value["term"])
        self.assertEqual("noun", value["part_of_speech"])
        self.assertIn("/rɪˈzɔːt/", value["phonetic"])
        self.assertIn("a place where many people go", value["english_definition"])
        self.assertIn("the fact that you have to do something", value["english_definition"])
        self.assertEqual("Cambridge Dictionary", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_current_cambridge_copy_ignores_ui_noise_and_keeps_example(self):
        sample = """Meaning of dip in English

dip
verb
uk
Your browser doesn't support HTML5 audio
/dɪp/ us
Your browser doesn't support HTML5 audio
/dɪp/
-pp-

dip verb (PUT INTO LIQUID)
Add to word list Add to word list
B2 [ T ]
to put something into a liquid for a short time:
dip something in something Dip the fish in the batter, then drop it into the hot oil.
SMART Vocabulary: related words and phrases
Movement on or through water"""
        value = self.parse(sample)
        self.assertEqual("dip", value["term"])
        self.assertEqual("verb", value["part_of_speech"])
        self.assertIn("/dɪp/", value["phonetic"])
        self.assertIn("to put something into a liquid", value["english_definition"])
        self.assertIn("Dip the fish in the batter", value["source_sentence"])
        self.assertNotIn("Add to word list", value["english_definition"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_merriam_webster_copy_handles_respelling_and_colon_definitions(self):
        sample = """RESORT Definition & Meaning - Merriam-Webster

resort
1 of 3
noun
re·sort ri-ˈzȯrt

1 a
: one that affords aid or refuge : resource

2 c (2)
: a place designed to provide recreation, entertainment, and accommodation especially to vacationers

resort
2 of 3
verb
resorted; resorting; resorts

1
: to go especially frequently or habitually
2
: to have recourse
"""
        value = self.parse(sample)
        self.assertEqual("resort", value["term"])
        self.assertEqual("noun; verb", value["part_of_speech"])
        self.assertIn("ri-ˈzȯrt", value["phonetic"])
        self.assertIn("one that affords aid or refuge", value["english_definition"])
        self.assertNotIn("1 of 3", value["english_definition"])
        self.assertEqual("Merriam-Webster", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_collins_copy_does_not_treat_page_title_as_the_term(self):
        sample = """resort in British English
(rɪˈzɔːt )
noun
1. a place to which many people go for recreation, rest, etc
2. recourse or appeal

verb
3. (intransitive; foll by to)
to have recourse (to) for help, use, etc

Collins English Dictionary
"""
        value = self.parse(sample)
        self.assertEqual("resort", value["term"])
        self.assertIn("rɪˈzɔːt", value["phonetic"])
        self.assertEqual("noun; verb", value["part_of_speech"])
        self.assertIn("a place to which many people go", value["english_definition"])
        self.assertEqual("Collins Dictionary", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_current_collins_copy_skips_branding_between_title_and_headword(self):
        sample = """Definition of 'dip'

COBUILD frequency band

dip

(d ɪ p )

Word forms: plural, 3rd person singular present tense dips, present participle dipping, past tense, past participle dipped

1. verb B2

If you dip something in a liquid, you put it into the liquid for a short time, so that only part of it is covered, and take it out again.

They dip the food into the sauce.

Collins COBUILD Advanced Learner's Dictionary."""
        value = self.parse(sample)
        self.assertEqual("dip", value["term"])
        self.assertEqual("verb", value["part_of_speech"])
        self.assertIn("If you dip something in a liquid", value["english_definition"])
        self.assertNotIn("COBUILD frequency band", value["english_definition"])
        self.assertNotIn("Word forms:", value["english_definition"])
        self.assertEqual("Collins Dictionary", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_dictionary_com_copy_with_bracketed_pronunciation_is_parsed(self):
        sample = """DIP Definition & Meaning | Dictionary.com

dip

[dip] / dɪp /

verb (used with object)

1. to plunge something temporarily into a liquid, so as to moisten it or coat it.

He dipped the brush into the paint bucket.

Synonyms: duck, immerse"""
        value = self.parse(sample)
        self.assertEqual("dip", value["term"])
        self.assertEqual("verb", value["part_of_speech"])
        self.assertIn("/ dɪp /", value["phonetic"])
        self.assertIn("to plunge something temporarily", value["english_definition"])
        self.assertEqual("Dictionary.com", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_bilingual_translation_copy_populates_chinese_meaning(self):
        for sample in (
            "resort\n\n度假胜地；旅游胜地\n\nnoun",
            "English\nresort\nChinese (Simplified)\n度假村；休闲胜地",
            "resort\n/rɪˈzɔːrt/\n名词：度假胜地\n动词：诉诸，求助于",
        ):
            with self.subTest(sample=sample):
                value = self.parse(sample)
                self.assertEqual("resort", value["term"])
                self.assertTrue(value["chinese_meaning"])
                self.assertIn("度假", value["chinese_meaning"])
                self.assertEqual("双语翻译文本", value["detected_format"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_google_homograph_index_is_not_part_of_the_headword(self):
        # Real capture: Google prints the homograph number straight after the headword ("dove1").
        # The index numbers the entry, not the word; before the fix this paste found no headword at
        # all and reported 未识别到英文词条，请让粘贴内容包含单词或短语本身。
        sample = """dove1
/dʌv/
noun
plural noun: doves
1.
a stocky seed- or fruit-eating bird with a small head, short legs, and a cooing voice.
\"the dove was released\""""
        value = self.parse(sample)
        self.assertEqual("dove", value["term"])
        self.assertEqual("/dʌv/", value["phonetic"])
        self.assertEqual("noun", value["part_of_speech"])
        self.assertIn("a stocky seed-", value["english_definition"])
        self.assertIn("the dove was released", value["source_sentence"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_merriam_webster_homograph_index_keeps_the_real_headword(self):
        sample = """dove1
/ˈdəv/
noun
plural doves
1
: any of numerous birds of the family Columbidae that have a stout body and small head"""
        value = self.parse(sample)
        self.assertEqual("dove", value["term"])
        self.assertEqual("noun", value["part_of_speech"])
        self.assertEqual("/ˈdəv/", value["phonetic"])
        self.assertIn("Columbidae", value["english_definition"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_flattened_homograph_paste_recovers_the_word(self):
        value = self.parse(
            "dove1 /dʌv/ noun plural noun: doves 1. a stocky seed- or fruit-eating bird with a small head."
        )
        self.assertEqual("dove", value["term"])
        self.assertEqual("/dʌv/", value["phonetic"])
        self.assertEqual("noun", value["part_of_speech"])

    @unittest.skipUnless(NODE, "Node.js is required for the browser parser smoke test")
    def test_only_a_single_entry_index_is_stripped_from_a_headword(self):
        # The scope of the index rule, pinned directly: it may not touch a digit that belongs to the
        # word, nor a term whose tail is not a word, nor a multi-digit tail.
        cases = {
            "dove1": "dove",
            "dove\u00b9": "dove",
            "bank2": "bank",
            "COVID-19": "COVID-19",
            "U2": "U2",
            "dove11": "dove11",
            "2 of 3": "2 of 3",
        }
        script = f"""
import {{stripHomographIndex}} from {json.dumps((ROOT / 'app' / 'dictionary-parser.js').as_uri())};
console.log(JSON.stringify({json.dumps(list(cases))}.map(stripHomographIndex)));
"""
        result = subprocess.run(
            [NODE, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(list(cases.values()), json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
