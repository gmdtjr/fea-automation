QUALITY_RULES = {
    "case1": {
        "max_aspect_ratio": 10.0,
        "target_aspect_ratio": 3.0,
        "min_elements_through_thickness": 4,
        "max_element_count": 300_000,
        "min_jacobian": 0.0,
    },
    "case2": {
        "max_aspect_ratio": 10.0,
        "min_elements_through_thickness": 4,
        "max_element_count": None,
        "min_jacobian": 0.0,
    },
}


def check_quality(mesh_result: dict, case: str) -> dict:
    rules = QUALITY_RULES[case]
    issues = []

    if mesh_result["max_aspect_ratio"] > rules["max_aspect_ratio"]:
        issues.append({
            "type": "aspect_ratio",
            "value": mesh_result["max_aspect_ratio"],
            "limit": rules["max_aspect_ratio"],
            "action": "reduce_seed_size",
        })

    if (
        rules["max_element_count"]
        and mesh_result["element_count"] > rules["max_element_count"]
    ):
        issues.append({
            "type": "element_count",
            "value": mesh_result["element_count"],
            "limit": rules["max_element_count"],
            "action": "increase_seed_size",
        })

    if mesh_result.get("min_jacobian", 1.0) < rules["min_jacobian"]:
        issues.append({
            "type": "jacobian",
            "value": mesh_result["min_jacobian"],
            "limit": rules["min_jacobian"],
            "action": "reduce_seed_size",
        })

    return {"pass": len(issues) == 0, "issues": issues}


def adjust_seed_size(current_size: float, issues: list) -> float:
    """Auto-adjust seed size on quality failure (called up to 5 times by orchestrator)."""
    for issue in issues:
        if issue["action"] == "reduce_seed_size":
            return round(current_size * 0.7, 2)
        if issue["action"] == "increase_seed_size":
            return round(current_size * 1.3, 2)
    return current_size
