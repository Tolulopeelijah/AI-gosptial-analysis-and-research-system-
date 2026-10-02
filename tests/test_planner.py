from agent.planner import OpenAIPlanner
from agent.config import settings
from agent.orchestration import Orchestrator
from agent.tools.registry import build_tool_registry

plan_debug = True
orchestrator_debug = True 

# planning 
planner = OpenAIPlanner(settings.OPENAI_MODEL, settings.OPENAI_API_KEY)
plan = planner.plan(query = "Find septic systems within 2 km of floodplain areas")

if plan_debug:
    print('PLANNING OUTPUT')
    print('=' * 100)
    print(f"goal: {plan['plan'].goal}")
    print('=' * 100)

    print("steps: ")

    for i in plan['plan'].steps:
        print(i)

    print('=' * 100)
    print(f"kind: {plan['kind']}")
    print('=' * 100)

    print(f"reason: {plan['reason']}")


# execution 
tools_registry = build_tool_registry()
orchestrator = Orchestrator(tool_registry=tools_registry, max_retries=1)
results = orchestrator.execute(plan = plan['plan'], query_id='id')

if orchestrator_debug:
    
    print('\nORCHESTRATION OUTPUTT')
    print('=' * 100)

    for result in results.items():
        print(result)
        print('=' * 100)
        

