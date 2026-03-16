# Video Generation Fix: Complete Dialogue & Sequential Timing

## Problem Statement

Three critical issues with AI video generation:

1. **Missing Phrase**: Sometimes the generated video does not include the target phrase at all
2. **Truncated Dialogue**: Video stops before characters complete their lines, cutting off mid-sentence
3. **Overlapping Audio**: Multiple dialogue lines play simultaneously instead of sequentially, causing audio overlap and potentially obscuring the key phrase

**Root Cause**: The video generation API receives a conversation script but may:
- Skip lines of dialogue
- Cut off dialogue before completion
- Not follow the script exactly as written
- Play multiple dialogue lines at the same time (overlapping audio)

The conversation script itself is fine - it contains the phrase. The problem is the VIDEO doesn't follow the script sequentially.

## Solution

Strengthened the video generation prompt to:
1. Force the API to follow the script exactly and complete all dialogue
2. Explicitly prevent audio overlap with sequential timing instructions

### Changed File: `ai_svc/dictionary/video.py`

**Before**:
```python
scene_parts = [
    ...,
    f"\n\nDialogue script to animate:\n{dialogue_text}",
    "STRICT LANGUAGE RULE: Animate EXACTLY this dialogue...",
    ...
]
```

**After**:
```python
scene_parts = [
    ...,
    f"\n\n=== DIALOGUE SCRIPT ({len(dialogue_lines)} lines, ~{total_words} words) ===",
    f"{dialogue_text}",
    "\n\n=== CRITICAL REQUIREMENTS ===",
    f"1. YOU MUST ANIMATE ALL {len(dialogue_lines)} DIALOGUE LINES ABOVE - EVERY SINGLE LINE FROM START TO FINISH",
    "2. DO NOT CUT OFF any dialogue mid-sentence - let each character COMPLETE their line",
    "3. DO NOT skip or omit any lines - include ALL dialogue in sequence",
    "4. Each line must be spoken WORD-FOR-WORD exactly as written (no paraphrasing, no changes)",
    "5. Video duration MUST be sufficient to speak all dialogue at natural pace - extend duration if needed",
    "6. Use ONLY English dialogue - no Chinese, no code-switching, no translation",
    "\n\n=== TIMING & SEQUENCING (CRITICAL) ===",
    "1. PLAY DIALOGUE STRICTLY ONE-BY-ONE: Each character must speak ONLY when the previous character has completely finished",
    "2. NO OVERLAPPING AUDIO: Do NOT play multiple dialogue lines simultaneously - voices must NEVER overlap",
    "3. WAIT FOR COMPLETION: Before starting a new line, ensure the previous character's mouth has closed and audio has ended",
    "4. When one character speaks, other characters must listen silently with no mouth movement",
    "5. If the requested duration is too short to fit all dialogue sequentially at natural pace, EXTEND the video duration instead of overlapping or rushing speech",
    ...
    "\n\nREMINDER: The two most critical requirements are: (1) COMPLETE ALL DIALOGUE without cutting off, and (2) PLAY DIALOGUE ONE-BY-ONE with NO overlapping audio - each line must finish completely before the next begins."
]
```

### Key Improvements

1. **Quantified expectations**: Shows total lines and word count upfront
2. **Explicit completion requirement**: "EVERY SINGLE LINE FROM START TO FINISH"
3. **Anti-truncation**: "DO NOT CUT OFF any dialogue mid-sentence"
4. **Sequential requirement**: "include ALL dialogue in sequence"
5. **Duration flexibility**: "extend duration if needed" (gives API permission to go longer)
6. **NEW: Sequential timing controls**: 
   - "PLAY DIALOGUE STRICTLY ONE-BY-ONE"
   - "NO OVERLAPPING AUDIO"
   - "WAIT FOR COMPLETION" before next line
   - "Listening characters must remain silent"
7. **Final reminder**: Emphasizes both completion AND sequential playback

## What Changed

- ✅ Video generation prompt (more explicit, stronger requirements)
- ✅ Added word count to help API estimate duration needed
- ✅ Multiple reinforcements of "complete all dialogue"
- ✅ NEW: Explicit sequential timing section to prevent audio overlap
- ✅ NEW: Instructions for listening characters (no mouth movement)
- ✅ NEW: Duration extension permission if needed for sequential playback

## What Did NOT Change

- ✅ No script validation (script is already correct)
- ✅ No duration changes (stays at 5 seconds default, but API can extend)
- ✅ No cost changes
- ✅ No API signature changes
- ✅ No conversation script generation changes

## Testing

### API Test
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"ai_generated_phrase_video","phrase":"pipe down"}'
```

### What to Check

1. **Generated script**: Verify phrase is in the conversation (should always be there)
2. **Generated video**: 
   - Does it include ALL dialogue lines?
   - Does each line play to completion (no mid-sentence cuts)?
   - Is the target phrase spoken in the video?

### Expected Results

| Issue | Before | After |
|-------|--------|-------|
| Missing phrase | Sometimes phrase not in video | Video follows script (phrase included) |
| Truncated dialogue | Video cuts off mid-sentence | All dialogue completes fully |
| Overlapping audio | Lines play simultaneously | Each line plays one-by-one, no overlap |
| API behavior | Unpredictable | Strong guidance to complete all dialogue sequentially |

## Why This Approach

1. **Targets the root cause**: The problem is the VIDEO API behavior, not the script
2. **Explicit instructions**: Removes ambiguity about what "complete" and "sequential" mean
3. **Multiple reinforcements**: Different phrasings of the same requirement
4. **Quantified expectations**: Shows line count and word count for clarity
5. **Duration flexibility**: Allows API to extend duration if needed to fit dialogue
6. **Industry best practices**: Uses timestamp-based thinking and explicit sequencing (based on T2V industry standards from Sora, Runway, Kling, etc.)

## Research Findings

Based on research of text-to-video APIs (Volcengine Ark, OpenAI Sora, Runway Gen-4, Kling 3.0):

- **No native dialogue timing parameters** exist in Volcengine Ark API
- **Industry workaround**: Timestamp-based prompt engineering with explicit sequencing
- **Key keywords**: "one-by-one", "wait for completion", "sequentially", "no overlap"
- **Best practice**: Explicitly instruct listening characters to remain silent with no mouth movement

## Monitoring

Watch for these patterns:

1. **If phrase still missing**: The video API is ignoring entire lines → consider shortening scripts
2. **If still truncating**: The video API has hard duration limits → may need to reduce script length
3. **If videos get longer**: API is respecting "extend duration if needed" → good!
4. **If audio still overlaps**: May need to add explicit per-line timestamps (advanced solution)

## Alternative Approaches (If This Doesn't Work)

If the video API still doesn't follow instructions:

1. **Shorten conversation scripts** - fewer lines = less chance of truncation/overlap
2. **Increase default duration** - give more time for sequential dialogue
3. **Add per-line timestamps** - explicit start_time for each dialogue line (e.g., "[0-2s]: Character A speaks...")
4. **Frontend retry logic** - regenerate if video doesn't meet quality threshold
5. **Post-generation validation** - check video transcript matches script and has no overlaps

---

**Date**: 2026-03-16  
**Status**: ✅ Implemented (includes sequential timing fix)  
**Files Changed**: 1 file (`video.py`)  
**Lines Changed**: ~25 lines  
**Research**: Industry T2V best practices applied
