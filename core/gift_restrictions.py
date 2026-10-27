"""Conservative matching of explicit text rules; no image recognition."""
import re
import unicodedata

_PATTERNS = [
    re.compile(r'(?:ギフト|バラ|薔薇|ローズ|1コイン|一コイン|1円)(?:だけ)?(?:縛り|しばり)'),
    re.compile(r'(?:バラ|薔薇|ローズ|1コイン|一コイン|1円)(?:ギフト)?(?:のみ|だけ)(?:で|の|限定|バトル|勝負|お願いします|$)'),
    re.compile(r'(?:バラ|薔薇|ローズ|1コイン|一コイン|1円)(?:ギフト)?限定'),
]
_NEGATION = re.compile(r'(?:縛り|しばり)(?:は)?(?:なし|無し|じゃない|ではない|ありません|ない)|縛り解除')

def match_gift_restriction(texts):
    for text in texts or []:
        text = unicodedata.normalize('NFKC', str(text))
        for line in text.splitlines():
            line = re.sub(r'\s+', '', line)
            if _NEGATION.search(line):
                continue
            for pattern in _PATTERNS:
                match = pattern.search(line)
                if match:
                    return match.group(0)
    return None
