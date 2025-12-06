import codecs
import functools
import typing


def decode(data: bytes) -> typing.Optional[str]:
    """
    様々なエンコーディングでデコードし、最初にデコードに成功した文字列で返す。

    :param data: 入力データ
    :type data: bytes
    :return: Description
    :rtype: Optional[str]
    """
    encodings_to_try = [
        "utf-8",
        "cp932",        # Windows日本語
        "shift_jis",
        "euc_jp",
        "iso2022_jp",
        "latin-1",
    ]
    for codec in encodings_to_try:
        try:
            return data.decode(codec, errors="strict")
        except UnicodeDecodeError:
            continue
    return None
