"""Conservative, deterministic checks. These do not prove semantic entailment."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from .errors import WorkError

NUMBER = re.compile(r'(?<![\d.,])(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?')
UNIT = re.compile(r'\s*(%|퍼센트|kWh|MWh|Wh|kW|MW|W|kJ|MJ|J|kV|V|mA|A|kg|km|cm|mm|m|ms|s|Hz|MHz|GHz|°C|℃|만원|억원|원|시간|개월|학년|학기|명|개|주|년|월|일|분|초|배|세)(?![A-Za-z])')
COMPOUND = re.compile(r'(?:\s*[/·*^]\s*[A-Za-z0-9⁻−+-]+)*')
ABSOLUTE = re.compile(r'항상|무조건|예외\s*없이|아무\s*조건\s*없이')


def normalized(text):
    text = unicodedata.normalize('NFC', text)
    supers = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻','0123456789+-')
    subs = str.maketrans('₀₁₂₃₄₅₆₇₈₉₊₋','0123456789+-')
    text = re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+', lambda m:'^'+m[0].translate(supers), text)
    text = re.sub(r'[₀₁₂₃₄₅₆₇₈₉₊₋]+', lambda m:'_'+m[0].translate(subs), text)
    text = re.sub(r'\\(?:mathrm|text|operatorname)\{([^{}]*)\}', r'\1', text)
    return text.replace('\\,', ' ').replace('\\%', '%').replace('퍼센트', '%')


def quantities(text):
    text = normalized(text)
    for match in NUMBER.finditer(text):
        value = match[0]
        # A hyphen between values is a range separator, not a negative sign.
        if value.startswith('-') and match.start() and text[match.start()-1].isdigit():
            value = value[1:]
        unit = UNIT.match(text, match.end())
        end = unit.end() if unit else match.end()
        compound = COMPOUND.match(text,end) if unit else None
        full_unit = unit[1]+re.sub(r'\s+','',compound[0]) if unit else ''
        if compound:end=compound.end()
        before, after = text[max(0, match.start()-12):match.start()], text[end:end+12]
        flags = set()
        if re.search(r'(?<![가-힣A-Za-z])(?:약|대략)\s*$', before) or re.match(r'\s*(?:내외|정도)', after): flags.add('approx')
        if re.search(r'(?:최대|≤)\s*$', before) or re.match(r'\s*이하', after): flags.add('upper')
        if re.search(r'<\s*$', before) or re.match(r'\s*미만', after): flags.add('upper_exclusive')
        if re.search(r'(?:최소|≥)\s*$', before) or re.match(r'\s*이상', after): flags.add('lower')
        if re.search(r'>\s*$', before) or re.match(r'\s*초과', after): flags.add('lower_exclusive')
        if re.search(r'\d[^.!?\n]*[~∼–—-]\s*$', before) or re.match(r'\s*[~∼–—-]\s*\d', after): flags.add('range')
        if re.match(r'\s*(?:에서|부터)\s*\d',after) or (re.search(r'\d.*(?:에서|부터)\s*$',before) and re.match(r'\s*까지',after)):
            flags.add('range')
        elif re.match(r'\s*까지',after):flags.add('upper')
        elif re.match(r'\s*부터',after):flags.add('lower')
        yield Decimal(value.replace(',', '')), full_unit, frozenset(flags)


def check_grounding(text, evidence, code='unsupported_claim'):
    """Reject new numeric values/units/bounds and obvious added absolutes.

    Evidence must be the cited source text, never other uncited paragraphs.
    Rewording, attribution, causality and negation still require human review.
    """
    originals = [normalized(value) for value in evidence]
    candidates = [q for value in originals for q in quantities(value)]
    for value, unit, flags in quantities(text):
        if not any(value == number and (not unit or unit == original_unit) and flags == original_flags
                   for number, original_unit, original_flags in candidates):
            raise WorkError(code, f'인용한 근거에서 수치·단위·범위를 확인할 수 없습니다: {value}{unit}. 원문 표기와 적용 조건을 유지해 주세요.')
    for match in ABSOLUTE.finditer(text):
        # "항상 성립하지 않는다" is not an unconditional assertion.
        tail = re.split(r'[,.!?。！？\n]|하며|이고|지만|면서', text[match.end():], maxsplit=1)[0][:24]
        if re.search(r'않|아니|없|못', tail):
            continue
        if not any(match[0] in original for original in originals):
            raise WorkError(code, '인용 근거에 없는 무조건적 표현이 추가되었습니다. 조건·예외를 복원해 주세요.')
