"""Validate shipped resource definitions, generated bundles, links and coverage."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / 'code'))
from backend.expert_resources.runtime import HANDLERS
from backend.expert_resources.tasks import PROCESSORS, task_definitions
TASKS = {item['taskId']: item for item in task_definitions()}
INPUTS = {'limit', 'taskId'} | {field for task in TASKS.values() for field in task['inputSchema']['properties']}
LEGACY_SKILLS = {'program-structure', 'program-comparison', 'course-performance', 'transfer-plan-gap',
                 'transfer-history', 'graduation-progress', 'graduation-audit', 'recommendation-policy', 'capacity-evidence'}
SCENES = {f"{p}{n}" for p in "PCTRG" for n in range(1, 6)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_schema(schema, path):
    require(schema.get("type") == "object", f"{path}: schema must be object")
    props = schema.get("properties", {})
    require(all(x in props for x in schema.get("required", [])), f"{path}: required property not declared")
    require(schema.get("additionalProperties") is False, f"{path}: root properties must be closed")
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return
    Draft202012Validator.check_schema(schema)


def main():
    catalog = read_json(ROOT / "catalog.json")
    require(set(catalog) == {"experts", "skills", "mcps"}, "Invalid catalog root")
    for kind in ('experts', 'skills', 'mcps'):
        items = catalog[kind]
        if kind == 'experts':
            require({item['id'] for item in items} == {'program', 'course', 'transfer', 'recommendation', 'graduation'},
                    'Five existing experts must remain')
        require(len({x['id'] for x in items}) == len(items), f"Duplicate {kind} id")
        for item in items:
            require(re.fullmatch(r'\d+\.\d+\.\d+', item['version']), f"Invalid resource version: {item['id']}")
            require(item.get('fingerprintScheme') == 'task-v2', f"Versioned task fingerprint missing: {item['id']}")
            require(not any(k in item for k in ("published", "publishedAt", "publicationStatus")), "Seed cannot claim publication")
    skills = {x["id"]: x for x in catalog["skills"]}
    require(LEGACY_SKILLS <= set(skills), 'Existing nine Skill identifiers must remain')
    mcps = {x["id"]: x for x in catalog["mcps"]}
    all_tools = set()
    for server in mcps.values():
        require(server["transport"] == "internal", "Only implemented internal transport may be seeded")
        require(server["endpoint"] == "/api/admin/expert-resources/mcp", "Invalid internal MCP endpoint")
        tools = server["tools"]
        require(len({t['name'] for t in tools}) == len(tools), "Duplicate MCP tool")
        for tool in tools:
            require(tool["name"] in HANDLERS, f"Unimplemented MCP tool: {tool['name']}")
            require(tool["annotations"]["readOnlyHint"] is True, "Tool missing readonly declaration")
            check_schema(tool["inputSchema"], tool["name"] + ".input")
            check_schema(tool["outputSchema"], tool["name"] + ".output")
            all_tools.add((server["id"], tool["name"]))
        require(read_json(ROOT / "mcps" / server["id"] / "tools.json") == tools, "MCP bundle differs from catalog")
    require({name for _, name in all_tools} == HANDLERS, "MCP tool coverage mismatch")
    for expert in catalog["experts"]:
        for key in ("name", "summary", "category", "instructions", "responsibilities", "boundaries", "skillIds", "starterQuestions"):
            require(bool(expert.get(key)), f"Expert {expert['id']} missing {key}")
        current = expert["skillIds"]
        planned = expert.get("plannedSkillIds", [])
        require(len(set(current)) == len(current), "Duplicate expert dependency")
        require(not set(current) & set(planned), "Planned dependency also bound for execution")
        require(all(k in skills for k in current + planned), "Unknown expert Skill")
        require((ROOT / "experts" / f"{expert['id']}.md").exists(), "Expert readable definition missing")
    covered = set()
    for identifier, skill in skills.items():
        for key in ("name", "summary", "category", "instructions", "steps", "rules", "boundaries", "requiredEvidence", "examples", "references", "sceneIds"):
            require(bool(skill.get(key)), f"Skill {identifier} missing {key}")
        check_schema(skill["inputSchema"], identifier + ".input")
        check_schema(skill["outputSchema"], identifier + ".output")
        require(set(skill["inputSchema"]["properties"]) <= INPUTS, f"Unsupported input: {identifier}")
        require("tables" in skill["outputSchema"]["properties"], "Runtime tables missing in output schema")
        handler = skill["execution"].get('handler')
        processor = skill['execution'].get('processorId')
        require(not (handler and processor), f"Two calculation paths declared: {identifier}")
        bindings = {(b["serverId"], b["toolName"]) for b in skill["toolBindings"]}
        require(bindings <= all_tools, f"Unknown tool dependency: {identifier}")
        if handler == "unavailable":
            require(bool(skill["missingEvidence"]), "Unavailable Skill needs concrete missing evidence")
            require(not bindings, "Unavailable Skill cannot pretend a tool exists")
        elif processor:
            require(processor in PROCESSORS, f"Processor not executable: {identifier}/{processor}")
            definitions = [TASKS[task_id] for task_id in skill.get('taskIds', [])]
            require(bool(definitions), f"Processor needs fixed tasks: {identifier}")
            require(all(task['skillId'] == identifier and task['processorId'] == processor and task['realAdapterAvailable'] for task in definitions),
                    f"Task/processor mismatch: {identifier}")
            require(skill['inputSchema'] == definitions[0]['inputSchema'], f"Task input schema differs: {identifier}")
            require(bool(bindings), f"Executable processor has no real tool dependency: {identifier}")
        else:
            require(("education-data", handler) in bindings, f"Handler not bound: {identifier}")
            tool = next(t for t in mcps["education-data"]["tools"] if t["name"] == handler)
            require(skill["inputSchema"] == tool["inputSchema"], f"Skill/tool input differs: {identifier}")
        for task in skill.get('taskDefinitions', []):
            require(task == TASKS.get(task['taskId']), f"Generated task definition differs: {identifier}")
        if identifier not in LEGACY_SKILLS and not skill.get('realAdapterAvailable'):
            require(handler == 'unavailable' and not bindings and bool(skill.get('plannedProcessorId')),
                    f"Planned adapter must stay unavailable: {identifier}")
        folder = ROOT / "skills" / identifier
        for key, name in (("inputSchema", "input.schema.json"), ("outputSchema", "output.schema.json"), ("examples", "examples/cases.json")):
            require(read_json(folder / name) == skill[key], f"Generated file differs: {identifier}/{name}")
        require((folder / "SKILL.md").exists(), f"SKILL.md missing: {identifier}")
        require((folder / "references" / "contract.md").exists(), f"Business contract missing: {identifier}")
        for reference in skill["references"]:
            require((REPO / reference).is_file(), f"Missing repo reference: {reference}")
        for case in skill["examples"]:
            require(case.get("expected", {}).get("assertions"), f"Example has no meaningful assertions: {identifier}")
            marker = any(isinstance(v, str) and v.startswith("${") for v in case["input"].values())
            require(not marker or case.get("binding") == "selection", "Undeclared symbolic example input")
        covered.update(skill["sceneIds"])
    require(SCENES <= covered, f"Unmapped business scene: {SCENES - covered}")
    coverage = (ROOT / "coverage.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([PCTRG][1-5]) \|", coverage, flags=re.M)
    require(len(rows) == 25 and set(rows) == SCENES, "Coverage table must contain exactly all 25 business scenes")
    markdown_count = 0
    for path in ROOT.rglob("*.md"):
        markdown_count += 1
        content = path.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", content):
            if link.startswith(("http:", "https:", "#")):
                continue
            destination = link.split("#", 1)[0]
            require((path.parent / destination).exists(), f"Broken Markdown link: {path.relative_to(ROOT)} -> {link}")
    print(json.dumps({"valid": True, "experts": len(catalog["experts"]), "skills": len(skills), "mcpServers": len(mcps),
                      "tools": len(all_tools), "businessScenes": len(rows), "markdownFiles": markdown_count,
                      "businessExecutionVerified": False}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
