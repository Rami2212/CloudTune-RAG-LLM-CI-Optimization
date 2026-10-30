"""Run only the ten newly added scenarios in the existing scenario batch."""
from run_pattern_batch import main
from scenario_experiments import ScenarioBatch
from scenario_replay import NEW_PATTERNS


class NewScenarioBatch(ScenarioBatch):
    supported_patterns = NEW_PATTERNS


if __name__ == "__main__":
    raise SystemExit(main(NewScenarioBatch, "scenario-three-runs-v1", __doc__))
