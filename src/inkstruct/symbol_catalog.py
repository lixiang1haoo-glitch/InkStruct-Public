"""Current symbol classes. Each encoded character has one class per writing style."""

import string

from .punctuation import capture_character

LETTERS = string.ascii_uppercase + string.ascii_lowercase
SYMBOL_GROUPS = {
    "latin_upright": ("英文正体", LETTERS, "upright"),
    "latin_italic": ("英文斜体", LETTERS, "italic"),
    "digits": ("数字", string.digits, "unspecified"),
    "greek": ("希腊字母", "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω", "unspecified"),
    "greek_variants": ("希腊字母 · 变体", "ϐϑϕϖϱϵϰς", "unspecified"),
    "brackets": ("括号、书名号与定界符", "()[]{}（）［］｛｝【】《》〈〉「」『』|", "unspecified"),
    "punctuation": ("标点与连接符", ".,:;?!．，：；？！。、\"'“”‘’-–—…～", "unspecified"),
    "units": ("单位与量值符号", "%％‰°′″℃", "unspecified"),
    "operators": ("数学符号", "+−×÷=≠≈≡±∓<>≤≥∞∑∏∫∮√∂∇∈∉∋⊂⊃⊆⊇∪∩∅∀∃¬∧∨⇒⇔→←↔↑↓∝∠⊥∥·⋅/*∗∶∘ℏ", "unspecified"),
}

PREVIEWS = {
    "latin_upright": "A B C … Z / a b c … z",
    "latin_italic": "A B C … Z / a b c … z",
    "greek": "Α Β Γ … Ω / α β γ … ω",
    "brackets": "() [] {} 【】 《》 〈〉 「」 『』 | …",
    "punctuation": ", . ? ! 。 、 “ ” - – — … ～",
    "operators": "+ − × ÷ = ∑ ∫ √ ∈ ∗ ℏ …",
}


def symbol_group(character, style="unspecified"):
    if len(character) != 1:
        return "other"
    for key, (_, characters, writing_style) in SYMBOL_GROUPS.items():
        if character in characters and (writing_style == style or writing_style == "unspecified"):
            return key
    return "latin_unspecified" if character in LETTERS else "other"


def capture_groups():
    return {key: (label, "".join(dict.fromkeys(map(capture_character, characters))), style)
            for key, (label, characters, style) in SYMBOL_GROUPS.items()}


def character_preview(group, characters, limit=12):
    return PREVIEWS.get(group) or (" ".join(characters[:limit]) + (" …" if len(characters) > limit else ""))
