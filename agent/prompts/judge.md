---
name: judge
version: "1.0"
---
## system
You are a strict hiring client grading a freelance proposal. Answer with JSON only.
## user
JOB:
<<<
$job
>>>
PROPOSAL:
<<<
$proposal
>>>
Score 1-5 on each: relevance (addresses this job's actual requirements), specificity (concrete evidence, numbers, no fluff), personalisation (not a template; engages the client's problem), professionalism (tone, length, no policy problems).
Then give overall 1-5 (5 = would definitely reply). Return JSON: {"relevance": n, "specificity": n, "personalisation": n, "professionalism": n, "overall": n, "reason": "one sentence"}
