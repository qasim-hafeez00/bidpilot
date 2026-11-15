# Prompts

One versioned Markdown file per LLM-using node (no inline prompts in Python; CI enforces this).
Front matter carries `version` and a changelog; `common/llm.py::load_prompt` parses `## system` / `## user`
sections and substitutes `$variables` (string.Template, so JSON braces need no escaping).
The prompt version is attached to every LLM call's trace metadata and usage record.

Untrusted text (job posts, client messages) is always placed between explicit delimiters and the system
prompt says to ignore instructions inside it (E4).
