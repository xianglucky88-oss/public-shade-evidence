"""街道遮阴与公共空间数据"""

from . import queue_coverage, walk_exposure, photo_evidence, construction_service, shade_contributions
from .contract import Row

PIPELINES = {
    "queue-coverage": queue_coverage.build_facts,
    "walk-exposure": walk_exposure.build_facts,
    "photo-evidence": photo_evidence.build_facts,
    "construction-service": construction_service.build_facts,
    "shade-contributions": shade_contributions.build_facts,
}

def process(pipeline: str, data: Row) -> list[Row]:
    """Validate and transform an independent input dataset into keyed facts."""
    if pipeline not in PIPELINES:
        raise ValueError(f"unknown pipeline: {pipeline}")
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    return PIPELINES[pipeline](data)
