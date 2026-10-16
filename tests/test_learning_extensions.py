import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

# Reads the arcs straight out of the builder's markup and asks whether they still form a ring: each
# arc has to be as long as its share of the total, and each has to start exactly where the previous
# one ended. Any gap between those two numbers is a notch in the ring; a negative one is an overlap.
DONUT_SCRIPT = """
import {donutChart} from __CHARTS__;
const colors = ['#5faa38', '#9ed073', '#f0ce6b', '#e5928a'];
const cases = [[26, 18, 6, 0], [1, 1, 1, 0], [7, 5, 3, 1], [16, 16, 16, 2], [41, 7, 2, 0]];
const failures = [];
const wrap = value => ((value % 360) + 540) % 360 - 180;
for (const values of cases) {
  const total = values.reduce((sum, value) => sum + value, 0);
  const markup = donutChart({
    segments: values.map((value, index) => ({label: 's' + index, value, color: colors[index]})),
    center: total,
  });
  const arcs = markup.split('<circle class="insight-arc"').slice(1).map(chunk => ({
    index: Number(/data-arc-index="(\\d+)"/.exec(chunk)[1]),
    len: Number(/--arc-len:([0-9.]+);/.exec(chunk)[1]),
    start: Number(/rotate\\(([-0-9.]+) /.exec(chunk)[1]) + 90,
  }));
  const label = JSON.stringify(values);
  let cursor = 0;
  for (const arc of arcs) {
    const want = values[arc.index] / total * 360;
    const drift = arc.len * 360 - want;
    if (Math.abs(drift) > 0.05) {
      failures.push(`${label} slice ${arc.index} is ${drift.toFixed(2)}deg off its share`);
    }
    const misplaced = wrap(arc.start - cursor);
    if (Math.abs(misplaced) > 0.05) {
      failures.push(`${label} slice ${arc.index} starts ${misplaced.toFixed(2)}deg from the last`);
    }
    cursor = arc.start + arc.len * 360;
  }
  const painted = arcs.reduce((sum, arc) => sum + arc.len, 0);
  if (Math.abs(painted - 1) > 0.0005) failures.push(`${label} paints ${painted} of the ring`);
  if (arcs.length && Math.abs(wrap(cursor - arcs[0].start)) > 0.05) {
    failures.push(`${label} does not close: ends ${wrap(cursor - arcs[0].start).toFixed(2)}deg out`);
  }
}
console.log(JSON.stringify(failures));
"""


class LearningExtensionContractTests(unittest.TestCase):
    def test_review_setup_has_today_scope_and_hides_legacy_chinese_input(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        review_setup = javascript.split("async function renderReview(", 1)[1].split(
            "async function startReview(", 1
        )[0]
        self.assertIn("['today','today','复习今日内容'", review_setup)
        self.assertIn("['recent','recent','最近添加'", review_setup)
        self.assertIn("最近添加数量", review_setup)
        self.assertIn("复习今日内容", review_setup)
        self.assertNotIn("en_to_zh:['看英文想中文'", review_setup)
        self.assertIn("en_to_zh", javascript)  # Historical API/review compatibility remains.

    def test_study_mode_has_separate_unrecorded_answer_path(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("['study','book','学习模式'", javascript)
        self.assertIn("r.scope==='study'||!r.answered", javascript)
        self.assertIn("button('下一条','study-next'", javascript)
        self.assertIn("不保存对错、统计或掌握状态", javascript)

    def test_due_review_ui_is_replaced_by_global_random_review(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        review_setup = javascript.split("async function renderReview(", 1)[1].split(
            "async function startReview(", 1
        )[0]

        self.assertIn("['random','globe','全局复习'", review_setup)
        self.assertIn("function icon(name,className='')", javascript)
        self.assertIn("全局复习", review_setup)
        self.assertIn("从所选内容库智能抽取", review_setup)
        self.assertNotIn('data-scope="due"', review_setup)
        self.assertIn("initialScope=['random','recent','study','today','mistakes','group','topic']", review_setup)

    def test_global_review_offers_balanced_and_forgetting_curve_strategies(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('data-strategy="balanced"', javascript)
        self.assertIn('data-strategy="forgetting"', javascript)
        self.assertIn("错词会优先巩固", javascript)
        self.assertIn("strategy:s.strategy", javascript)
        self.assertIn(".review-plan-grid", css)
        self.assertIn("@keyframes curveDrift", css)

    def test_all_time_statistics_and_activity_feedback_are_visible(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("stats-all", javascript)
        self.assertIn("月度练习节奏", javascript)
        self.assertIn("学习活跃", javascript)
        self.assertIn("今日活跃已记录", javascript)

    def test_mastery_is_editable_inline_and_activity_distinguishes_daily_scores(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('class="mastery-select"', javascript)
        self.assertIn("data-status-id", javascript)
        self.assertIn("掌握度已改为", javascript)
        self.assertIn("wrong:'易错'", javascript)
        self.assertIn(
            "const statusText={wrong:'易错',new:'新词',learning:'学习中',familiar:'较熟悉',mastered:'已掌握'}",
            javascript,
        )
        self.assertIn("function activityLevel(score,maxScore)", javascript)
        self.assertIn("Math.sqrt(score/Math.max(1,maxScore))", javascript)
        self.assertIn("const maxScore=Math.max", javascript)
        self.assertIn("Array.from({length:13}", javascript)
        self.assertIn("style=\"background-color:${activityColor", javascript)
        self.assertIn("表达阅读 ${expressionReads} 次", javascript)
        self.assertIn(".book-sprout-eye", css)

    def test_recall_has_three_precise_results_and_a_reduced_motion_thinking_animation(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        recall_card = javascript.split("function renderReviewCard()", 1)[1].split(
            "function answerReveal", 1
        )[0]
        self.assertIn('data-rating="unrecalled"', recall_card)
        self.assertIn("未能回忆", recall_card)
        self.assertIn("回忆有误", recall_card)
        self.assertIn("回忆正确", recall_card)
        self.assertIn("thinkingPulse", css)
        reduced_motion = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn(".cover-dots", reduced_motion)

    def test_thirty_day_chart_aggregates_every_day_instead_of_sampling_dates(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        stats_view = javascript.split("async function renderStats(", 1)[1].split(
            "async function importCsv", 1
        )[0]
        self.assertIn("bucketStats(data.series,3)", stats_view)
        self.assertNotIn("i%4===0", stats_view)

    def test_chart_reserves_the_same_label_height_for_every_bar(self):
        # The chart markup lives in its own module now, so the contract is read across both files.
        javascript = "".join(
            (ROOT / "app" / name).read_text(encoding="utf-8") for name in ("app.js", "charts.js")
        )
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('class="bar-label"', javascript)
        self.assertIn(".bar-label {", css)
        self.assertIn("min-height: 24px", css)

    def test_behaviour_insight_is_wired_to_real_statistics(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        charts = (ROOT / "app" / "charts.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("学习行为洞察", javascript)
        self.assertIn("从多个维度了解你的学习习惯，找到更适合自己的节奏。", javascript)
        for panel in ("最近练习节奏", "单词状态分布", "各时段练习分布", "正确率趋势"):
            self.assertIn(panel, javascript)
        self.assertIn("月度练习节奏", javascript)
        # Every figure reads from the statistics payload rather than from a hardcoded sample.
        self.assertIn("data.hours", javascript)
        self.assertIn("data.accuracy", javascript)
        self.assertIn("data.status", javascript)
        self.assertIn("accuracy_summary", javascript)
        self.assertNotIn("09/17", javascript)

    def test_statistics_page_survives_a_service_that_predates_the_insight_module(self):
        # The page is always read fresh from disk while a running Python service keeps answering with
        # the payload it was built for, so a page can meet an older shape. Reading `data.accuracy`
        # unguarded there failed the whole route with a raw TypeError instead of one missing module.
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function statsWindow(raw){", javascript)
        self.assertIn("detailed:Boolean(raw?.status)", javascript)
        self.assertIn("if(!data.detailed)return staleInsight();", javascript)
        self.assertIn("const data=statsWindow(rawStats),activity=activityWindow(rawActivity);", javascript)
        self.assertIn("(data.accuracy||[]).map(", javascript)
        self.assertNotIn("data.accuracy.map(", javascript)
        self.assertIn(".insight-stale {", css)

    def test_donut_ring_covers_every_status_the_app_can_assign(self):
        # The ring is meant to partition the whole collection: the total it prints in the middle and
        # the percentages beside it come from the arcs. A status the app can set but the ring does
        # not map would therefore shrink the reported total without any visible error.
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        status_map = javascript.split("const statusText={", 1)[1].split("};", 1)[0]
        statuses = re.findall(r"([a-z_]+):'", status_map)
        segments = javascript.split("function donutSegments(status){", 1)[1].split(
            "function insightOutline", 1
        )[0]

        self.assertEqual(
            statuses, ["wrong", "new", "learning", "familiar", "mastered"],
            "the mastery vocabulary changed; the ring below has to change with it",
        )
        for status in statuses:
            self.assertIn(f"count('{status}')", segments)

    def test_donut_arcs_keep_the_precision_that_lets_them_tile(self):
        # The ring normalises its dashes through `pathLength="1"`, so an arc length is a fraction of
        # the turn and one decimal of it is 36 degrees - while the arc still sits at its exact,
        # unrounded start angle. A 26/18/6/0 ring therefore used to leave a 7.2 degree notch on both
        # sides of the first slice and paint 14.4 degrees of the second slice over the third.
        if not NODE:
            self.skipTest("node is not available to evaluate the chart builders")
        script = DONUT_SCRIPT.replace(
            "__CHARTS__", json.dumps((ROOT / "app" / "charts.js").as_uri())
        )
        result = subprocess.run(
            [NODE, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(result.stdout), [], "the ring no longer closes")

    def test_insight_charts_draw_themselves_without_layout_animation(self):
        charts = (ROOT / "app" / "charts.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")

        for builder in ("export function lineChart", "export function donutChart", "export function barChart", "export function mountCharts"):
            self.assertIn(builder, charts)
        # Drawing is a dash offset and an opacity step, never a change of chart geometry.
        self.assertIn("stroke-dashoffset var(--motion-draw)", css)
        self.assertIn('[data-chart="line"] .insight-line {', css)
        self.assertIn('[data-chart="donut"] .insight-arc {', css)
        self.assertIn(".hour-bar-track i {", css)
        self.assertIn("transform: scaleY(0);", css)
        motion = css.split("   Motion system", 1)[1]
        self.assertNotIn("transition: height", motion)
        self.assertNotIn("transition: width", motion)
        # The entrance is staged, and one curve and one ladder of durations govern the page.
        self.assertIn("body[data-route=\"stats\"] .page-enter [data-enter]", css)
        self.assertIn("--motion-ease: cubic-bezier(.22, 1, .36, 1);", css)
        self.assertIn("body[data-route=\"stats\"] .page-enter .activity-grid .activity-cell", css)

    def test_line_chart_keeps_the_last_axis_label_clear_of_the_one_before_it(self):
        # The 30-day window samples every second bucket and then forces the final date in, which
        # used to print "09/19–21" and "09/22–24" on top of each other. The forced label now pushes
        # the previous one aside instead of overlapping it.
        charts = (ROOT / "app" / "charts.js").read_text(encoding="utf-8")

        self.assertIn("const labelIndices = [];", charts)
        self.assertIn("if (lastIndex - labelIndices.at(-1) < labelEvery) labelIndices.pop();", charts)
        self.assertIn("labelled.has(index)", charts)
        self.assertNotIn("index % labelEvery === 0 || index === coords.length - 1", charts)

    def test_charts_replace_the_browser_default_tooltip(self):
        javascript = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("chartTip.className='chart-tip'", javascript)
        self.assertIn("[data-tip]", javascript)
        self.assertIn(".chart-tip-body {", css)
        self.assertIn("backdrop-filter: blur(8px);", css)
        self.assertNotIn('title="${point.date}', javascript)

    def test_reduced_motion_switches_off_every_insight_animation(self):
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        reduced = css.rsplit("@media (prefers-reduced-motion: reduce)", 1)[1]

        self.assertIn(".insight-line", reduced)
        self.assertIn(".insight-arc", reduced)
        self.assertIn(".hour-bar-track i", reduced)
        self.assertIn('[data-enter]', reduced)
        self.assertIn(".activity-grid .activity-cell", reduced)

    def test_route_switching_has_visible_motion_and_reduced_motion_fallback(self):
        css = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".page-enter { animation: pageEnter", css)
        self.assertIn(".nav a.active { animation: navActivate", css)
        self.assertIn("@keyframes pageEnter", css)
        self.assertIn("@keyframes navActivate", css)
        self.assertIn(".page-enter, .nav a.active { animation: none; }", css)


if __name__ == "__main__":
    unittest.main()
