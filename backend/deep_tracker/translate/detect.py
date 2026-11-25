"""AIを使わない軽量な言語判定。

ひらがな・カタカナの比率で日本語かを判定する。漢字のみの中国語の記事も「日本語以外」として
翻訳対象にするため、漢字は日本語の根拠にしない。
"""

import html
import re

LANG_JA = "ja"
LANG_OTHER = "other"

# 仮名の比率がこれ以上なら日本語とみなす。
# 分母は「仮名＋漢字＋ハングルの文字数＋ラテン文字等の単語数」
# （英単語を1文字ずつ数えると、製品名の多い日本語記事が日本語以外になるため単語で数える）
KANA_RATIO_THRESHOLD = 0.15

_TAG = re.compile(r"<[^>]*>")
_KANA = re.compile(r"[ぁ-ゟ゠-ヿㇰ-ㇿｦ-ﾟ]")
# CJK統合漢字（拡張A含む）・互換漢字
_KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")
# 仮名・漢字・ハングル以外の文字（ラテン文字・キリル文字など）からなる単語
_WORD = re.compile(
    r"[^\W\d_ぁ-ゟ゠-ヿㇰ-ㇿｦ-ﾟ"
    r"㐀-䶿一-鿿豈-﫿가-힯ᄀ-ᇿ㄰-㆏]+"
)


def strip_html(text: str) -> str:
    return html.unescape(_TAG.sub(" ", text))


def detect_language(title: str | None, content: str | None) -> str:
    """タイトル＋本文から言語を判定し、"ja" か "other" を返す。

    判定に使える文字が無い（数字・記号のみ、空）場合は翻訳不要として "ja" を返す。
    """
    text = strip_html(f"{title or ''}\n{content or ''}")
    kana = len(_KANA.findall(text))
    units = kana + len(_KANJI.findall(text)) + len(_HANGUL.findall(text))
    units += len(_WORD.findall(text))
    if units == 0:
        return LANG_JA
    return LANG_JA if kana / units >= KANA_RATIO_THRESHOLD else LANG_OTHER
