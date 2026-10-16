import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StaticContractTests(unittest.TestCase):
    def test_application_contains_required_routes_and_modes(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        for label in ("今日", "复习", "词库", "阅读素材", "添加", "统计"):
            self.assertIn(label, html)
        for mode in ("cloze", "zh_to_en", "en_to_zh", "recall"):
            self.assertIn(mode, javascript)
        self.assertNotIn("dictation", javascript)
        self.assertIn("建立易混词组", javascript)
        self.assertIn("全局复习", javascript)
        self.assertIn("最近添加", javascript)
        self.assertIn("遗忘曲线", javascript)
        self.assertIn("重置全局抽词", javascript)
        self.assertIn("查看中文", javascript)
        self.assertIn("回忆正确", javascript)
        self.assertIn("回忆有误", javascript)
        self.assertIn("未能回忆", javascript)
        self.assertIn("[遮罩自评]", javascript)
        self.assertIn("同义词 / 替换词", javascript)
        self.assertNotIn("学习新词", html + javascript)
        self.assertNotIn("今日新词", html + javascript)

    def test_application_is_local_responsive_and_accessible(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('name="viewport"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("max-width:760px", css)
        self.assertIn("main:focus-visible { outline: 0; }", css)
        self.assertIn("Polished learning world", css)
        self.assertIn("Refined Duolingo learning system", css)
        refined_css = css.split("/* Refined Duolingo learning system", 1)[1]
        self.assertIn("--accent: #58c625", refined_css)
        self.assertIn("@keyframes polishedPageIn", css)
        self.assertIn("@keyframes pathStepIn", css)
        self.assertIn("@keyframes homeMarkFloat", css)
        self.assertIn("@keyframes bookBuddySway", css)
        self.assertIn('styles.css?v=78', html)
        self.assertIn('app.js?v=100', html)
        self.assertNotIn("https://", html + css + javascript)
        self.assertNotIn("http://", html + css + javascript)
        # The recognition module is cached by its own query string, so a parser change must bump it
        # together with the entry version above — otherwise a warm cache keeps running the old rules.
        self.assertIn("import {parseDictionaryText} from './dictionary-parser.js?v=17';", javascript)
        self.assertIn("navigator.clipboard.readText", javascript)
        self.assertIn("从词典或翻译软件粘贴", javascript)
        self.assertIn("parsed.detected_format", javascript)
        self.assertIn("中文只会从粘贴内容中提取", javascript)
        self.assertIn("英文释义 ${parsed.definition_count||1} 条", javascript)
        self.assertIn("原文没有中文释义；英文内容已填入下方“英文释义”", javascript)
        self.assertIn('class="path-route"', javascript)
        self.assertIn("stroke-dasharray", css)
        self.assertIn("function icon(name,className='')", javascript)
        self.assertIn('class="page-kicker"', javascript)
        self.assertNotIn(".learning-path::before", css)
        self.assertIn(".learning-layout { display: grid; grid-template-columns: 1fr;", css)
        self.assertIn(
            ".learning-aside { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));",
            css,
        )

    def test_expression_library_keeps_reading_separate_from_review(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-route="expressions"', html)
        self.assertIn("阅读素材", javascript)
        self.assertIn("句式 · 段落 · 范文", javascript)
        self.assertIn("继续阅读", javascript)
        self.assertIn("浏览素材", javascript)
        self.assertIn("最近阅读", javascript)
        self.assertIn("显示中文翻译", javascript)
        self.assertIn("data-expression-action=\"favorite\"", javascript)
        self.assertIn('name="english_text"', javascript)
        self.assertIn(".expression-filter-shelf", css)
        self.assertIn(".expression-reader-layout", css)
        self.assertIn("expression_materials", (ROOT / "vocabulary" / "database.py").read_text(encoding="utf-8"))
        self.assertNotIn("expression_materials", (ROOT / "vocabulary" / "stats.py").read_text(encoding="utf-8"))

    def test_error_ranking_fills_short_windows_to_five_all_time_words(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        ranking = javascript.split("function errorRanking(map,allTimeWords=[])", 1)[1].split(
            "function errorMapBody", 1
        )[0]

        self.assertIn("const RANKING_ROWS=5;", javascript)
        self.assertIn("for(const word of allTimeWords)", ranking)
        self.assertIn("if(words.length>=RANKING_ROWS)break", ranking)
        self.assertIn("if(!seen.has(word.id))", ranking)
        self.assertIn("errorRanking(map,data.mistakes)", javascript)

    def test_home_actions_share_a_quiet_button_family_and_daily_copy_has_depth(self):
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        motivation_block = javascript.split("const motivationText={", 1)[1].split(
            "function localDayNumber", 1
        )[0]

        for variant in ("mission", "progress", "capture"):
            self.assertIn(f"home-action {variant}", javascript)
            self.assertIn(f".learning-aside .btn.home-action.{variant}", css)
        self.assertIn("width: auto;", css)
        self.assertIn("box-shadow: none;", css)
        self.assertIn('class="stats-link">学习统计', javascript)
        self.assertIn(".stats-link", css)
        self.assertIn("function dailyMotivation", javascript)
        self.assertIn("Date.UTC(date.getFullYear(),date.getMonth(),date.getDate())", javascript)
        self.assertGreaterEqual(
            len(re.findall(r"^\s{4}'[^']+'[,]?$", motivation_block, re.MULTILINE)),
            96,
        )

    def test_dynamic_form_labels_and_same_route_navigation_are_wired(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("new MutationObserver", javascript)
        self.assertIn("field.querySelector('label')", javascript)
        self.assertIn("label.htmlFor=control.id", javascript)
        self.assertIn("control.name==='phonetic'?'item-phonetic'", javascript)
        self.assertIn("target.closest('a[data-route], button[data-route]')", javascript)
        # `<body>` carries data-route because the stats page keys its entry animations off
        # body[data-route="stats"]. A bare [data-route] lookup therefore resolves to the body for
        # every click in the app and routes the user away from whatever they just tapped, so the
        # click handler must stay anchored to real navigation controls.
        self.assertIn("onCommit:()=>{document.body.dataset.route=route}", javascript)
        self.assertNotIn("closest('[data-route]')", javascript)
        self.assertNotIn("querySelectorAll('[data-route]')", javascript)
        self.assertIn("location.hash===next", javascript)
        self.assertIn("submitItemFormFromPageEnter", javascript)
        self.assertIn("form.requestSubmit()", javascript)
        self.assertIn("input, textarea, select, button, a", javascript)
        self.assertIn(r"/^edit-\d+$/", javascript)
        self.assertIn(r"/^delete-\d+$/", javascript)
        self.assertNotIn(r"/^edit-\\d+$/", javascript)
        self.assertNotIn(r"/^delete-\\d+$/", javascript)

    def test_synonyms_stay_out_of_library_rows_and_are_available_in_details(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        library_row = javascript.split("function libraryRow(item)", 1)[1].split(
            "function bindLibrary()", 1
        )[0]
        recall_card = javascript.split("function renderReviewCard()", 1)[1].split(
            "function answerReveal", 1
        )[0]

        self.assertNotIn("item.synonyms", library_row)
        self.assertIn("同义 / 替换：", javascript)
        self.assertIn("入库后词库列表只显示英文和中文；近义词会独立保存在详情中。", javascript)
        self.assertIn("button('查看详情',`detail-${item.id}`,'small light')", recall_card)

    def test_library_shows_words_and_fixed_collocations_apart_from_long_sentences(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        library = javascript.split("let libraryRequestVersion=0", 1)[1].split(
            "function libraryRow(item)", 1
        )[0]

        self.assertIn("item_group:'vocabulary'", javascript)
        self.assertIn("data-library-group=\"vocabulary\"", library)
        self.assertIn("data-library-group=\"sentence\"", library)
        self.assertIn("单词与固定搭配", library)
        self.assertIn("peal of laughter", library)
        self.assertIn("雅思句型与完整描述句单独存放", library)
        self.assertNotIn("phrase-guide", library)
        self.assertNotIn("添加短语", library)
        self.assertNotIn("添加长句", library)
        self.assertNotIn('data-filter="item_type"', library)
        self.assertIn(".library-group-switch", css)
        self.assertIn('aria-label="词条类型筛选"', library)
        self.assertIn('data-library-type=', library)
        self.assertIn('只看单词', library)
        self.assertIn('只看固定搭配', library)

    def test_sentence_library_omits_mastery_and_switches_in_place(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        library = javascript.split("let libraryRequestVersion=0", 1)[1].split(
            "function bindMasteryBoost()", 1
        )[0]
        add_form = javascript.split("async function renderAdd(", 1)[1].split(
            "async function renderExpressionForm", 1
        )[0]
        review_card = javascript.split("function renderReviewCard()", 1)[1].split(
            "function renderPreviousReviewCard", 1
        )[0]

        self.assertIn("group==='sentence'?'':'<span>掌握度</span>'", library)
        self.assertIn("item.item_type==='sentence'?'':`<div class=\"mastery-control\"", library)
        self.assertIn("status:group==='sentence'?'':state.filters.status", library)
        self.assertIn("refreshLibraryContent()", library)
        self.assertNotIn("state.editingGroup=null;\n    renderLibrary();", library)
        self.assertIn("[data-library-content]", library)
        self.assertIn(".library-list.sentence-list .library-row", css)
        self.assertIn("data-mastery-field", add_form)
        self.assertIn("item.item_type==='sentence'?'':reviewMasteryPanel(item)", review_card)

    def test_mastery_boost_stars_and_review_limit_presets_are_wired(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        library_row = javascript.split("function libraryRow(item)", 1)[1].split(
            "function bindLibrary()", 1
        )[0]
        mastery_boost = javascript.split("function masteryBoost(item)", 1)[1].split(
            "const esc=", 1
        )[0]
        review_card = javascript.split("function renderReviewCard()", 1)[1].split(
            "function renderPreviousReviewCard", 1
        )[0]

        self.assertIn("const masteryBoostTarget={wrong:'new',new:'learning',learning:'familiar',familiar:'mastered'};", javascript)
        self.assertIn("function bindMasteryBoost()", javascript)
        self.assertNotIn("masteryBoost(item)", library_row)
        self.assertIn("reviewMasteryPanel(item)", review_card)
        self.assertIn('data-mastery-boost', mastery_boost)
        self.assertIn("masteryStars(status,item)", library_row)
        self.assertIn('data-mastery-star', javascript)
        self.assertIn('role="radiogroup"', javascript)
        self.assertNotIn('mastery-dot', library_row)
        self.assertNotIn('mastery-steps', library_row)
        self.assertIn("const reviewLimitPresets=[10,20,30,50,100];", javascript)
        self.assertIn('class="limit-slider-shell"', javascript)
        self.assertIn('id="review-limit-custom"', javascript)
        self.assertIn("state.reviewSetup.limit=value", javascript)
        self.assertIn("bindReviewLimitControl();", javascript)
        self.assertIn("syncReviewSetupUi(scope.dataset.scope);", javascript)
        self.assertNotIn("#batch-select", javascript)
        self.assertNotIn("#recent-limit", javascript)
        self.assertIn(".mastery-boost", css)
        self.assertIn(".mastery-stars", css)
        self.assertIn(".limit-liquid", css)

    def test_review_content_type_is_explicit_and_sent_to_every_queue(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("只复习单词", javascript)
        self.assertIn("只复习短语", javascript)
        self.assertIn("只复习长句", javascript)
        self.assertIn('data-review-type="${type}"', javascript)
        self.assertIn("item_type:s.itemType", javascript)
        self.assertIn("item_type:state.reviewSetup.itemType", javascript)
        self.assertIn(".content-type-switch", css)
        self.assertIn(".review-plan-grid { display: grid;", css)

    def test_review_card_motion_does_not_restart_page_header(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        card = javascript.split("function renderReviewCard()", 1)[1].split(
            "function renderPreviousReviewCard", 1
        )[0]
        self.assertIn("main.classList.remove('page-enter')", card)
        self.assertIn("r.motionIndex!==r.index", card)
        self.assertIn("review-card-switch", card)
        self.assertIn(".review-card-switch { animation:", css)
        self.assertIn(".review-card-switch { animation: none; }", css)

    def test_review_launch_does_not_float_over_setup_and_home_banner_stays_subtly_glassy(self):
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        review_studio = css.split("/* Review studio:", 1)[1].split("@keyframes floatHint", 1)[0]
        launch_dock = review_studio.split(".launch-dock {", 1)[1].split("}", 1)[0]
        banner = css.split("/* Quiet frosted learning card:", 1)[1].split(
            '.nav a[data-route="today"]', 1
        )[0]

        self.assertIn("position: static", launch_dock)
        self.assertNotIn("position: sticky", launch_dock)
        self.assertIn("backdrop-filter: blur(8px) saturate(1.06)", banner)
        self.assertIn("rgba(70,176,16,.94)", banner)

    def test_stats_numbers_roll_through_the_shared_counter(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        counter = (ROOT / "app" / "counter.js").read_text(encoding="utf-8")

        self.assertIn("import {mountCounters} from './counter.js?v=2';", javascript)
        self.assertIn("new MutationObserver(()=>mountCounters(main))", javascript)
        self.assertIn("function counter(value)", javascript)
        # The three stat cards, the streak figures and the practice chart labels all roll.
        self.assertIn("<strong>'+counter(value)+'</strong>", javascript)
        self.assertIn("counter(data.current_streak)", javascript)
        self.assertIn("counter(data.active_days)", javascript)
        self.assertIn("counter(data.longest_streak)", javascript)
        self.assertIn("counter(x.reviews)", javascript)
        # Counters must stay decorative for assistive tech and inert for reduced motion.
        self.assertIn("aria-hidden", counter)
        self.assertIn("prefers-reduced-motion", counter)
        self.assertIn("role', 'img'", counter)
        self.assertIn("span.counter[data-counter]", css)

        self.assertIn(".counter .counter-digit", css)
        self.assertIn(".stats-metrics .metric, .activity-card, .chart-card { --counter-shade: #fff; }", css)
        # The number that was replaced is stowed in a hidden placeholder: it keeps the host box
        # identical and stops a frozen copy of the old digits showing through the rolling strip.
        # The placeholder and the strip restate the host typography so page rules aimed at
        # generic spans (.metric span) cannot shrink the box and clip the digits.
        self.assertIn(".counter .counter-static { display: inline; visibility: hidden; }", css)
        self.assertIn("counter-static", counter)
        self.assertIn("isolateStaticText", counter)
        self.assertIn(
            ".counter .counter-static,\n.counter .counter-track,\n.counter .counter-digit,\n"
            ".counter .counter-number,\n.counter .counter-dot { font: inherit; font-variant-numeric: tabular-nums; color: inherit; line-height: inherit; }",
            css,
        )
        # Every roll row copies the host line box, so a glyph lands on the baseline of the text
        # underneath even when the surrounding type is not 1em tall (the chart labels are not).
        self.assertIn("rowPitch", counter)
        self.assertIn(".counter .counter-digit { position: relative; width: 1ch; }", css)
        self.assertIn(
            ".counter .counter-number { position: absolute; top: 0; right: 0; bottom: 0; left: 0; text-align: center; }",
            css,
        )

    def test_stat_cards_replace_decorative_bars_with_real_context(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn('class="metric-sparkline"', javascript)
        for label in ("本周期日均", "活跃天数", "占词库比例"):
            self.assertIn(label, javascript)
        self.assertIn(".stats-metrics .metric-context", css)
        self.assertIn("conic-gradient", css)


if __name__ == "__main__":
    unittest.main()

