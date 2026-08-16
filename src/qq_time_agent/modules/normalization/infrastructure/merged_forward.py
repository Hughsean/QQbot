"""Stable-order bounded normalizer for official merged-forward node trees."""

from qq_time_agent.modules.normalization.contracts import (
    AssetParseError,
    MergedForwardContent,
    MergedForwardNode,
)

PARSER_VERSION = "qq-merged-forward-v1"


class MergedForwardNormalizer:
    def __init__(self, max_depth: int, max_nodes: int, max_output_chars: int) -> None:
        if min(max_depth, max_nodes, max_output_chars) < 1:
            raise ValueError("merged-forward limits must be positive")
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._max_output_chars = max_output_chars

    def parse(self, nodes: tuple[MergedForwardNode, ...]) -> MergedForwardContent:
        lines: list[str] = []
        seen: set[int] = set()
        count = 0

        def visit(node: MergedForwardNode, path: tuple[int, ...]) -> None:
            nonlocal count
            identity = id(node)
            if identity in seen:
                raise AssetParseError("MergedForwardCycle")
            if len(path) > self._max_depth:
                raise AssetParseError("MergedForwardDepthLimit")
            count += 1
            if count > self._max_nodes:
                raise AssetParseError("MergedForwardNodeLimit")
            author = " ".join(node.author_label.split()) or "unknown"
            text = " ".join(node.text.split())
            prefix = ".".join(str(value) for value in path)
            line = f"[{prefix}] {author}: {text}"
            if sum(len(value) + 1 for value in lines) + len(line) > self._max_output_chars:
                raise AssetParseError("AssetOutputLimit")
            lines.append(line)
            seen.add(identity)
            try:
                for index, child in enumerate(node.children, start=1):
                    visit(child, (*path, index))
            finally:
                seen.remove(identity)

        for index, node in enumerate(nodes, start=1):
            visit(node, (index,))
        return MergedForwardContent("\n".join(lines), count, PARSER_VERSION)
