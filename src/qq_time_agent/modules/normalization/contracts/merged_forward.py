"""Provider-neutral bounded QQ merged-forward normalization contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MergedForwardNode:
    author_label: str
    text: str
    children: tuple["MergedForwardNode", ...] = ()


@dataclass(frozen=True, slots=True)
class MergedForwardContent:
    text: str
    node_count: int
    parser_version: str


class MergedForwardParserPort(Protocol):
    def parse(self, nodes: tuple[MergedForwardNode, ...]) -> MergedForwardContent: ...
