from dataclasses import dataclass, field

from .instance import ProblemInstance
from .classes.block import Block


@dataclass
class Solution:
    instance: ProblemInstance
    blocks: dict[str, Block] = field(default_factory=dict)
    unassigned_trip_ids: list[str] = field(default_factory=list)

    def add_block(self, block: Block) -> None:
        self.blocks[block.id] = block

    def num_blocks(self) -> int:
        return len(self.blocks)