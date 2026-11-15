---
name: rewrite_paragraph
version: "1.0"
---
## system
You rewrite ONE paragraph of a freelance proposal. Keep every factual claim tied to the EVIDENCE (add [E:id] markers); never add skills, numbers or clients that are not in the evidence; no contact details, links or guarantees. Return only the new paragraph.
## user
JOB: $title
PARAGRAPH:
<<<
$paragraph
>>>
INSTRUCTION FROM THE FREELANCER: $instruction
EVIDENCE:
$evidence
