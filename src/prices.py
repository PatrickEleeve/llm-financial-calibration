"""Standard (non-batch) API prices in USD per 1M tokens, checked 2026-11-14.

Sources (fetched 2026-11-14):
  Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
    web search $10 / 1,000 searches; search results billed as input tokens.
    Batch API is 50% off (relevant for the no-tools condition of the full run).
  OpenAI: https://developers.openai.com/api/docs/pricing  (short context <=272K)
    web search $10 / 1k calls; search content tokens billed at model rates.
"""

PRICES = {
    # model: (input, cached_input_read, cache_write_5m, output)
    "claude-fable-5-2": (8.00, 0.20, 10.00, 40.00),
    "claude-opus-5-5": (4.00, 0.20, 5.00, 20.00),
    "claude-sonnet-5-5": (2.00, 0.10, 2.50, 10.00),
    "claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50),  # prompts <= 100K tokens
    "gpt-6.1-sol": (2.00, 0.10, None, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, None, 5.00),
    "gpt-5.5": (5.00, 0.50, None, 30.00),
    # gpt-5.6-* fetched 2026-11-14; page says the gpt-5.6-sol price is promotional until 2026-11-30.
    "gpt-5.6-sol": (4.00, 0.40, None, 20.00),
    "gpt-5.6-terra": (2.00, 0.20, None, 12.00),
    "gpt-5.6-luna": (0.20, 0.02, None, 1.20),
}
SEARCH_USD_PER_CALL = 10.00 / 1000


BATCH_TOKEN_DISCOUNT = 0.5  # both providers: batch = 50% of token prices


def cost_usd(model, input_tokens, output_tokens, cache_read=0, cache_write=0, searches=0, batch=False):
    """input_tokens = uncached input (Anthropic semantics). For OpenAI pass
    input_tokens = total - cached and cache_read = cached.
    Batch: tokens at 50%; per-search fees are conservatively kept at the full price
    (neither pricing page says they are discounted)."""
    pin, pcr, pcw, pout = PRICES[model]
    c = input_tokens * pin + output_tokens * pout + cache_read * pcr + cache_write * (pcw or pin)
    if batch:
        c *= BATCH_TOKEN_DISCOUNT
    return c / 1e6 + searches * SEARCH_USD_PER_CALL
