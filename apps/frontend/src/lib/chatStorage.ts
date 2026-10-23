/**
 * Browser storage keys of the AI chat page.
 * Other pages write these keys, so they live here and not in a chat component.
 */

/** localStorage key. The value "accepted" records that the user accepted the AI advisor disclaimer. */
export const CONSENT_KEY = "ai_advisor_disclaimer_v1";

/** sessionStorage key. Another page writes a prompt here; the chat page reads it once and removes it. */
export const PENDING_CHAT_PROMPT_KEY = "ai_chat_pending_prompt";
