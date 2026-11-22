"""Guess speaker names from self-introductions ("ben Selim", "my name is Ana")
and from being addressed ("Umut sen de bir şey söyle", "Günaydın Ece", "Ece, rapor hazır mı?",
"Ne dersin Ece?" -> next different speaker is the named person)."""
from __future__ import annotations

import re

UP, LO = "A-ZÇĞİÖŞÜ", "a-zçğıöşü"
NAME = rf"([{UP}][{LO}]+)"
END = r"(?![\w'’])"  # "Ankara'da" is a place with a suffix, not a name

SELF_INTRO = [
    re.compile(rf"\b(?:[Bb]enim\s+)?(?:ad[ıi]m|ismim)\s+{NAME}{END}"),
    # "ben Selim", "Ben de konuşmacı olarak Bahadır" (up to 3 lowercase words in between)
    re.compile(rf"\b[Bb]en(?:\s+[{LO}]+){{0,3}}\s+{NAME}{END}"),
    re.compile(rf"\b(?:[Mm]y name is|[Ii]'m|[Ii] am|[Tt]his is)\s+{NAME}{END}"),
]
# speech-to-text often writes a whole sentence in lower case: "hi my name is melisa"
LOWER_INTRO = re.compile(rf"\b(?:my name is|ad[ıi]m|ismim)\s+([{LO}]{{3,}}){END}")
LOWER_STOP = {"not", "also", "now", "here", "just", "very", "john", "ben", "bir", "the", "and", "was", "is", "are"}
GREETINGS = "İyi akşamlar|Hoş geldin|Günaydın|Merhaba|Selam|Teşekkürler|Sağ ol|Good morning|Hello|Hi|Thanks"
HONORIFIC = r"(?:\s+(?:[Bb]ey|[Hh]anım|[Hh]ocam))?"  # "Ece Hanım" -> the name is Ece
ADDRESS = [
    # "Umut sen de bir şey söyle", "Ece, buyur"
    re.compile(rf"\b{NAME},?\s+(?:sen\b|siz\b|sıra\s+sende|söz\s+sende|buyur|what about you|your turn|go ahead)"),
    # "Günaydın Ece", "Merhaba Ece", "İyi akşamlar Ece", "Good morning Ece"
    re.compile(rf"\b(?:{GREETINGS})\s*,?\s+{NAME}{END}"),
    # "Ece, sen ne düşünüyorsun?", "Ece Hanım, bu rapor hazır mı?"
    re.compile(rf"^\s*{NAME}{HONORIFIC},"),
    # "Bu rapor hazır mı, Ece?", "Ne dersin Ece?" - only a question to that person
    re.compile(rf"{NAME}{HONORIFIC}\s*\?\s*$"),
]
INTRO_WINDOW = 60  # introductions happen near the start of what someone says
NOT_NAMES = {"Türkçe", "İngilizce", "Bey", "Hanım", "Hocam", "Tamam", "Evet", "Hayır", "Not", "Sorry", "Here",
             "Fine", "Good", "Glad", "Happy", "Ready", "Back", "Just", "Very", "Also", "Still", "So", "Sure", "Well",
             "English", "Turkish", "Student", "Teacher"}
# ordinary sentence starters that must not be mistaken for a name someone is called by
NOT_ADDRESS = {"Bugün", "Yarın", "Dün", "Yani", "Peki", "Şimdi", "Aslında", "Ama", "Fakat", "Sonra", "Önce",
               "Bence", "Bir", "Bu", "Şu", "O", "Biz", "Siz", "Onlar", "Ben", "Sen", "Hadi", "Haydi", "Evet",
               "Hayır", "Tamam", "Tabii", "Olur", "Lütfen", "Ne", "Neden", "Nasıl", "Kim", "Hangi", "Nerede",
               "Merhaba", "Selam", "Günaydın", "Teşekkürler", "Hoş", "Sağ",
               "Hello", "Hi", "Thanks", "Morning",
               "Okay", "Yes", "No", "Then", "Now", "Today", "Well", "So", "But", "And", "Please", "What", "Why",
               "How", "Who", "Where", "You", "Your", "We", "They", "Arkadaşlar", "Beyler", "Hanımlar", "Efendim",
               "Hocam", "Herkes", "Ekip", "Sevgili", "Değerli", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma",
               "Cumartesi", "Pazar", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
               "Eylül", "Ekim", "Kasım", "Aralık", "Friends", "Guys", "Everyone", "Team",
               # interjections and short answers that start a sentence like a name would ("İyi, güzel.")
               "İyi", "Güzel", "Harika", "Süper", "Doğru", "Aynen", "Kesinlikle", "Elbette", "Valla", "Vallahi",
               "Bak", "Bakın", "Bakalım", "Şey", "Hmm", "Hı", "Ha", "Ah", "Oh", "Of", "Eee", "Pardon", "Kusura",
               "Merak", "Yok", "Var", "Belki", "Galiba", "Herhalde", "Gerçekten", "Zaten", "Hani", "İşte", "Neyse",
               "Teşekkür", "Rica", "Hoşça", "Görüşürüz", "Tabi", "Anladım", "Tamamdır", "Oldu", "Olmaz", "Gel", "Gelin",
               "Good", "Great", "Nice", "Right", "Sure", "Thanks", "Sorry", "Hey", "Oh", "Wow", "Hmm", "Look", "Listen"}


def _is_default(label: str | None, spk: int) -> bool:
    return not label or label in (f"Speaker {spk + 1}", f"Konuşmacı {spk + 1}")


def intro_names(text: str) -> list[str]:
    """Every name the text introduces ("I am Ece. And I am Işıl" -> both), only near its start."""
    out: list[str] = []
    for rx in SELF_INTRO:
        for m in rx.finditer(text):
            if m.start() < INTRO_WINDOW and m.group(1) not in NOT_NAMES and m.group(1) not in out:
                out.append(m.group(1))
    for m in LOWER_INTRO.finditer(text):
        nm = m.group(1).capitalize()
        if m.start() < INTRO_WINDOW and m.group(1) not in LOWER_STOP and nm not in NOT_NAMES and nm not in out:
            out.append(nm)
    return out


def detect_intros(segments: list[dict]) -> dict[int, str]:
    """Only the clear self-introductions, one name per speaker ("my name is X"): what a voice may be learned from.
    A speaker who introduced itself under two names is several people and is left out."""
    found: dict[int, list[str]] = {}
    for seg in segments:
        for nm in intro_names(seg["text_edited"]):
            if nm not in found.setdefault(seg["speaker"], []):
                found[seg["speaker"]].append(nm)
    return {spk: names[0] for spk, names in found.items() if len(names) == 1}


def address_name(text: str) -> str | None:
    """The person the text speaks to ("Umut sen de...", "Günaydın Ece", "Ece, rapor hazır mı?",
    "Ne dersin Ece?"), or None. A self-introduction ("Merhaba ben Selim") is not an address."""
    for rx in ADDRESS:
        m = rx.search(text)
        if m and m.group(1) not in NOT_NAMES and m.group(1) not in NOT_ADDRESS:
            return m.group(1)
    return None


def detect_names(segments: list[dict], speakers: dict) -> dict[int, str]:
    """Return {speaker_index: name} for speakers still labelled 'Speaker N'.
    A speaker that introduces itself under two different names is several people the voice
    separation could not tell apart: it gets no name at all instead of a wrong one."""
    intros: dict[int, list[str]] = {}
    weak: dict[int, str] = {}
    for i, seg in enumerate(segments):
        text, spk = seg["text_edited"], seg["speaker"]
        for rx in SELF_INTRO:
            m = rx.search(text)
            if m and m.start() < INTRO_WINDOW and m.group(1) not in NOT_NAMES:
                if m.group(1) not in intros.setdefault(spk, []):
                    intros[spk].append(m.group(1))
                break
        m = LOWER_INTRO.search(text)
        if m and m.start() < INTRO_WINDOW and m.group(1) not in LOWER_STOP:
            nm = m.group(1)[0].upper().replace("i", "İ") + m.group(1)[1:] if m.group(1)[0] == "i" else m.group(1).capitalize()
            if nm not in NOT_NAMES and nm not in intros.setdefault(spk, []):
                intros[spk].append(nm)
        nm = address_name(text)
        if nm:
            nxt = next((s for s in segments[i + 1:] if s["speaker"] != spk), None)
            if nxt is not None:
                weak.setdefault(nxt["speaker"], nm)
    crowded = {spk for spk, names in intros.items() if len(names) > 1}
    strong = {spk: names[0] for spk, names in intros.items() if len(names) == 1}
    result: dict[int, str] = {}
    used = {v for k, v in speakers.items() if not _is_default(v, int(k))}
    for spk, name in [*strong.items(), *((k, v) for k, v in weak.items() if k not in crowded)]:
        if spk in result or name in used or not _is_default(speakers.get(str(spk)), spk):
            continue
        result[spk] = name
        used.add(name)
    return result
