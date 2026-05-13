"""Output-type templates for Build mode.

Each template carries:
  - target length (in words, approximate)
  - structure hint (intro/body/CTA layout)
  - format rules specific to the medium (e.g. line breaks for LinkedIn)
  - anti-AI hints calibrated to that output type
"""
from __future__ import annotations

LENGTH_WORDS = {
    "short":  {"blog_post": 600,  "video_script": 90,  "x_thread": 5,  "linkedin_post": 180, "newsletter": 350},
    "medium": {"blog_post": 1200, "video_script": 180, "x_thread": 8,  "linkedin_post": 300, "newsletter": 600},
    "long":   {"blog_post": 2200, "video_script": 360, "x_thread": 12, "linkedin_post": 500, "newsletter": 1100},
}


OUTPUT_TYPE_SPEC: dict[str, dict] = {
    "blog_post": {
        "label": "Blog post",
        "format_rules": (
            "Plain markdown. One H1 title, then 3-5 H2 sections. Short paragraphs (2-4 sentences). "
            "Use real numbers and quotes from the assets to back claims. End with a one-paragraph takeaway "
            "— no 'in conclusion'."
        ),
        "structure": (
            "Title (H1) → hook paragraph (no header) → 3-5 sections (H2 each) → closing paragraph."
        ),
        "extra_anti_ai": (
            "Avoid the AI-blog template (definition → benefits → challenges → conclusion). "
            "Open with a specific scene, fact, or quote — not 'In today's world…'."
        ),
    },
    "video_script": {
        "label": "Video script",
        "format_rules": (
            "Plain prose, spoken cadence. No stage directions in brackets unless asked. "
            "Sentences read aloud — shorter is better. Mark beats with blank lines between sections."
        ),
        "structure": (
            "Hook (1-3 sentences, ~5 sec) → Body (the meat, 60-90% of length) → CTA (1-2 sentences, 5-10 sec)."
        ),
        "extra_anti_ai": (
            "No 'Hey guys, welcome back to my channel'. No 'don't forget to like and subscribe'. "
            "Open with a number, a quote, or a question that the body actually answers."
        ),
    },
    "x_thread": {
        "label": "X / Twitter thread",
        "format_rules": (
            "Number each tweet (1/, 2/, …). Each tweet ≤ 270 characters. "
            "Hook tweet must work standalone — assume 90% of readers stop there. "
            "Use line breaks WITHIN tweets when it helps scan-ability."
        ),
        "structure": (
            "Tweet 1: hook (the single most counterintuitive or specific claim). "
            "Tweets 2-N: one idea per tweet, each backed by a concrete fact from the assets. "
            "Last tweet: a CTA or memorable closing line. Optional final 'Subscribe / save' tweet only if asked."
        ),
        "extra_anti_ai": (
            "Don't start with 'Here's a thread on…' or '🧵 Thread time:'. "
            "No corporate emojis (📊✅🔥) unless they truly add meaning. Lower-case is fine."
        ),
    },
    "linkedin_post": {
        "label": "LinkedIn post",
        "format_rules": (
            "Plain text with line breaks between micro-paragraphs (1-2 sentences each) for skim-ability. "
            "Hook line on its own. No hashtags unless requested."
        ),
        "structure": (
            "Hook (one-liner) → micro-paragraphs that build the argument → closing line."
        ),
        "extra_anti_ai": (
            "Skip the 'I had a realization yesterday…' template. Skip 'agree?' at the end. "
            "Don't open with 'In 2024, …' or any LinkedIn cliché."
        ),
    },
    "newsletter": {
        "label": "Newsletter blurb",
        "format_rules": (
            "Conversational, email-like. Optional one-line subject suggestion at the top. "
            "Headers allowed but optional — short pieces work better without them."
        ),
        "structure": (
            "Subject line → opening hook → 2-3 short sections → kicker/CTA."
        ),
        "extra_anti_ai": (
            "Talk to the reader as a single person, not 'all of you'. Don't end with 'Stay tuned!'. "
            "Use specifics from the assets — a quote, a stat, a name — at least once per section."
        ),
    },
}


def target_words(output_type: str, length: str) -> int:
    return LENGTH_WORDS.get(length, LENGTH_WORDS["medium"]).get(output_type, 800)


def spec(output_type: str) -> dict:
    return OUTPUT_TYPE_SPEC.get(output_type, OUTPUT_TYPE_SPEC["blog_post"])


TONE_HINTS = {
    "confident":   "Sound certain. Use declarative sentences. Avoid hedges entirely.",
    "analytical":  "Sound like an investigator. Tie every claim to evidence in the assets. Numbers earn their place.",
    "casual":      "Sound like texting a friend. Contractions, short sentences, dry humor allowed. Still grounded in the assets.",
    "irreverent":  "Sound a little punk. Sharp opinions, willing to call out clichés. No edgelord posturing — wit, not snark.",
}


def tone_hint(tone: str) -> str:
    return TONE_HINTS.get(tone, TONE_HINTS["confident"])
