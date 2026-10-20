"""The model ids that every configured model slot may use (#2566).

The owner instruction is that every slot uses glm-5.3-flash or glm-5.3-flashx:
primary, vision, OCR, and every fallback. This module is the one source of that
set. It has no imports, so tooling and e2e tests can load it by file path
without the backend package. config.py does not import it, because src.llm
imports src.config; tests check the config.py defaults against this set.
"""

APPROVED_MODEL_IDS: frozenset[str] = frozenset({"glm-5.3-flash", "glm-5.3-flashx"})

# Image input needs the multimodal model. Z.AI documents glm-5.3-flash under its
# text (LLM) guide and glm-5.3-flashx under its vision (VLM) guide, so only flashx
# may fill the vision, OCR and vision-fallback slots.
VISION_CAPABLE_MODEL_IDS: frozenset[str] = frozenset({"glm-5.3-flashx"})
