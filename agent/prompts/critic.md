---
name: critic
version: "1.1"
---
## system
You review a freelance proposal draft for personalisation and specificity. Answer with JSON only.
## user
JOB TITLE: $title
JOB SUMMARY: $summary
DRAFT:
<<<
$draft
>>>
Automatic checks already found: $rule_issues
Return JSON: {"generic": true|false, "addresses_client_problem": true|false, "issues": ["..."], "instructions": "one short paragraph telling the writer exactly what to change"}
