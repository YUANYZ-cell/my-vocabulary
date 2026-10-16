import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
COUNTER = (ROOT / "app" / "counter.js").as_uri()


# Minimal DOM so the real counter module can be mounted outside a browser. Only the API
# surface counter.js touches is implemented: createElement/append/remove/style/attributes plus
# the two layout reads it needs (getComputedStyle and getBoundingClientRect for the host box).
DOM_STUB = """
function expect(condition, message) {
  if (condition) return;
  console.error('FAILED: ' + message);
  process.exit(1);
}
// The line box the plain number occupies. Tests override this to imitate type that is not
// 1em tall, which is what the practice-chart labels use.
globalThis.__lineBox = { fontSize: '10px', height: 10 };
function makeElement(tag) {
  const element = {
    tagName: tag,
    className: '',
    textContent: '',
    children: [],
    style: {},
    attributes: {},
    parent: null,
    get childNodes() { return element.children },
    append(...nodes) {
      nodes.forEach(node => {
        if (node.parent) node.parent.children = node.parent.children.filter(child => child !== node);
        node.parent = element;
        element.children.push(node);
      });
    },
    remove() {
      const parent = element.parent;
      if (parent) parent.children = parent.children.filter(child => child !== element);
    },
    setAttribute(name, value) { element.attributes[name] = String(value) },
    getAttribute(name) { return name in element.attributes ? element.attributes[name] : null },
    getBoundingClientRect() {
      return { top: 0, left: 0, right: 0, bottom: globalThis.__lineBox.height, width: 0, height: globalThis.__lineBox.height };
    },
    querySelector(selector) {
      const wanted = selector.replace('.', '');
      const walk = node => {
        for (const child of node.children) {
          if (child.className === wanted) return child;
          const found = walk(child);
          if (found) return found;
        }
        return null;
      };
      return walk(element);
    }
  };
  return element;
}
globalThis.document = { createElement: makeElement };
globalThis.getComputedStyle = () => ({
  fontSize: globalThis.__lineBox.fontSize,
  paddingTop: '0px', paddingBottom: '0px', borderTopWidth: '0px', borderBottomWidth: '0px'
});
const frames = [];
globalThis.requestAnimationFrame = callback => { frames.push(callback); return frames.length };
globalThis.cancelAnimationFrame = () => {};
function runFrames(total) {
  for (let index = 1; index <= total; index += 1) {
    const pending = frames.splice(0, frames.length);
    pending.forEach(callback => callback(index * 16.7));
  }
}
function textNode(value) {
  return { nodeType: 3, textContent: value, parent: null };
}
// Mirrors what app.js emits: the host carries the plain number as a text node, and the line
// box it occupies is whatever the surrounding type gives it.
function stripHost(value, lineBox) {
  globalThis.__lineBox = lineBox || { fontSize: '10px', height: 10 };
  const host = makeElement('span');
  host.className = 'counter';
  host.setAttribute('data-counter', value);
  host.append(textNode(value));
  return host;
}
function mount(host) {
  mountCounters({ querySelectorAll: () => [host] });
  return host;
}
function strip(host) {
  return host.children[host.children.length - 1];
}
"""


class CounterTests(unittest.TestCase):
    def run_script(self, body):
        script = (
            f"import {{placesFor, digitOffset, mountCounters}} from {json.dumps(COUNTER)};\n"
            f"{DOM_STUB}\n{body}\n"
        )
        result = subprocess.run(
            [NODE, "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    @unittest.skipUnless(NODE, "Node.js is required for the counter smoke test")
    def test_places_are_derived_from_integer_and_decimal_values(self):
        self.run_script(
            """
const integers = placesFor('1234').map(entry => entry.place);
expect(JSON.stringify(integers) === JSON.stringify([1000, 100, 10, 1]), 'placesFor(1234) -> ' + JSON.stringify(integers));
const single = placesFor('7');
expect(single.length === 1 && single[0].place === 1 && single[0].decimal === false, 'placesFor(7) should be the ones column');
const mixed = placesFor('12.50').map(entry => entry.place);
expect(JSON.stringify(mixed) === JSON.stringify([10, 1, '.', 0.1, 0.01]), 'placesFor(12.50) -> ' + JSON.stringify(mixed));
"""
        )

    @unittest.skipUnless(NODE, "Node.js is required for the counter smoke test")
    def test_glyph_travel_stays_within_half_a_turn(self):
        self.run_script(
            """
expect(digitOffset(0, 0) === 0, 'the current digit sits in the window');
expect(digitOffset(0, 1) === 1, 'the next digit waits below');
expect(digitOffset(0, 9) === -1, 'the previous digit waits above');
expect(digitOffset(137, 0) === 3, 'a full place value still folds to +/-5 steps');
expect(Math.abs(digitOffset(3.4, 3) + 0.4) < 1e-9, 'fractional place values roll smoothly');
for (let progress = 0; progress < 10; progress += 0.25) {
  for (let digit = 0; digit < 10; digit += 1) {
    expect(Math.abs(digitOffset(progress, digit)) <= 5, 'travel capped at 5 steps for ' + progress + '/' + digit);
  }
}
"""
        )

    @unittest.skipUnless(NODE, "Node.js is required for the counter smoke test")
    def test_stats_counter_rolls_to_the_exact_value(self):
        self.run_script(
            """
const host = stripHost('137');
mount(host);
expect(host.children.length === 2, 'the host keeps a hidden placeholder plus one strip');
const placeholder = host.children[0];
expect(placeholder.className === 'counter-static', 'the plain number is kept as a hidden placeholder');
expect(placeholder.getAttribute('aria-hidden') === 'true', 'the placeholder stays invisible to assistive tech');
expect(placeholder.children.length === 1, 'the placeholder holds exactly the text it replaced');
expect(placeholder.children[0].nodeType === 3 && placeholder.children[0].textContent === '137', 'the frozen text is stowed inside the placeholder, not left in the flow');
const track = host.children[1];
expect(track.className === 'counter-track', 'the strip carries the counter-track class');
expect(track.getAttribute('aria-hidden') === 'true', 'the rolling glyphs stay decorative');
expect(host.style.width === '3ch', 'the host reserves the width of the replaced text, got ' + host.style.width);
expect(host.getAttribute('role') === 'img' && host.getAttribute('aria-label') === '137', 'the host exposes the final value');
const columns = track.children;
expect(columns.length === 3, '137 needs three digit columns, got ' + columns.length);
expect(columns.every(column => column.children.length === 10), 'every column holds the ten glyphs');
expect(columns.every(column => column.children.every(glyph => glyph.style.transform)), 'glyphs start positioned, not stacked');

runFrames(10);
expect(columns[2].children[7].style.transform !== 'translateY(0em)', 'the ones column is still rolling after 10 frames');
runFrames(260);
expect(columns[0].style.opacity === '1' && columns[1].style.opacity === '1', 'higher places fade in and stay visible');
expect(columns[0].children[1].style.transform === 'translateY(0em)', 'hundreds glyph 1 lands in the window');
expect(columns[1].children[3].style.transform === 'translateY(0em)', 'tens glyph 3 lands in the window');
expect(columns[2].children[7].style.transform === 'translateY(0em)', 'ones glyph 7 lands in the window');
expect(columns[2].children[0].style.transform === 'translateY(3em)', 'ones glyph 0 waits three steps below');
expect(columns[2].children[8].style.transform === 'translateY(1em)', 'ones glyph 8 waits one step below');
expect(columns[0].children[0].style.transform === 'translateY(-1em)', 'hundreds glyph 0 waits one step above');
mount(host);
expect(host.children.length === 2, 'an already mounted counter is never mounted twice');
"""
        )

    @unittest.skipUnless(NODE, "Node.js is required for the counter smoke test")
    def test_rows_follow_the_line_box_of_the_host(self):
        # The practice-chart labels are 10px type on a 14px line box. Measuring the pitch from
        # that line box is what keeps the next glyph out of the window while the number rolls.
        self.run_script(
            """
const host = stripHost('25', {fontSize: '10px', height: 14});
mount(host);
const columns = strip(host).children;
expect(columns.length === 2, '25 needs two digit columns');
runFrames(260);
expect(columns[1].children[5].style.transform === 'translateY(0em)', 'ones glyph 5 lands in the window');
expect(columns[1].children[4].style.transform === 'translateY(-1.4em)', 'one row above is one line box, not one em');
expect(columns[1].children[6].style.transform === 'translateY(1.4em)', 'one row below is one line box, not one em');
expect(columns[0].children[2].style.transform === 'translateY(0em)', 'tens glyph 2 lands in the window');
expect(columns[0].children[0].style.transform === 'translateY(-2.8em)', 'travel scales with the measured pitch');
"""
        )

    @unittest.skipUnless(NODE, "Node.js is required for the counter smoke test")
    def test_non_rolling_values_keep_their_static_text(self):
        self.run_script(
            """
for (const value of ['-3', 'abc', '']) {
  const host = stripHost(value);
  mount(host);
  expect(host.children.length === 1, 'value ' + JSON.stringify(value) + ' keeps its static text');
  expect(host.getAttribute('role') === null, 'value ' + JSON.stringify(value) + ' is left alone for assistive tech');
}
"""
        )

    @unittest.skipUnless(NODE, "Node.js is required for the counter smoke test")
    def test_reduced_motion_lands_on_the_value_without_frames(self):
        self.run_script(
            """
globalThis.window = { matchMedia: () => ({ matches: true }) };
const host = stripHost('42');
mount(host);
const columns = strip(host).children;
expect(columns.length === 2, '42 needs two digit columns');
expect(columns[0].children[4].style.transform === 'translateY(0em)', 'equal motion preference shows the final value at once');
expect(columns[1].children[2].style.transform === 'translateY(0em)', 'ones glyph 2 shows the final value at once');
expect(frames.length === 0, 'no frame loop is scheduled under reduced motion');
"""
        )


if __name__ == "__main__":
    unittest.main()
