"""Compatibility entry point for the repeatable route-feasibility runner."""
from run_scenario import run

if __name__ == '__main__':
    result = run('scenarios/baseline.json', 'runs/baseline')
    print(result['summary'])
