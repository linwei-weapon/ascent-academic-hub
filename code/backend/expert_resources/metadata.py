"""Resource configuration hints; business algorithms and runtime manifests stay unchanged."""
from .tasks import task_definitions


def policy_domains(skill_id):
    """Policy editor scope comes from registered consumers, not card categories."""
    domains = {
        'T-RECOGNITION': ('transfer',), 'T-POLICY': ('transfer',),
        'T-POLICY-SCENARIO': ('transfer',), 'R-PREPARE': ('recommendation',),
        'R-RANK': ('recommendation',), 'R-CHECK': ('recommendation',),
        'R-SCENARIO': ('recommendation',), 'G-CHECK': ('graduation', 'degree'),
        'P-PATH': ('support',), 'P-CHANGE': ('support',),
    }
    result = []
    for task in task_definitions():
        if task['skillId'] != skill_id or 'ruleRef' not in task['inputSchema'].get('properties', {}):
            continue
        for domain in domains.get(task['taskId'], ()):
            if domain not in result:
                result.append(domain)
    return result
