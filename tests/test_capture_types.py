import json
import shutil
import subprocess
import unittest
from pathlib import Path

from vocabulary.content_types import infer_item_type

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is required for capture detection')
class CaptureTypesTests(unittest.TestCase):
    def run_js(self, code):
        module = (ROOT / 'app/content-types.js').as_uri()
        result = subprocess.run(
            [NODE, '--input-type=module', '-e',
             f'import {{inferItemType,updateCaptureType}} from {json.dumps(module)};\n{code}'],
            check=True, capture_output=True, text=True, encoding='utf-8',
        )
        return json.loads(result.stdout)

    def test_capture_matches_saved_repository_types(self):
        samples = ['sparse', ' self-aware ', "don't", 'peal of laughter',
                   'play a crucial role in', '  integrated\t circuit  ',
                   'Take care on the road.',
                   'The figure saw a gradual decline over the period.']
        actual = self.run_js(f'console.log(JSON.stringify({json.dumps(samples)}.map(inferItemType)));')
        self.assertEqual(actual, [infer_item_type(term) for term in samples])
        self.assertEqual(actual, ['word', 'word', 'word', 'phrase', 'phrase', 'phrase', 'phrase', 'sentence'])

    def test_continuous_entry_reclassifies_each_new_term(self):
        result = self.run_js('''
const form={elements:{term:{value:''},type_choice:{value:'auto'},item_type:{value:'sentence'}}};
const types=['entropy','peal of laughter','The figure saw a gradual decline over the period.','circuit'].map(term=>{
  form.elements.term.value=term;return updateCaptureType(form);
});
console.log(JSON.stringify(types));
''')
        self.assertEqual(result, ['word', 'phrase', 'sentence', 'word'])

    def test_game_changer_open_and_hyphenated_spellings_are_words(self):
        samples = ['game-changer', 'Game changer', ' GAME\tCHANGER ',
                   'game changers in education', 'transform the way people work']
        actual = self.run_js(f'console.log(JSON.stringify({json.dumps(samples)}.map(inferItemType)));')
        self.assertEqual(actual, ['word', 'word', 'word', 'phrase', 'phrase'])
        self.assertEqual(actual, [infer_item_type(term) for term in samples])

    def test_explicit_type_survives_typing_and_can_return_to_auto(self):
        result = self.run_js('''
const form={elements:{term:{value:'A deliberately long collocation can need manual correction'},type_choice:{value:'phrase'},item_type:{value:'word'}}};
const chosen=updateCaptureType(form);
form.elements.term.value='The figure saw a gradual decline over the period.';
const retained=updateCaptureType(form);
form.elements.type_choice.value='auto';
console.log(JSON.stringify([chosen,retained,updateCaptureType(form)]));
''')
        self.assertEqual(result, ['phrase', 'phrase', 'sentence'])
