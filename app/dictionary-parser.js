import {inferItemType} from './content-types.js?v=1';
// Parse pasted dictionary or translation text locally. Never follow links or translate content.
const POS_WORDS = ['phrasal verb', 'auxiliary verb', 'modal verb', 'transitive verb', 'intransitive verb',
  'noun', 'verb', 'adjective', 'adverb', 'pronoun', 'preposition', 'conjunction', 'interjection',
  'determiner', 'exclamation', 'article'];
const NARRATIVE_POS = new RegExp(
  `^(?:The (?:word|term|phrase|expression)\\s+)?["“']?([a-zA-Z][a-zA-Z '’.-]*?)["”']?\\s+is\\s+(?:an?\\s+)?(${POS_WORDS.map(pos => pos.replaceAll(' ', '\\s+')).join('|')})\\b`,
  'i',
);

const TERM_NOISE = /^(?:english|chinese(?:\s*\(simplified\))?|simplified chinese|中文|简体中文|英(?:语|文)|中(?:文|译)|uk|us|american|meaning|definition|translation|translate)$/i;
const STOP_SECTION = /^(?:Origin|Etymology|Translations?|People also ask|Examples? (?:of|in)|Word History|Cite this Entry|Kids Definition|SMART Vocabulary|Collocations? with)\b/i;
const ABBREVIATED_POS = {n: 'noun', adj: 'adjective', adv: 'adverb', v: 'verb', vt: 'verb', vi: 'verb', pron: 'pronoun', prep: 'preposition', conj: 'conjunction', interj: 'interjection', num: 'numeral', art: 'article', det: 'determiner', aux: 'verb'};
const YOUDAO_POS = /^(n|adj|adv|vt|vi|v|pron|prep|conj|interj|num|art|det|aux)\.\s*(.*)$/i;

function isYoudaoText(text) {
  return /有道(?:翻译|词典)|来自有道/.test(text)
    || /(?:英|美)\s*(?:\/[^/\n]+\/|\[[^\]\n]+\])/.test(text)
    || /(?:英|美)\s*\n\s*(?:\/[^/\n]+\/|\[[^\]\n]+\])/.test(text);
}

function normalizeYoudaoText(text) {
  // Recover the dictionary's strong boundaries even when clipboard text is flattened.
  const expanded = text.replace(/\s*(英|美)\s*(?:\/([^/\n]+)\/|\[([^\]\n]+)\])/g,
    (_, region, slash, bracket) => `\n${region} /${(slash || bracket).trim()}/\n`)
    .replace(/\s+(?=(?:n|adj|adv|vt|vi|v|pron|prep|conj|interj|num|art|det|aux)\.\s*[\u3400-\u9fff<（(])/gi, '\n');
  const lines = expanded.split('\n').map(tidyLine).filter(Boolean);
  const result = [];
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (/^(?:有道翻译|有道词典|检测到(?:英语|英文)\s*[-—–]\s*中文|术语库|查看全部\s*[>›]?|来自有道词典结果|AI润色|重点词汇|\d+\s*\/\s*5000)$/.test(line)
        || /^(?:CET[46]|考研|GRE|TOEFL|IELTS)(?:\s*[/、]\s*(?:CET[46]|考研|GRE|TOEFL|IELTS))*$/i.test(line)) continue;
    if (YOUDAO_POS.test(line) && !line.match(YOUDAO_POS)[2] && /[\u3400-\u9fff]/.test(lines[index + 1] || '') && !/^(?:英|美)\s*\//.test(lines[index + 1])) {
      result.push(`${line} ${lines[++index]}`);
    } else result.push(line);
  }
  return result.join('\n');
}


function cleanMarkdown(raw) {
  return raw.replace(/\r\n?/g, '\n').replace(/\u00a0/g, ' ')
    .replace(/\[([^\]]+)\]\((?:[^()\n]|\([^()\n]*\))*\)/g, '$1')
    .replace(/[ \t]*\(https?:\/\/[^)\s]+\)[ \t]*[,;]?/gi, ' ')
    .replace(/(^|\s)https?:\/\/[^\s]+/gi, '$1')
    .replace(/\\([.*_()\[\]#;!&-])/g, '$1')
    .replace(/\*{1,3}|_{1,3}/g, '')
    .replace(/[ \t]*\[(?:\d+[ \t]*(?:,[ \t]*\d+[ \t]*)*)\][ \t]*[,;]?/g, ' ');
}

function stripPronunciationButton(text) {
  // Google Dictionary copies this button before definitions or on its own line.
  return text.replace(/^([ \t]*)([-•][ \t]*)?Learn to pronounce(?:[ \t]*([·•:：|–—-])[ \t]*|[ \t]*$)/gim,
    (_, indent, bullet, separator) => separator ? `${indent}${bullet || '• '}` : '');
}

function tidyLine(line) {
  return line.replace(/^#{1,6}\s*/, '').replace(/[¹²³⁴⁵]+$/, '').trim();
}

// Dictionaries number their homograph entries: Google copies as "dove1", Merriam-Webster as "dove1"
// or "dove¹". The index belongs to the entry, not to the word, and it is what makes a real paste
// unrecognisable — "dove1" fails the plain-word test below, so the headword line is discarded and the
// entry either reports no word at all or falls through to the next line ("plural doves").
// Only a single index glued to the end of a word of at least two letters is dropped, so a headword
// that genuinely ends in a digit ("COVID-19") and a term whose tail is not a word ("U2") are left
// alone. Exported so the rule's exact scope can be pinned by a test of its own.
const HOMOGRAPH_INDEX = /^(.*[a-zA-Z]{2}['’]?)[0-9¹²³⁴⁵⁶⁷⁸⁹]$/u;

export function stripHomographIndex(term) {
  const match = term.match(HOMOGRAPH_INDEX);
  return match ? match[1] : term;
}

function normalizeTerm(value) {
  return stripHomographIndex(value.replace(/^['“”]|['“”]$/g, '').replace(/\s+/g, ' ').trim());
}

function isTermCandidate(value) {
  const term = normalizeTerm(value);
  if (!/^[a-zA-Z][a-zA-Z '’().-]*$/.test(term) || term.length > 240 || term.split(/\s+/).length > 12) return false;
  if (term.split(/\s+/).length >= 3 && /[.!?]$/.test(term)) return false;
  if (TERM_NOISE.test(term) || /\b(?:meaning|definition|dictionary|synonyms?|antonyms?|examples?)\b/i.test(term)) return false;
  return !POS_WORDS.some(pos => term.toLowerCase() === pos);
}

function canonicalizeSyllabifiedHeadword(value) {
  const term = normalizeTerm(value);
  if (!/[·‧]/.test(term)) return '';
  const canonical = term.replace(/[·‧]/g, '');
  return /^[a-zA-Z][a-zA-Z'’-]*$/.test(canonical) ? canonical : '';
}

function extractNarrativeHeadword(line) {
  const patterns = [
    // Read "Charming is an adjective that means ..." before the general
    // "X means ..." rule, which would swallow "is an adjective that" into X.
    NARRATIVE_POS,
    /^The (?:word|term|phrase|expression)\s+["“']?(.+?)["”']?\s+(?:means?|refers to)\b/i,
    /^What does\s+["“']?(.+?)["”']?\s+mean\??$/i,
    /^What is the meaning of\s+["“']?(.+?)["”']?\??$/i,
    /^["“']?(.+?)["”']?\s+(?:means?|refers to)\b/i,
    /^["“']?([A-Z][a-zA-Z'’.-]*(?:\s+[a-zA-Z][a-zA-Z'’.-]*){0,4})["”']?\s+is\b/,
  ];
  for (const pattern of patterns) {
    const match = line.match(pattern);
    if (!match) continue;
    const candidate = normalizeTerm(match[1]);
    if (/^(?:this|that|it|these|those|the word|the term|the phrase|the expression|the\b.+|an?\b.+)$/i.test(candidate)) continue;
    if (isTermCandidate(candidate)) return candidate;
  }
  return '';
}

function expandLeadingCompactEntry(text) {
  const newlineAt = text.indexOf('\n');
  const firstLine = newlineAt >= 0 ? text.slice(0, newlineAt) : text;
  const remainingLines = newlineAt >= 0 ? text.slice(newlineAt + 1) : '';
  const posPattern = POS_WORDS.map(value => value.replace(' ', '\\s+')).join('|');
  const match = firstLine.match(new RegExp(
    `^([a-zA-Z][a-zA-Z0-9 '’().-]{0,239}?)\\s*(\\/[^/\\n]{1,80}\\/)\\s*(${posPattern})?\\s*(.*)$`,
    'i',
  ));
  if (!match || !isTermCandidate(match[1])) return text;
  // normalizeTerm drops the homograph index, so a flattened "dove1 /dʌv/ noun …" recovers "dove".
  return [normalizeTerm(match[1]), match[2], match[3] || '', match[4] || '', remainingLines]
    .filter(Boolean).join('\n');
}

function expandCollapsedStructure(text) {
  return text.split('\n').flatMap(line => {
    if (line.length < 240) return [line];
    // Rich-text clipboard APIs sometimes flatten block boundaries. Recover only
    // strong boundaries: sentence-to-heading and joined TitleCase headings.
    const expanded = line
      .replace(/([.!?])(?=[A-Z])/g, '$1\n')
      .replace(/([a-z])([A-Z][a-z])/g, '$1\n$2');
    return expanded.split('\n');
  }).join('\n');
}

function findTerm(lines) {
  for (const line of lines.slice(0, 16)) {
    const labelled = line.match(/^(?:word|term|headword|英文(?:词条)?|单词|词组)\s*[:：]\s*(.+)$/i);
    if (labelled && isTermCandidate(labelled[1])) return normalizeTerm(labelled[1]);
  }
  const posPattern = POS_WORDS.map(value => value.replace(' ', '\\s+')).join('|');
  for (const line of lines.slice(0, 16)) {
    const labelled = line.match(new RegExp(`^(?:${posPattern})\\s*[:：]\\s*([^;]+)`, 'i'));
    if (labelled && isTermCandidate(labelled[1])) return normalizeTerm(labelled[1]).toLowerCase();
  }
  for (const line of lines.slice(0, 16)) {
    const wrapped = line.match(/^Meaning of (.+?)(?: in English)?$/i)
      || line.match(/^(.+?)\s+Definition\s*&\s*Meaning(?:\s*[-|].*)?$/i)
      || line.match(/^Definition of (.+?)(?:\s+in English)?$/i)
      || line.match(/^Translation of (.+?)(?:\s+[–-].*)?$/i)
      || line.match(/^(.+?)\s+in British English$/i)
      || line.match(/^What does\s+["“']?(.+?)["”']?\s+mean\??$/i)
      || line.match(/^What is the meaning of\s+["“']?(.+?)["”']?\??$/i);
    if (wrapped && isTermCandidate(wrapped[1])) {
      const wrappedTerm = normalizeTerm(wrapped[1]);
      const nearby = lines.slice(1, 7).find(value => normalizeTerm(value).toLowerCase() === wrappedTerm.toLowerCase());
      return normalizeTerm(nearby || wrappedTerm).toLowerCase();
    }
  }
  for (const line of lines.slice(0, 16)) {
    const narrative = extractNarrativeHeadword(line);
    if (narrative) return narrative.toLowerCase();
  }
  for (const line of lines.slice(0, 16)) {
    const syllabified = canonicalizeSyllabifiedHeadword(line);
    if (syllabified) return syllabified.toLowerCase();
  }
  const bilingualSentence = lines.length <= 4 && lines.some(line => /[\u3400-\u9fff]/u.test(line))
    ? normalizeTerm(lines[0]) : '';
  if (inferItemType(bilingualSentence) === 'sentence'
      && /^[a-zA-Z][a-zA-Z '’().,!?:;-]*$/.test(bilingualSentence)) return bilingualSentence;
  const candidate = lines.slice(0, 16).find(isTermCandidate);
  if (!candidate) throw new Error('未识别到英文词条，请让粘贴内容包含单词或短语本身。');
  return normalizeTerm(candidate);
}

function extractParts(line) {
  const abbreviated = line.match(YOUDAO_POS);
  if (abbreviated && (!abbreviated[2] || /[\u3400-\u9fff]/.test(abbreviated[2]))) return [ABBREVIATED_POS[abbreviated[1].toLowerCase()]];
  // AI overview introductions can be longer than the metadata limit below.
  // Extract their declared POS only; words in the explanation are not POS labels.
  const narrative = line.match(NARRATIVE_POS);
  if (narrative) {
    const pos = narrative[2].toLowerCase().replace(/\s+/g, ' ');
    return [pos.endsWith('verb') && pos !== 'phrasal verb' ? 'verb' : pos];
  }
  const lower = line.toLowerCase();
  if (line.length > 100 || !/\b(?:as a|word has|noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection|determiner|exclamation|article)\b/i.test(line)) return [];
  const found = [];
  for (const pos of POS_WORDS) {
    if (new RegExp(`\\b${pos.replace(' ', '\\s+')}\\b`, 'i').test(lower)) {
      const base = pos.endsWith('verb') ? (pos === 'phrasal verb' ? pos : 'verb') : pos;
      if (!found.includes(base)) found.push(base);
    }
  }
  return found;
}

function detectFormat(raw, lines, hasChinese) {
  const joined = lines.slice(0, 20).join('\n');
  if (/Cambridge Dictionary|Meaning of .+ in English/i.test(joined)) return 'Cambridge Dictionary';
  if (/Merriam-Webster/i.test(joined)) return 'Merriam-Webster';
  if (/Dictionary\.com/i.test(joined)) return 'Dictionary.com';
  if (/Collins(?:\s+COBUILD)?(?:\s+Advanced Learner's)?\s+Dictionary|in British English/i.test(joined)) return 'Collins Dictionary';
  if (/Britannica Dictionary/i.test(joined)) return 'Britannica Dictionary';
  if (hasChinese) return '双语翻译文本';
  if (/\*\*|^#{1,6}\s|\bAs a (?:Noun|Verb|Adjective|Adverb)\b|\bThe (?:word|term|phrase|expression)\s+.+?\s+(?:has\s+(?:multiple|several|many|two|three)\s+(?:meanings?|uses?)|means?|refers to)\b|^What (?:does\s+.+?\s+mean|is the meaning of\s+.+?)\??$/im.test(raw)) return 'AI / Markdown 词条';
  return '通用词典文本';
}

function extractChinese(lines, term = '') {
  const meanings = [];
  const allowSentenceTranslation = inferItemType(term) === 'sentence' && lines.length <= 4;
  for (const original of lines) {
    if (!/[\u3400-\u9fff]/u.test(original)) continue;
    if (/^(?:英|美)\s*\/[^/]+\/$/.test(original)) continue;
    let line = original
      .replace(/^(?:中文(?:释义|翻译)?|简体中文|中文[（(]简体[）)]|译文|翻译结果|释义)\s*[:：]?\s*/i, '')
      .trim();
    if (!line || /^(?:中文|简体中文|中文[（(]简体[）)]|翻译|译文|释义)$/.test(line)) continue;
    line = line.replace(/^(?:(?:名词|动词|形容词|副词|介词|连词|代词|感叹词)\s*[:：]\s*)+/g, '').trim();
    // A sentence-like paragraph is explanatory context, not a compact translation for this field.
    if (!YOUDAO_POS.test(line) && (line.length > 180 || (/[。！？]/.test(line) && !allowSentenceTranslation))) continue;
    if (line && !meanings.includes(line)) meanings.push(line);
  }
  return meanings.join('；').slice(0, 1000);
}

function extractPhonetic(lines, term) {
  const regional = lines.slice(0, 24).filter(line => /^(?:英|美)\s*\/[^/]+\/$/.test(line));
  if (regional.length) return [...new Set(regional)].join(' · ');
  const slashForms = [];
  for (const line of lines.slice(0, 24)) {
    for (const match of line.matchAll(/\/[^/\n]{1,80}\//g)) {
      const value = match[0].replace(/\s+/g, ' ');
      if (!slashForms.includes(value)) slashForms.push(value);
    }
  }
  if (slashForms.length) return slashForms.join(' · ');
  for (const line of lines.slice(0, 16)) {
    const parenthetical = line.match(/^\(([^()]{2,80})\)$/);
    if (parenthetical && /[ˈˌəɪʊɔɛæɑɒʌθðŋʃʒ]/u.test(parenthetical[1])) return parenthetical[1].trim();
    if (!/[ˈˌ]/u.test(line) || line.length > 100) continue;
    const tokens = line.split(/\s+/);
    const respelling = tokens.findLast(token => /[ˈˌ]/u.test(token));
    if (respelling && respelling.toLowerCase() !== term.toLowerCase()) return respelling;
  }
  return '';
}

function isMetadata(line, term) {
  if (!line || line.toLowerCase() === term.toLowerCase() || TERM_NOISE.test(line)) return true;
  if (/^(?:\d+\s+of\s+\d+|\d+(?:\s+[a-z]|\s+c\s*\(\d+\))?|[A-C]\d?\s*\[[^\]]+\]|\[[CU]\])$/i.test(line)) return true;
  if (/^(?:uk|us|american|your browser doesn't support html5 audio)$/i.test(line)) return true;
  if (/^(?:The word has|As an?\s+(?:Noun|Verb|Adjective|Adverb))\b/i.test(line)) return true;
  if (/^What (?:does\s+.+?\s+mean|is the meaning of\s+.+?)\??$/i.test(line)) return true;
  if (/^(?:Meaning of|Definition of|Translation of).+$/i.test(line) || /Definition\s*&\s*Meaning/i.test(line)) return true;
  if (/^(?:Add to word list(?:\s+Add to word list)?|COBUILD frequency band|Word forms?:|Collins COBUILD\b)/i.test(line)) return true;
  if (/^(?:verb|noun|adjective|adverb):\s*\S+(?:;|$)/i.test(line)) return true;
  if (/^(?:(?:past tense|past participle|present participle|plural|3rd person(?: singular)? present)\s*:\s*[^;]+)(?:;\s*(?:past tense|past participle|present participle|plural|3rd person(?: singular)? present)\s*:\s*[^;]+)*$/i.test(line)) return true;
  if (/^[a-zA-Z-]+(?:ed|ing|s)?(?:;\s*[a-zA-Z-]+(?:ed|ing|s)?)+$/i.test(line)) return true;
  if (/^[\p{L}·-]+\s+[^\s]*[ˈˌ][^\s]*$/u.test(line)) return true;
  return extractParts(line).length > 0 && line.split(/\s+/).length < 9;
}

function splitCambridgeExample(line) {
  const match = line.match(/^([a-z][a-z -]{1,36})\s+([A-Z].+[.!?])$/);
  return match ? match[2] : '';
}

function isAiSectionHeading(line, isBullet, isNumbered) {
  if (isBullet || isNumbered || line.includes(':') || line.split(/\s+/).length > 7) return false;
  if (!/^[A-Z][A-Za-z&/ -]+$/.test(line)) return false;
  return !/^(?:Similar|Synonyms?|Opposite|Antonyms?|Examples?|Origin|Etymology|Translations?|Meaning of\b|Definition of\b|Translation of\b|COBUILD frequency band|Collins COBUILD\b)/i.test(line);
}

function isAiOverviewOrPrompt(line) {
  return /^(?:The word\s+.+?\s+has\s+(?:multiple|several|many|two|three)\s+(?:meanings?|uses?)\b|If you had\b|Tell me\b|Let me know\b|I can provide\b|Would you like\b)/i.test(line);
}

function contextualDefinition(section, line) {
  return section ? `${section} · ${line}` : line;
}

export function parseDictionaryText(raw, {format = 'auto'} = {}) {
  if (!raw.trim()) throw new Error('请先粘贴一条词典或翻译内容。');
  if (raw.length > 60000) throw new Error('内容太长，请每次粘贴一个词条（不超过 60000 字）。');

  const youdao = format === 'youdao' || isYoudaoText(raw);
  const text = stripPronunciationButton(cleanMarkdown(raw));
  const cleaned = expandCollapsedStructure(expandLeadingCompactEntry(youdao ? normalizeYoudaoText(text) : text));
  const lines = cleaned.split('\n').map(tidyLine).filter(Boolean);
  const term = findTerm(lines);
  const chineseMeaning = extractChinese(lines, term);
  const phonetic = extractPhonetic(lines, term);
  const parts = [], definitions = [], examples = [], synonyms = [];
  let inRelated = false;
  let section = '';

  for (const original of lines) {
    const numbered = /^(?:\d+\.\s*)+/.test(original);
    const bullet = /^[-•]\s+/.test(original);
    const colonDefinition = /^:\s+/.test(original);
    const line = original.replace(/^(?:\d+\.\s*)+/, '').replace(/^[-•]\s+/, '').replace(/^:\s+/, '').trim();
    if (numbered || bullet || colonDefinition) inRelated = false;
    if (!line) continue;

    if (isAiSectionHeading(line, bullet, numbered)) {
      section = line;
      continue;
    }

    for (const part of extractParts(line)) if (!parts.includes(part)) parts.push(part);
    if (STOP_SECTION.test(line)) break;
    if (phonetic.split(' · ').includes(line) || /^\/[^/]+\/$/.test(line)) continue;

    const related = line.match(/^(?:Similar|Synonyms?)(?:\s+(?:of\s+\S+))?(?:\s*:\s*(.*))?$/i);
    if (related) {
      inRelated = true;
      if (related[1]) synonyms.push(...related[1].split(/[,;·|]/).map(value => value.trim()).filter(Boolean));
      continue;
    }
    if (/^(?:Opposite|Antonyms?)(?:\s*:.*)?$/i.test(line)) { inRelated = false; continue; }
    if (inRelated) {
      const relatedWords = line.split(/[,;\u00b7|]/).map(value => normalizeTerm(value)).filter(value => value.length <= 80 && isTermCandidate(value));
      synonyms.push(...relatedWords);
      continue;
    }
    if (/[\u3400-\u9fff]/u.test(line) || isMetadata(line, term) || isAiOverviewOrPrompt(line)) continue;
    if (/^['“"].+['”"]$/.test(line)) { examples.push(line.slice(1, -1)); continue; }
    const cambridgeExample = splitCambridgeExample(line);
    if (cambridgeExample) { examples.push(cambridgeExample); continue; }
    if (/^(?:(?:dated|informal|formal|archaic|literary|slang|British|North American|technical)(?:\s*[•·,/\s]\s*|$))+$/i.test(line)) continue;
    if (/[a-zA-Z]/.test(line) && line.split(/\s+/).length >= 3) definitions.push(contextualDefinition(section, line));
  }

  if (!definitions.length && !chineseMeaning) {
    throw new Error('未识别到释义，请复制包含英文释义或中文翻译的完整内容。');
  }
  const detectedFormat = youdao ? '有道词典' : detectFormat(raw, lines, Boolean(chineseMeaning));
  const warningParts = [];
  if (!chineseMeaning) warningParts.push('未检测到中文释义，请补充。');
  if (!phonetic) warningParts.push('未检测到音标。');
  if (youdao && /(?:…|\.{3})\s*$/m.test(cleaned)) warningParts.push('释义可能被截断，请在有道中点“查看全部”后重新复制，或手动补全。');
  return {
    term,
    phonetic,
    part_of_speech: parts.join('; '),
    chinese_meaning: chineseMeaning,
    english_definition: [...new Set(definitions)].join('\n'),
    definition_count: new Set(definitions).size,
    source_sentence: [...new Set(examples)].join('\n'),
    synonyms: [...new Set(synonyms)],
    item_type: inferItemType(term),
    detected_format: detectedFormat,
    warnings: warningParts.join(' '),
    notes: '粘贴原文（已去除链接与格式标记）：\n' + cleaned.trim(),
  };
}
