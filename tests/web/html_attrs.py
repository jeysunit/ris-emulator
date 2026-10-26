"""画面の HTML の確かめ用：タグの属性を、書かれた順に依らず調べる."""

from __future__ import annotations

from html.parser import HTMLParser


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def has_tag(page: str, tag: str, **attrs: str | None) -> bool:
    """`<tag>` で、指定の属性が全部ある（値が None なら、値の無い属性）ものが1つでもあるか.

    class は空白で区切った語の集まりとして見る（`class="a b"` は `a` と `b` のどちらでも当たる）。
    属性の順と、ほかの属性があるかどうかは問わない。
    """
    collector = _Collector()
    collector.feed(page)
    for name, found in collector.tags:
        if name != tag:
            continue
        if all(_matches(found, key, value) for key, value in attrs.items()):
            return True
    return False


def _matches(found: dict[str, str | None], key: str, value: str | None) -> bool:
    if key not in found:
        return False
    if key == "class" and value is not None:
        return set(value.split()) <= set((found[key] or "").split())
    return found[key] == value
