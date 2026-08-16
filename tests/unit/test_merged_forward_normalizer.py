import pytest

from qq_time_agent.modules.normalization.contracts import AssetParseError, MergedForwardNode
from qq_time_agent.modules.normalization.infrastructure.merged_forward import (
    MergedForwardNormalizer,
)


def test_merged_forward_preserves_stable_depth_first_order() -> None:
    parser = MergedForwardNormalizer(4, 10, 1000)
    result = parser.parse(
        (
            MergedForwardNode(
                "Alice",
                "  确认  deadbeef-1  ",
                (MergedForwardNode("Bob", "Meeting at 10:00"),),
            ),
            MergedForwardNode("Carol", "Second root"),
        )
    )
    assert result.text.splitlines() == [
        "[1] Alice: 确认 deadbeef-1",
        "[1.1] Bob: Meeting at 10:00",
        "[2] Carol: Second root",
    ]
    assert result.node_count == 3


@pytest.mark.parametrize(
    ("parser", "nodes", "failure"),
    (
        (
            MergedForwardNormalizer(1, 10, 1000),
            (MergedForwardNode("A", "x", (MergedForwardNode("B", "y"),)),),
            "MergedForwardDepthLimit",
        ),
        (
            MergedForwardNormalizer(4, 1, 1000),
            (MergedForwardNode("A", "x"), MergedForwardNode("B", "y")),
            "MergedForwardNodeLimit",
        ),
        (
            MergedForwardNormalizer(4, 10, 5),
            (MergedForwardNode("A", "long output"),),
            "AssetOutputLimit",
        ),
    ),
)
def test_merged_forward_enforces_bounded_tree_limits(
    parser: MergedForwardNormalizer,
    nodes: tuple[MergedForwardNode, ...],
    failure: str,
) -> None:
    with pytest.raises(AssetParseError, match=failure):
        parser.parse(nodes)


def test_merged_forward_rejects_cycles() -> None:
    node = MergedForwardNode("A", "x")
    object.__setattr__(node, "children", (node,))
    with pytest.raises(AssetParseError, match="MergedForwardCycle"):
        MergedForwardNormalizer(4, 10, 1000).parse((node,))
