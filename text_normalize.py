"""text_normalize.py — Normalize text to catch filtered words disguised with leetspeak,
zero-width chars, symbols, or extra spaces."""
import re
import unicodedata

LEET = {
    '4': 'a', '@': 'a',
    '3': 'e',
    '1': 'i', '!': 'i', '|': 'i',
    '0': 'o',
    '5': 's', '$': 's',
    '7': 't',
    '6': 'g',
    '8': 'b',
    '9': 'g',
}

ZERO_WIDTH = re.compile(
    r'[\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\uFEFF\u00ad]'
)


def normalize(text: str) -> str:
    """Return a cleaned, lowercase string suitable for word-filter matching."""
    text = ZERO_WIDTH.sub('', text)
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    result = []
    for ch in text:
        result.append(LEET.get(ch, ch))
    text = ''.join(result)
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def contains_banned(text: str, banned_words: list[str]) -> str | None:
    """Return the first matched banned word, or None."""
    normalized = normalize(text)
    normalized_nospace = normalized.replace(' ', '')
    for word in banned_words:
        w = normalize(word)
        if w in normalized or w in normalized_nospace:
            return word
    return None


def caps_ratio(text: str) -> float:
    """Return fraction of alphabetic characters that are uppercase."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 8:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def count_emojis(text: str) -> int:
    """Count emoji characters in text."""
    count = 0
    for ch in text:
        cp = ord(ch)
        if (0x1F600 <= cp <= 0x1F64F or 0x1F300 <= cp <= 0x1F5FF or
                0x1F680 <= cp <= 0x1F6FF or 0x2600 <= cp <= 0x27BF or
                0x1F900 <= cp <= 0x1F9FF or 0xFE00 <= cp <= 0xFE0F):
            count += 1
    return count


def extract_urls(text: str) -> list[str]:
    return re.findall(r'https?://[^\s]+', text)
