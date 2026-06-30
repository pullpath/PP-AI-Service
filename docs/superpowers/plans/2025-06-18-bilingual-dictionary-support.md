# Bilingual Dictionary Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Chinese (zh) bilingual translation fields to the dictionary API when `lang=zh` is requested.

**Architecture:** When `lang=zh` is passed, after English data is fetched, dedicated translation AI agents produce Chinese equivalents (`zh_*` fields). Results are cached in separate `*_zh_*` columns in existing SQLite tables. No `lang` parameter means English-only (backward compatible).

**Files modified:**
- `ai_svc/dictionary/schemas.py` — add Chinese translation Pydantic models
- `ai_svc/dictionary/prompts.py` — add translation prompt functions
- `ai_svc/dictionary/service.py` — add translation agents + wire `lang` through `lookup_section`
- `ai_svc/dictionary/cache_service.py` — add `*_zh_*` columns + `lang`-aware get/set/lookup
- `app.py` — parse `lang` from request, pass through to cache and service

---

### Task 1: Add Chinese translation Pydantic models to `schemas.py`

**File:** `ai_svc/dictionary/schemas.py` — add after line 7 (before `EtymologyInfo`)

```python
class ChineseBasicDefinition(BaseModel):
    definition: str = Field(..., description="Chinese translation of the definition")
    example: str = Field(default="", description="Chinese translation of the example sentence")
    synonyms: List[str] = Field(default_factory=list, description="Chinese synonyms")
    antonyms: List[str] = Field(default_factory=list, description="Chinese antonyms")


class ChineseBasicMeaning(BaseModel):
    part_of_speech: str = Field(..., description="Chinese part of speech, e.g., '动词', '名词'")
    definitions: List[ChineseBasicDefinition] = Field(
        default_factory=list, description="Chinese translations of definitions for this meaning"
    )


class ChineseBasicTranslation(BaseModel):
    meanings: List[ChineseBasicMeaning] = Field(
        default_factory=list, description="Chinese translations for each meaning group"
    )


class ChineseDetailedSenseTranslation(BaseModel):
    zh_definition: str = Field(default="", description="Chinese translation of the definition")
    zh_part_of_speech: str = Field(default="", description="Chinese part of speech")
    zh_synonyms: List[str] = Field(default_factory=list, description="Chinese synonyms")
    zh_antonyms: List[str] = Field(default_factory=list, description="Chinese antonyms")
    zh_word_specific_phrases: List[str] = Field(default_factory=list, description="Chinese translations of phrases")


class ChineseExamplesTranslation(BaseModel):
    zh_examples: List[str] = Field(default_factory=list, description="Chinese translations of example sentences")
    zh_collocations: List[str] = Field(default_factory=list, description="Chinese translations of collocations")


class ChineseUsageNotesTranslation(BaseModel):
    zh_learner_guidance: str = Field(default="", description="Chinese translation of learner guidance")
    zh_common_pitfalls: List[str] = Field(default_factory=list, description="Chinese translations of common pitfalls")


class ChineseCommonPhrasesTranslation(BaseModel):
    zh_phrases: List[str] = Field(default_factory=list, min_length=0, max_length=6, description="Chinese translations of common phrases")
```

No `ChinesePhonetic` — phonetics remain English-only.

---

### Task 2: Add translation prompt functions to `prompts.py`

**File:** `ai_svc/dictionary/prompts.py` — add at end of file

```python
def get_basic_translation_prompt(word: str, basic_json: str) -> str:
    return f"""You are a professional English-to-Chinese dictionary translator.

Translate the following English dictionary entry for "{word}" into accurate, natural Chinese.

Rules:
1. Preserve meaning exactly — do not add or omit information
2. Use natural Chinese dictionary phrasing (like 《牛津高阶》 or 《朗文》 style)
3. For definitions, provide clear, idiomatic Chinese
4. For examples, provide natural Chinese translations
5. For synonyms/antonyms, find the closest Chinese equivalents

English source data:
{basic_json}

Output must be valid JSON matching the ChineseBasicTranslation schema.

Example output structure:
{{
  "meanings": [
    {{
      "part_of_speech": "动词",
      "definitions": [
        {{"definition": "用腿快速移动", "example": "她每天早上跑步。", "synonyms": ["慢跑", "冲刺"], "antonyms": ["步行"]}}
      ]
    }}
  ]
}}"""


def get_detailed_sense_translation_prompt(word: str, sense_index: int, basic_definition: str,
                                          core_metadata: str, related_words: str) -> str:
    return f"""You are a professional English-to-Chinese dictionary translator.

Translate the following detailed word sense analysis for sense #{sense_index + 1} of "{word}" into Chinese.

Definition: "{basic_definition}"

Core metadata (JSON):
{core_metadata}

Related words (JSON):
{related_words}

Produce Chinese translations for each field.
Output must be valid JSON matching the ChineseDetailedSenseTranslation schema."""


def get_examples_translation_prompt(word: str, sense_index: int, basic_definition: str,
                                    examples_data: str) -> str:
    return f"""You are a professional English-to-Chinese dictionary translator.

Translate the following example sentences and collocations for sense #{sense_index + 1} of "{word}" into Chinese.

Definition: "{basic_definition}"

English examples and collocations (JSON):
{examples_data}

Output must be valid JSON matching the ChineseExamplesTranslation schema."""


def get_usage_notes_translation_prompt(word: str, sense_index: int, basic_definition: str,
                                       usage_notes_data: str) -> str:
    return f"""You are a professional English-to-Chinese dictionary translator.

Translate the following usage guidance for sense #{sense_index + 1} of "{word}" into Chinese.

Definition: "{basic_definition}"

English usage notes (JSON):
{usage_notes_data}

Output must be valid JSON matching the ChineseUsageNotesTranslation schema."""


def get_common_phrases_translation_prompt(word: str, phrases_data: str) -> str:
    return f"""You are a professional English-to-Chinese dictionary translator.

Translate the following common English phrases for "{word}" into natural Chinese.

English phrases:
{phrases_data}

Output must be valid JSON matching the ChineseCommonPhrasesTranslation schema."""
```

---

### Task 3: Add Chinese translation agents to `service.py`

**File:** `ai_svc/dictionary/service.py`

**3a:** Update imports (lines 26-41). Add to schemas import:
```python
ChineseBasicTranslation, ChineseDetailedSenseTranslation,
ChineseExamplesTranslation, ChineseUsageNotesTranslation,
ChineseCommonPhrasesTranslation,
```

Add to prompts import:
```python
get_basic_translation_prompt,
get_detailed_sense_translation_prompt, get_examples_translation_prompt,
get_usage_notes_translation_prompt, get_common_phrases_translation_prompt,
```

**3b:** Add translation agent models in `__init__` (after line 350, after conversation_model block):

```python
translation_model = DeepSeek(
    id="deepseek-v4-flash",
    api_key=deepseek_api_key,
    temperature=0,
    max_tokens=1024,
    timeout=45.0,
    max_retries=0,
    extra_body=no_thinking
)

self.basic_translation_agent = Agent(
    name="BasicTranslationAgent",
    model=translation_model,
    description="Translates basic dictionary data into Chinese",
    use_json_mode=True,
    output_schema=ChineseBasicTranslation
)

self.sense_translation_agent = Agent(
    name="SenseTranslationAgent",
    model=translation_model,
    description="Translates detailed sense analysis into Chinese",
    use_json_mode=True,
    output_schema=ChineseDetailedSenseTranslation
)

self.examples_translation_agent = Agent(
    name="ExamplesTranslationAgent",
    model=translation_model,
    description="Translates examples and collocations into Chinese",
    use_json_mode=True,
    output_schema=ChineseExamplesTranslation
)

self.usage_notes_translation_agent = Agent(
    name="UsageNotesTranslationAgent",
    model=translation_model,
    description="Translates usage notes into Chinese",
    use_json_mode=True,
    output_schema=ChineseUsageNotesTranslation
)

self.phrases_translation_agent = Agent(
    name="PhrasesTranslationAgent",
    model=translation_model,
    description="Translates common phrases into Chinese",
    use_json_mode=True,
    output_schema=ChineseCommonPhrasesTranslation
)
```

**3c:** Add `_translate_basic_section` method (after `_fetch_basic`):

```python
def _translate_basic_section(self, word: str, basic_result: Dict[str, Any]) -> Dict[str, Any]:
    """Translate basic section data into Chinese"""
    try:
        basic_json = json.dumps(basic_result, ensure_ascii=False)
        prompt = get_basic_translation_prompt(word, basic_json)
        response = self.basic_translation_agent.run(prompt)
        translation = response.content if hasattr(response, 'content') else str(response)
        import json as _json
        parsed = _json.loads(translation)
        return {"success": True, "translation": parsed}
    except Exception as e:
        logger.warning(f"Failed to translate basic section for '{word}': {e}")
        return {"success": False, "error": str(e)}
```

**3d:** Add `_translate_detailed_sense` method (after `_fetch_single_detailed_sense_2d`):

```python
def _translate_detailed_sense(self, word: str, entry_index: int, sense_index: int,
                               basic_definition: str, core_result: Dict[str, Any],
                               related_result: Dict[str, Any]) -> Dict[str, Any]:
    """Translate detailed sense data into Chinese"""
    try:
        core_json = json.dumps(core_result, ensure_ascii=False)
        related_json = json.dumps(related_result, ensure_ascii=False)
        prompt = get_detailed_sense_translation_prompt(word, sense_index, basic_definition, core_json, related_json)
        response = self.sense_translation_agent.run(prompt)
        import json as _json
        parsed = _json.loads(response.content if hasattr(response, 'content') else str(response))
        return {"success": True, "translation": parsed}
    except Exception as e:
        logger.warning(f"Failed to translate detailed sense for '{word}': {e}")
        return {"success": False, "error": str(e)}
```

**3e:** Add `_translate_examples` method:

```python
def _translate_examples(self, word: str, entry_index: int, sense_index: int,
                         basic_definition: str, examples_data: Dict[str, Any]) -> Dict[str, Any]:
    """Translate examples into Chinese"""
    try:
        examples_json = json.dumps(examples_data, ensure_ascii=False)
        prompt = get_examples_translation_prompt(word, sense_index, basic_definition, examples_json)
        response = self.examples_translation_agent.run(prompt)
        import json as _json
        parsed = _json.loads(response.content if hasattr(response, 'content') else str(response))
        return {"success": True, "translation": parsed}
    except Exception as e:
        logger.warning(f"Failed to translate examples for '{word}': {e}")
        return {"success": False, "error": str(e)}
```

**3f:** Add `_translate_usage_notes` method:

```python
def _translate_usage_notes(self, word: str, entry_index: int, sense_index: int,
                            basic_definition: str, usage_notes_data: Dict[str, Any]) -> Dict[str, Any]:
    """Translate usage notes into Chinese"""
    try:
        notes_json = json.dumps(usage_notes_data, ensure_ascii=False)
        prompt = get_usage_notes_translation_prompt(word, sense_index, basic_definition, notes_json)
        response = self.usage_notes_translation_agent.run(prompt)
        import json as _json
        parsed = _json.loads(response.content if hasattr(response, 'content') else str(response))
        return {"success": True, "translation": parsed}
    except Exception as e:
        logger.warning(f"Failed to translate usage notes for '{word}': {e}")
        return {"success": False, "error": str(e)}
```

**3g:** Add `_translate_common_phrases` method:

```python
def _translate_common_phrases(self, word: str, phrases_data: Dict[str, Any]) -> Dict[str, Any]:
    """Translate common phrases into Chinese"""
    try:
        phrases_json = json.dumps(phrases_data, ensure_ascii=False)
        prompt = get_common_phrases_translation_prompt(word, phrases_json)
        response = self.phrases_translation_agent.run(prompt)
        import json as _json
        parsed = _json.loads(response.content if hasattr(response, 'content') else str(response))
        return {"success": True, "translation": parsed}
    except Exception as e:
        logger.warning(f"Failed to translate common phrases for '{word}': {e}")
        return {"success": False, "error": str(e)}
```

**3h:** Add `_add_chinese_translations` helper method (after `_fetch_basic`):

```python
def _add_chinese_translations(self, word: str, section: str, result: Dict[str, Any],
                               entry_index: Optional[int] = None,
                               sense_index: Optional[int] = None,
                               phrase: Optional[str] = None) -> Dict[str, Any]:
    """Add Chinese translation fields to a section result"""
    if not result.get('success'):
        return result

    if section == 'basic':
        trans = self._translate_basic_section(word, result)
        if trans.get('success'):
            result['basic_zh'] = trans['translation']

    elif section == 'detailed_sense':
        basic_def = result.get('detailed_sense', {}).get('definition', '')
        core_data = {k: result.get('detailed_sense', {}).get(k) for k in
                     ['part_of_speech', 'usage_register', 'domain', 'tone']}
        related_data = {k: result.get('detailed_sense', {}).get(k) for k in
                        ['synonyms', 'antonyms', 'word_specific_phrases']}
        trans = self._translate_detailed_sense(word, entry_index, sense_index,
                                                basic_def, core_data, related_data)
        if trans.get('success'):
            result['detailed_sense_zh'] = trans['translation']

    elif section == 'examples':
        trans = self._translate_examples(word, entry_index, sense_index,
                                          '', {'examples': result.get('examples', []),
                                               'collocations': result.get('collocations', [])})
        if trans.get('success'):
            result['zh_examples'] = trans['translation'].get('zh_examples', [])
            result['zh_collocations'] = trans['translation'].get('zh_collocations', [])

    elif section == 'usage_notes':
        trans = self._translate_usage_notes(word, entry_index, sense_index,
                                             '', {'usage_notes': result.get('usage_notes', '')})
        if trans.get('success'):
            result['zh_learner_guidance'] = trans['translation'].get('zh_learner_guidance', '')
            result['zh_common_pitfalls'] = trans['translation'].get('zh_common_pitfalls', [])

    elif section == 'common_phrases':
        trans = self._translate_common_phrases(word, result)
        if trans.get('success'):
            result['zh_phrases'] = trans['translation'].get('zh_phrases', [])

    return result
```

---

### Task 4: Wire `lang` through `lookup_section` in `service.py`

**File:** `ai_svc/dictionary/service.py`

**4a:** Add `lang` parameter to `lookup_section` signature (line 382):

```python
def lookup_section(self, word: str, section: str, sense_index: Optional[int] = None,
                   entry_index: Optional[int] = None, phrase: Optional[str] = None,
                   confused_word: Optional[str] = None, lang: Optional[str] = None,
                   style: str = "kids_cartoon", duration: int = 5,
                   resolution: str = "480p", ratio: str = "16:9") -> Dict[str, Any]:
```

**4b:** Modify each section return in `lookup_section` to check `lang == 'zh'` and call `_add_chinese_translations`.

**`basic` section (line 451):**
```python
            if section == 'basic':
                result = self._fetch_basic(normalized_word, start_time)
                if lang == 'zh' and result.get('success'):
                    result = self._add_chinese_translations(normalized_word, section, result)
                return result
```

**`detailed_sense` section (lines 441-448):**
```python
                response = {
                    "headword": normalized_word,
                    "detailed_sense": result["detailed_sense"],
                    "entry_index": result.get("entry_index", 0),
                    "sense_index": result.get("sense_index", 0),
                    "execution_time": time.time() - start_time,
                    "success": True
                }
                if lang == 'zh':
                    response = self._add_chinese_translations(normalized_word, section, response, entry_index, sense_index)
                return response
```

**`examples` section (lines 462-471):**
```python
                response = {
                    "headword": normalized_word,
                    "entry_index": entry_index,
                    "sense_index": sense_index,
                    "examples": result["examples"],
                    "collocations": result["collocations"],
                    "data_source": "hybrid",
                    "execution_time": time.time() - start_time,
                    "success": True
                }
                if lang == 'zh':
                    response = self._add_chinese_translations(normalized_word, section, response, entry_index, sense_index)
                return response
```

**`usage_notes` section (lines 482-490):**
```python
                response = {
                    "headword": normalized_word,
                    "entry_index": entry_index,
                    "sense_index": sense_index,
                    "usage_notes": result["usage_notes"],
                    "data_source": "ai",
                    "execution_time": time.time() - start_time,
                    "success": True
                }
                if lang == 'zh':
                    response = self._add_chinese_translations(normalized_word, section, response, entry_index, sense_index)
                return response
```

**`common_phrases` section (line 493):**
```python
            if section == 'common_phrases':
                result = self._fetch_common_phrases_section(normalized_word, start_time)
                if lang == 'zh' and result.get('success'):
                    result = self._add_chinese_translations(normalized_word, section, result)
                return result
```

**Entry-level sections (lines 560-562):**
```python
            entry_level_sections = ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']
            if section in entry_level_sections:
                result = self._fetch_entry_level_section(normalized_word, section, entry_index, start_time)
                if lang == 'zh' and result.get('success'):
                    result = self._add_chinese_translations(normalized_word, section, result, entry_index)
                return result
```

---

### Task 5: Pass `lang` from route handler in `app.py`

**File:** `app.py`

**5a:** Extract `lang` from request (after line 171):

```python
        lang = data.get('lang', None)
        if lang is not None and lang not in ('zh',):
            return jsonify({
                "error": f"Unsupported language '{lang}'. Supported: 'zh'",
                "success": False
            }), 400
```

**5b:** Pass `lang` to `fetch_from_service` lambda (line 191-192):

```python
        def fetch_from_service():
            """Fetch function for cache miss"""
            return dictionary_service.lookup_section(word, section, sense_index, entry_index, phrase, confused_word, lang=lang)
```

**5c:** Pass `lang` to `lookup_with_cache` (line 194-202):

```python
        result, status_code = cache_service.lookup_with_cache(
            word=word,
            section=section,
            entry_index=entry_index,
            sense_index=sense_index,
            phrase=phrase,
            fetch_func=fetch_from_service,
            confused_word=confused_word,
            lang=lang
        )
```

---

### Task 6: Add Chinese cache columns to `cache_service.py`

**File:** `ai_svc/dictionary/cache_service.py`

**6a:** Add `*_zh_*` columns to `word_cache` schema in `_create_schema` (line 151-171, before closing `")"`):

```python
                # Chinese translation columns
                basic_zh_data TEXT,
                basic_zh_updated_at INTEGER,
                basic_zh_status TEXT DEFAULT 'empty' CHECK(basic_zh_status IN ('empty', 'fetching', 'fresh', 'stale', 'failed')),

                common_phrases_zh_data TEXT,
                common_phrases_zh_updated_at INTEGER,
                common_phrases_zh_status TEXT DEFAULT 'empty'
```

**6b:** Add `*_zh_*` columns to `entry_cache` schema (line 173-207, before `UNIQUE` line):

```python
                etymology_zh_data TEXT,
                etymology_zh_updated_at INTEGER,
                etymology_zh_status TEXT DEFAULT 'empty',

                word_family_zh_data TEXT,
                word_family_zh_updated_at INTEGER,
                word_family_zh_status TEXT DEFAULT 'empty',

                usage_context_zh_data TEXT,
                usage_context_zh_updated_at INTEGER,
                usage_context_zh_status TEXT DEFAULT 'empty',

                cultural_notes_zh_data TEXT,
                cultural_notes_zh_updated_at INTEGER,
                cultural_notes_zh_status TEXT DEFAULT 'empty',

                frequency_zh_data TEXT,
                frequency_zh_updated_at INTEGER,
                frequency_zh_status TEXT DEFAULT 'empty',

                bilibili_videos_zh_data TEXT,
                bilibili_videos_zh_updated_at INTEGER,
                bilibili_videos_zh_status TEXT DEFAULT 'empty',
```

**6c:** Add `*_zh_*` columns to `sense_cache` schema (line 209-232):

```python
                detailed_sense_zh_data TEXT,
                detailed_sense_zh_updated_at INTEGER,
                detailed_sense_zh_status TEXT DEFAULT 'empty',

                examples_zh_data TEXT,
                examples_zh_updated_at INTEGER,
                examples_zh_status TEXT DEFAULT 'empty',

                usage_notes_zh_data TEXT,
                usage_notes_zh_updated_at INTEGER,
                usage_notes_zh_status TEXT DEFAULT 'empty',
```

**6d:** Add migration for existing databases (after `_migrate_add_common_phrases_columns` call, line 383):

```python
        self._migrate_add_zh_columns(conn)
```

**6e:** Add `_migrate_add_zh_columns` method (after `_migrate_add_common_phrases_columns`):

```python
    def _migrate_add_zh_columns(self, conn: sqlite3.Connection):
        """Add Chinese translation columns to existing tables"""
        try:
            cursor = conn.execute("PRAGMA table_info(word_cache)")
            columns = {row[1] for row in cursor.fetchall()}

            zh_word_cols = [
                ('basic_zh_data', 'TEXT'),
                ('basic_zh_updated_at', 'INTEGER'),
                ('basic_zh_status', "TEXT DEFAULT 'empty'"),
                ('common_phrases_zh_data', 'TEXT'),
                ('common_phrases_zh_updated_at', 'INTEGER'),
                ('common_phrases_zh_status', "TEXT DEFAULT 'empty'"),
            ]
            for col_name, col_type in zh_word_cols:
                if col_name not in columns:
                    conn.execute(f"ALTER TABLE word_cache ADD COLUMN {col_name} {col_type}")

            cursor = conn.execute("PRAGMA table_info(entry_cache)")
            columns = {row[1] for row in cursor.fetchall()}
            zh_entry_sections = ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']
            for section in zh_entry_sections:
                for suffix, col_type in [('_data', 'TEXT'), ('_updated_at', 'INTEGER'), ('_status', "TEXT DEFAULT 'empty'")]:
                    col_name = f"{section}_zh{suffix}"
                    if col_name not in columns:
                        conn.execute(f"ALTER TABLE entry_cache ADD COLUMN {col_name} {col_type}")

            cursor = conn.execute("PRAGMA table_info(sense_cache)")
            columns = {row[1] for row in cursor.fetchall()}
            zh_sense_sections = ['detailed_sense', 'examples', 'usage_notes']
            for section in zh_sense_sections:
                for suffix, col_type in [('_data', 'TEXT'), ('_updated_at', 'INTEGER'), ('_status', "TEXT DEFAULT 'empty'")]:
                    col_name = f"{section}_zh{suffix}"
                    if col_name not in columns:
                        conn.execute(f"ALTER TABLE sense_cache ADD COLUMN {col_name} {col_type}")

            conn.commit()
        except Exception as e:
            logger.warning(f"Migration warning for zh columns (may be expected): {e}")
```

---

### Task 7: Add Chinese cache get/set methods to `cache_service.py`

**File:** `ai_svc/dictionary/cache_service.py`

**7a:** Add `get_basic_zh` and `set_basic_zh` (after `set_basic`):

```python
    def get_basic_zh(self, word: str) -> Optional[Dict[str, Any]]:
        """Get cached Chinese translation of basic section"""
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        try:
            row = conn.execute("""
                SELECT basic_zh_data, basic_zh_updated_at
                FROM word_cache WHERE word = ?
            """, (normalized,)).fetchone()
            if not row or not row['basic_zh_data']:
                return None
            is_stale = self._is_stale(row['basic_zh_updated_at'], 'basic')
            return {
                'data': json.loads(row['basic_zh_data']),
                'updated_at': row['basic_zh_updated_at'],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()

    def set_basic_zh(self, word: str, data: Dict[str, Any], status: str = 'fresh'):
        normalized = self._normalize_word(word)
        now = int(time.time())
        with self._write_transaction() as conn:
            conn.execute("""
                INSERT INTO word_cache (word, normalized_word, basic_zh_data, basic_zh_updated_at, basic_zh_status,
                                        created_at, last_accessed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    basic_zh_data = excluded.basic_zh_data,
                    basic_zh_updated_at = excluded.basic_zh_updated_at,
                    basic_zh_status = excluded.basic_zh_status,
                    last_accessed_at = excluded.last_accessed_at
            """, (normalized, normalized, json.dumps(data), now, status, now, now))
        logger.info(f"[{word}] Cached 'basic_zh' section - status: {status}")
```

**7b:** Add `get_entry_section_zh` and `set_entry_section_zh` (after `set_entry_section`):

```python
    def get_entry_section_zh(self, word: str, entry_index: int, section: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        try:
            data_col = f"{section}_zh_data"
            time_col = f"{section}_zh_updated_at"
            status_col = f"{section}_zh_status"
            row = conn.execute(f"""
                SELECT {data_col}, {time_col}, {status_col}
                FROM entry_cache WHERE word = ? AND entry_index = ?
            """, (normalized, entry_index)).fetchone()
            if not row or not row[data_col] or row[status_col] not in ('fresh', 'stale'):
                return None
            is_stale = self._is_stale(row[time_col], section)
            return {
                'data': json.loads(row[data_col]),
                'updated_at': row[time_col],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()

    def set_entry_section_zh(self, word: str, entry_index: int, section: str, data: Dict[str, Any], status: str = 'fresh'):
        normalized = self._normalize_word(word)
        now = int(time.time())
        with self._write_transaction() as conn:
            data_col = f"{section}_zh_data"
            time_col = f"{section}_zh_updated_at"
            status_col = f"{section}_zh_status"
            conn.execute(f"""
                INSERT INTO entry_cache (word, entry_index, {data_col}, {time_col}, {status_col})
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(word, entry_index) DO UPDATE SET
                    {data_col} = excluded.{data_col},
                    {time_col} = excluded.{time_col},
                    {status_col} = excluded.{status_col}
            """, (normalized, entry_index, json.dumps(data), now, status))
        logger.info(f"[{word}] Cached '{section}_zh' (entry {entry_index}) - status: {status}")
```

**7c:** Add `get_sense_section_zh` and `set_sense_section_zh` (after `set_sense_section`):

```python
    def get_sense_section_zh(self, word: str, entry_index: int, sense_index: int, section: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        try:
            data_col = f"{section}_zh_data"
            time_col = f"{section}_zh_updated_at"
            status_col = f"{section}_zh_status"
            row = conn.execute(f"""
                SELECT {data_col}, {time_col}, {status_col}
                FROM sense_cache WHERE word = ? AND entry_index = ? AND sense_index = ?
            """, (normalized, entry_index, sense_index)).fetchone()
            if not row or not row[data_col] or row[status_col] not in ('fresh', 'stale'):
                return None
            is_stale = self._is_stale(row[time_col], section)
            return {
                'data': json.loads(row[data_col]),
                'updated_at': row[time_col],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()

    def set_sense_section_zh(self, word: str, entry_index: int, sense_index: int, section: str, data: Dict[str, Any], status: str = 'fresh'):
        normalized = self._normalize_word(word)
        now = int(time.time())
        with self._write_transaction() as conn:
            data_col = f"{section}_zh_data"
            time_col = f"{section}_zh_updated_at"
            status_col = f"{section}_zh_status"
            conn.execute(f"""
                INSERT INTO sense_cache (word, entry_index, sense_index, {data_col}, {time_col}, {status_col})
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(word, entry_index, sense_index) DO UPDATE SET
                    {data_col} = excluded.{data_col},
                    {time_col} = excluded.{time_col},
                    {status_col} = excluded.{status_col}
            """, (normalized, entry_index, sense_index, json.dumps(data), now, status))
        logger.info(f"[{word}] Cached '{section}_zh' (entry {entry_index}, sense {sense_index}) - status: {status}")
```

---

### Task 8: Wire `lang` through `lookup_with_cache` in `cache_service.py`

**File:** `ai_svc/dictionary/cache_service.py`

**8a:** Add `lang` parameter to `lookup_with_cache` (line 1530):

```python
    def lookup_with_cache(self, word, section, entry_index, sense_index, phrase, fetch_func, confused_word=None, lang=None):
```

**8b:** Add `lang` to `_make_cache_key` (line 411-422):

```python
    def _make_cache_key(self, word: str, section: str, entry_index: int = None,
                        sense_index: int = None, confused_word: str = None,
                        lang: str = None) -> str:
        lang_part = f":{lang}" if lang else ""
        if section == 'basic':
            return f"{word}:basic{lang_part}"
        elif section == 'common_phrases':
            return f"{word}:common_phrases{lang_part}"
        elif section in ('confusion_meta', 'confusion_profiles', 'confusion_examples', 'confusion_all'):
            return f"{word}:confusion:{confused_word}:{section}{lang_part}"
        elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']:
            return f"{word}:entry:{entry_index}:{section}{lang_part}"
        else:
            return f"{word}:sense:{entry_index}:{sense_index}:{section}{lang_part}"
```

**8c:** Update `_make_cache_key` call site in `lookup_with_cache` (line 1625) to pass `lang`:

```python
        cache_key = self._make_cache_key(word, section, entry_index, sense_index, confused_word, lang)
```

**8d:** Add `lang`-aware cache reading in `lookup_with_cache` (lines 1557-1590). Replace the existing cache read block:

```python
        cached = None
        if section == 'basic':
            if lang == 'zh':
                cached = self.get_basic_zh(word)
            else:
                cached = self.get_basic(word)
        elif section == 'common_phrases':
            cached = self.get_common_phrases(word)
        elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
            if entry_index is not None:
                if lang == 'zh':
                    cached = self.get_entry_section_zh(word, entry_index, section)
                else:
                    cached = self.get_entry_section(word, entry_index, section)
        elif section == 'bilibili_videos':
            if phrase:
                cached = self.get_phrase_videos(word, phrase)
        elif section in ['detailed_sense', 'examples', 'usage_notes']:
            if entry_index is not None and sense_index is not None:
                if lang == 'zh':
                    cached = self.get_sense_section_zh(word, entry_index, sense_index, section)
                else:
                    cached = self.get_sense_section(word, entry_index, sense_index, section)
        elif section in ('confusion_meta', 'confusion_profiles', 'confusion_examples'):
            if confused_word:
                cached = self.get_word_confusion(word, confused_word, section)
        elif section == 'confusion_all':
            if confused_word:
                c_meta = self.get_word_confusion(word, confused_word, 'confusion_meta')
                c_profiles = self.get_word_confusion(word, confused_word, 'confusion_profiles')
                c_examples = self.get_word_confusion(word, confused_word, 'confusion_examples')
                if (c_meta and c_meta.get('cache_hit') and not c_meta.get('is_stale') and
                        c_profiles and c_profiles.get('cache_hit') and not c_profiles.get('is_stale') and
                        c_examples and c_examples.get('cache_hit') and not c_examples.get('is_stale')):
                    logger.info(f"[{word}] Cache HIT (all 3 confusion sections fresh)")
                    self.metrics.record_hit(time.time() - start_time)
                    response_time = (time.time() - start_time) * 1000
                    self.track_metric('hit', word, section, response_time, 'cache')
                    return {
                        **c_meta['data'],
                        **c_profiles['data'],
                        **c_examples['data'],
                        '_cache_status': 'fresh',
                    }, 200
```

**8e:** Apply the same `lang`-aware pattern to the in-flight wait loop cache re-checks (lines 1642-1659), mirroring the pattern in 8d.

**8f:** Add `lang`-aware cache writing in `lookup_with_cache` (lines 1682-1709). When `lang == 'zh'`, write to the zh columns instead of English columns:

```python
            if result.get('success'):
                try:
                    if lang == 'zh':
                        if section == 'basic':
                            self.set_basic_zh(word, result)
                        elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
                            if entry_index is not None:
                                self.set_entry_section_zh(word, entry_index, section, result)
                        elif section in ['detailed_sense', 'examples', 'usage_notes']:
                            if entry_index is not None and sense_index is not None:
                                self.set_sense_section_zh(word, entry_index, sense_index, section, result)
                    else:
                        if section == 'basic':
                            self.set_basic(word, result)
                        elif section == 'common_phrases':
                            self.set_common_phrases(word, result)
                        elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
                            if entry_index is not None:
                                self.set_entry_section(word, entry_index, section, result)
                        elif section == 'bilibili_videos':
                            if phrase:
                                self.set_phrase_videos(word, phrase, result)
                        elif section in ['detailed_sense', 'examples', 'usage_notes']:
                            if entry_index is not None and sense_index is not None:
                                self.set_sense_section(word, entry_index, sense_index, section, result)
                        elif section in ('confusion_meta', 'confusion_profiles', 'confusion_examples'):
                            if confused_word:
                                self.set_word_confusion(word, confused_word, section, result)
                        elif section == 'confusion_all':
                            if confused_word:
                                ...
                except Exception as cache_error:
                    logger.warning(f"Failed to write cache for {word}/{section}: {cache_error}")
```

---

### Task 9: Verification

- [ ] **9a:** Start the Flask app: `python app.py`

- [ ] **9b:** Test English-only (backward compat):
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"basic"}'
```
Expected: no `zh_*` fields, `_cache_status: "fresh"`.

- [ ] **9c:** Test Chinese basic section:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"basic","lang":"zh"}'
```
Expected: English fields + `basic_zh` with Chinese translations.

- [ ] **9d:** Test Chinese detailed_sense:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"detailed_sense","entry_index":0,"sense_index":0,"lang":"zh"}'
```
Expected: `detailed_sense_zh` with Chinese fields.

- [ ] **9e:** Test Chinese examples:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"examples","entry_index":0,"sense_index":0,"lang":"zh"}'
```
Expected: `zh_examples`, `zh_collocations`.

- [ ] **9f:** Test Chinese usage_notes:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"usage_notes","entry_index":0,"sense_index":0,"lang":"zh"}'
```
Expected: `zh_learner_guidance`, `zh_common_pitfalls`.

- [ ] **9g:** Test Chinese common_phrases:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"common_phrases","lang":"zh"}'
```
Expected: `zh_phrases` alongside `phrases`.

- [ ] **9h:** Test invalid lang:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"basic","lang":"fr"}'
```
Expected: 400 error with "Unsupported language 'fr'."

- [ ] **9i:** Test second request (cache hit):
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"basic","lang":"zh"}'
```
Expected: instant response, `_cache_status: "fresh"`.
