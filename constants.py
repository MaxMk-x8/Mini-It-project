FACULTIES = [
    ('FCI', 'Faculty of Computer Information'),
    ('FOM', 'Faculty of Management')
]

FACULTY_CODES = [code for code, _ in FACULTIES]

import re

BLOCKED_WORDS = [
    'fuck', 'fucking', 'fucker', 'motherfucker', 'shit', 'bullshit', 'bitch', 'bastard',
    'asshole', 'dick', 'cock', 'pussy', 'cunt', 'idiot', 'moron', 'stupid', 'dumbass',
    'loser', 'donkey', 'sial', 'bangsat', 'pukimak', 'bodoh', 'babi', 'anjing', 'celaka',
    'palat', 'lancau', 'kimak'
]

BLOCKED_PHRASES = [
    'fuck you', 'shut the fuck up', 'kill yourself', 'go kill yourself'
]

def contains_profanity(text):
    """
    Returns (True, matched_term) if text contains prohibited words or phrases.
    Uses regex word boundaries (\b) to prevent false positives (e.g. 'assessment').
    """
    if not text:
        return False, None

    clean_text = ' '.join(str(text).split())

    # Check multi-word phrases first
    for phrase in BLOCKED_PHRASES:
        pattern = r'\b' + re.escape(phrase) + r'\b'
        if re.search(pattern, clean_text, re.IGNORECASE):
            return True, phrase

    # Check individual words with word boundaries
    for word in BLOCKED_WORDS:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, clean_text, re.IGNORECASE):
            return True, word

    return False, None

