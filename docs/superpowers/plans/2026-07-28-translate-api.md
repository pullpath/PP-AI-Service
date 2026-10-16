# Translate API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `POST /api/translate` endpoint that translates arbitrary text into a target language using the DeepSeek LLM.

**Architecture:** New `ai_svc/translation/` module with `prompts.py` (prompt builder) and `service.py` (`TranslationService` class, DeepSeek agent instantiated once at startup). Flask route added to `app.py`. No response_model — translation output is plain text extracted from the agent response.

**Tech Stack:** Python, Flask, agno (`Agent`), `agno.models.deepseek.DeepSeek`, python-dotenv.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ai_svc/translation/__init__.py` | Create | Package init — exports `translation_service` singleton |
| `ai_svc/translation/prompts.py` | Create | `get_translation_prompt(text, target_lang)` — builds the LLM prompt |
| `ai_svc/translation/service.py` | Create | `TranslationService` class with `translate(text, target_lang)` method |
| `app.py` | Modify | Import `translation_service`, add `POST /api/translate` route |

---

## Task 1: Create `ai_svc/translation/prompts.py`

**Files:**
- Create: `ai_svc/translation/prompts.py`

- [ ] **Step 1.1: Create the prompts file**

Create `/Users/jiali/personal_github_repos/PP-AI-Service/ai_svc/translation/prompts.py` with this exact content:

```python
"""
Translation service prompts
"""


def get_translation_prompt(text: str, target_lang: str) -> str:
    """Build a prompt that asks the LLM to translate text into the target language.

    Args:
        text: The text to translate.
        target_lang: BCP-47 language tag (e.g. "zh-cn", "ja", "es", "fr").

    Returns:
        Prompt string for the translation agent.
    """
    return (
        f"Translate the following text into the language identified by BCP-47 tag \"{target_lang}\".\n"
        "Return ONLY the translated text — no explanations, no quotes, no markdown, no extra punctuation.\n"
        "Preserve the original meaning and tone exactly.\n\n"
        f"Text to translate:\n{text}"
    )
```

- [ ] **Step 1.2: Commit**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
git add ai_svc/translation/prompts.py
git commit -m "feat(translate): add translation prompt builder"
```

---

## Task 2: Create `ai_svc/translation/service.py`

**Files:**
- Create: `ai_svc/translation/service.py`

- [ ] **Step 2.1: Create the service file**

Create `/Users/jiali/personal_github_repos/PP-AI-Service/ai_svc/translation/service.py` with this exact content:

```python
"""
Standalone translation service.
Translates arbitrary text into a target language using DeepSeek LLM.
"""
import os
import time
import logging
from typing import Dict, Any

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from dotenv import load_dotenv

from .prompts import get_translation_prompt

load_dotenv()
logger = logging.getLogger(__name__)


class TranslationService:
    """Translates arbitrary text into a target language via DeepSeek."""

    def __init__(self):
        deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        no_thinking = {"thinking": {"type": "disabled"}}

        translation_model = DeepSeek(
            id="deepseek-flash",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=1024,
            timeout=45.0,
            max_retries=0,
            extra_body=no_thinking,
        )

        self.agent = Agent(
            name="TranslationAgent",
            model=translation_model,
            description="Translates text into a target language",
        )

    def translate(self, text: str, target_lang: str) -> Dict[str, Any]:
        """Translate text into target_lang.

        Args:
            text: The text to translate.
            target_lang: BCP-47 language tag (e.g. "zh-cn", "ja", "es").

        Returns:
            {"success": True, "translation": "<translated text>"}
            or {"success": False, "error": "<message>"}
        """
        start = time.time()
        try:
            prompt = get_translation_prompt(text, target_lang)
            response = self.agent.run(prompt)
            # Extract plain-text content from the agent response
            translation = response.content
            if isinstance(translation, list):
                # agno may return a list of content blocks
                translation = "".join(
                    block.text if hasattr(block, "text") else str(block)
                    for block in translation
                )
            translation = translation.strip()
            logger.info(
                f"[translate] '{target_lang}' in {time.time() - start:.2f}s "
                f"({len(text)} chars → {len(translation)} chars)"
            )
            return {"success": True, "translation": translation}
        except Exception as e:
            logger.warning(f"[translate] Failed for target_lang='{target_lang}': {e}")
            return {"success": False, "error": str(e)}
```

- [ ] **Step 2.2: Commit**

```bash
git add ai_svc/translation/service.py
git commit -m "feat(translate): add TranslationService"
```

---

## Task 3: Create `ai_svc/translation/__init__.py`

**Files:**
- Create: `ai_svc/translation/__init__.py`

- [ ] **Step 3.1: Create the package init**

Create `/Users/jiali/personal_github_repos/PP-AI-Service/ai_svc/translation/__init__.py` with this exact content:

```python
"""
Translation service package.
"""
from .service import TranslationService

translation_service = TranslationService()
```

- [ ] **Step 3.2: Verify the module imports cleanly**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -c "from ai_svc.translation import translation_service; print('OK')"
```

Expected output: `OK` (no import errors).

- [ ] **Step 3.3: Commit**

```bash
git add ai_svc/translation/__init__.py
git commit -m "feat(translate): export translation_service singleton"
```

---

## Task 4: Add `POST /api/translate` route to `app.py`

**Files:**
- Modify: `app.py`

- [ ] **Step 4.1: Add the import**

Open `app.py`. Find this block (around line 20):

```python
from ai_svc.dictionary import dictionary_service
from ai_svc.dictionary.cache_service import cache_service
from ai_svc.dictionary.cache_routes import cache_bp
from ai_svc.dictionary.suggest_service import suggestion_service
from ai_svc.dictionary.video_task_service import video_task_service
from ai_svc.metrics_collector import metrics_collector
```

Add one line immediately after it:

```python
from ai_svc.translation import translation_service
```

- [ ] **Step 4.2: Add the route**

Open `app.py`. Find the last `@app.route` definition before the `if __name__ == '__main__':` block (around line 385, the `/api/search` route). Add the new route **after** the existing routes and **before** `if __name__ == '__main__':`.

Locate this line near the bottom of the file:

```python
if __name__ == '__main__':
```

Insert the following block immediately before it:

```python
@app.route('/api/translate', methods=['POST'])
def translate_text():
    """
    Standalone text translation endpoint.

    Request body:
    {
        "text": "She scrubbed the floor until it gleamed.",
        "target_lang": "zh-cn"
    }

    - "text": Required. The text to translate (word, phrase, or sentence).
    - "target_lang": Required. BCP-47 language tag for the target language
                     (e.g. "zh-cn", "ja", "es", "fr", "de").

    Response:
    {
        "text": "She scrubbed the floor until it gleamed.",
        "target_lang": "zh-cn",
        "translation": "她把地板擦得闪闪发光。",
        "execution_time": 1.23,
        "success": true
    }
    """
    start_time = __import__('time').time()
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({
                "error": "Missing 'text' parameter in request body",
                "success": False
            }), 400

        if 'target_lang' not in data:
            return jsonify({
                "error": "Missing 'target_lang' parameter in request body",
                "success": False
            }), 400

        text = data['text'].strip()
        if not text:
            return jsonify({
                "error": "text cannot be empty",
                "success": False
            }), 400

        target_lang = data['target_lang'].strip()
        if not target_lang:
            return jsonify({
                "error": "target_lang cannot be empty",
                "success": False
            }), 400

        result = translation_service.translate(text, target_lang)
        if not result.get("success"):
            return jsonify({
                "error": f"Translation failed: {result.get('error', 'unknown error')}",
                "success": False
            }), 500

        return jsonify({
            "text": text,
            "target_lang": target_lang,
            "translation": result["translation"],
            "execution_time": __import__('time').time() - start_time,
            "success": True
        })
    except Exception as e:
        logging.error(f"[/api/translate] Unexpected error: {e}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500
```

- [ ] **Step 4.3: Verify the app starts without errors**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python app.py &
sleep 3
curl -s http://localhost:8000/ | head -5
kill %1
```

Expected: HTML from the index page (no startup crash).

- [ ] **Step 4.4: Smoke-test the endpoint**

Start the app, then in another terminal:

```bash
curl -s -X POST http://localhost:8000/api/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "She scrubbed the floor until it gleamed.", "target_lang": "zh-cn"}'
```

Expected response shape:
```json
{
  "text": "She scrubbed the floor until it gleamed.",
  "target_lang": "zh-cn",
  "translation": "...",
  "execution_time": 1.5,
  "success": true
}
```

- [ ] **Step 4.5: Test validation errors**

Missing `text`:
```bash
curl -s -X POST http://localhost:8000/api/translate \
  -H "Content-Type: application/json" \
  -d '{"target_lang": "zh-cn"}'
```
Expected: HTTP 400, `{"error": "Missing 'text' parameter in request body", "success": false}`

Missing `target_lang`:
```bash
curl -s -X POST http://localhost:8000/api/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "hello"}'
```
Expected: HTTP 400, `{"error": "Missing 'target_lang' parameter in request body", "success": false}`

- [ ] **Step 4.6: Commit**

```bash
git add app.py
git commit -m "feat(translate): add POST /api/translate endpoint"
```
