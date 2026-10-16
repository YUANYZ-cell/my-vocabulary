// Keep local capture and dictionary-paste detection consistent with the repository.
export function inferItemType(term) {
  const clean = String(term || '').trim().replace(/\s+/g, ' ');
  // This lexical compound also has an open spelling; spaces alone do not make it a phrase.
  if (clean.toLowerCase() === 'game changer') return 'word';
  if (!clean.includes(' ')) return 'word';
  return clean.length >= 35 && clean.split(' ').length >= 5 ? 'sentence' : 'phrase';
}

export function updateCaptureType(form) {
  const choice = form.elements.type_choice.value;
  form.elements.item_type.value = choice === 'auto' ? inferItemType(form.elements.term.value) : choice;
  return form.elements.item_type.value;
}
