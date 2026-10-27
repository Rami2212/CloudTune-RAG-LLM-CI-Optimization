"""Run ten controlled CI scenarios, including six synthetic service-policy replays."""
from run_pattern_batch import main
from scenario_experiments import ScenarioBatch

if __name__ == "__main__":
    raise SystemExit(main(ScenarioBatch, "scenario-three-runs-v1", __doc__))
