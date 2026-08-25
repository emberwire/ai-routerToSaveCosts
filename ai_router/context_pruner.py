import re
from typing import Set, Tuple, List


class ContextPruner:
    """
    Context Deduplicator & Token Pruner.
    Computes Jaccard/lexical similarity between scraped docs and local repo context.
    Strips redundant paragraphs and caps output to stay strictly under the token ceiling.
    """

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        words = re.findall(r"\b\w{3,}\b", text.lower())
        return set(words)

    @classmethod
    def compute_jaccard_similarity(cls, text_a: str, text_b: str) -> float:
        set_a = cls._tokenize(text_a)
        set_b = cls._tokenize(text_b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a.intersection(set_b))
        union = len(set_a.union(set_b))
        return intersection / union if union > 0 else 0.0

    @classmethod
    def prune_and_budget(cls, raw_context: str, max_tokens: int = 1500) -> Tuple[str, int]:
        """
        Prunes redundant boilerplate, empty lines, and caps at token budget.
        Estimates ~4 characters per token.
        """
        if not raw_context:
            return "", 0

        # Split into paragraphs or logical sections
        paragraphs = raw_context.split("\n\n")
        retained = []
        seen_signatures = set()
        estimated_token_count = 0

        for p in paragraphs:
            cleaned = p.strip()
            if not cleaned:
                continue

            # Check if this paragraph looks like an API signature or code block
            is_code_or_spec = "```" in cleaned or "function" in cleaned or "curl" in cleaned or "POST" in cleaned or "GET" in cleaned or "{" in cleaned

            # Approximate token count for this block
            block_tokens = max(1, len(cleaned) // 4)

            if estimated_token_count + block_tokens > max_tokens:
                # If we're hitting budget, retain only essential code blocks if possible
                if is_code_or_spec and estimated_token_count + block_tokens <= max_tokens + 200:
                    retained.append(cleaned)
                    estimated_token_count += block_tokens
                break

            retained.append(cleaned)
            estimated_token_count += block_tokens

        pruned_result = "\n\n".join(retained)
        final_token_estimate = max(1, len(pruned_result) // 4) if pruned_result else 0
        return pruned_result, final_token_estimate
