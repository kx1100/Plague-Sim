"""
bench_local.py — run the benchmark without Mesocosm.

`mesocosm run local` is a driver loop, not infrastructure: reset the adapter,
prompt a model with the observation, post the action back, repeat to done, then
average the terminal fields named in benchanything.json. This is that loop, with
no dependency on the Mesocosm CLI or platform.

It drives the adapter over HTTP rather than importing PlagueEnv, because the
natural-language action normalisation lives in adapter.py -- an in-process
harness would reject output that a hosted agent's would accept, and score the
model on plumbing it never sees.

Usage:
    python adapter.py                      # terminal 1
    python tools/bench_local.py            # terminal 2 (ollama/llama3.2)

    python tools/bench_local.py --model policy/expert          # no LLM, baseline
    python tools/bench_local.py --model anthropic/claude-opus-5 --max-cost 2.00
    python tools/bench_local.py --model openai/gpt-5 --base-url ... --api-key-env ...
    python tools/bench_local.py --model anthropic/claude-opus-5 --probe

Spend guards, for the paid backends:
    --probe            one call, printed in full, then exit -- check the
                       plumbing before committing to a run
    --max-calls N      hard ceiling on model calls for the whole run
                       (default: episodes x max-steps, the true worst case)
    --max-cost USD     hard ceiling on estimated spend (default 5.00 for paid
                       backends, 0 to disable)
    --skip-idle        no call on days where nothing is affordable
    Any 4xx that is not a rate limit aborts immediately, so a bad key or a bad
    model id costs one call rather than six hundred.

A tripped budget stops the run and reports the episodes that finished; it never
throws the completed work away.

Every run is recorded to `runs/<date>-<model>/run.json` and appended to
`runs/index.json`, with the provenance needed to read it back cold months later
-- seeds, every protocol setting, the system prompt, the manifest hash and the
git SHA. `--no-save` turns that off; see tools/run_store.py.
"""

import argparse
import http.client
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.calibrate import POLICIES, DEFAULT_SEEDS      # noqa: E402
from tools import run_store                              # noqa: E402

# Anthropic list prices, USD per million tokens (input, output). Used only to
# estimate spend against --max-cost; --price-in/--price-out override for any
# model that is not listed, including every non-Anthropic one.
ANTHROPIC_PRICES = {
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

_PAID_BACKENDS = ("anthropic", "openai")
_NULL_WORDS = {
    "null", "none", "nothing", "pass", "wait", "skip", "hold", "no action",
    "noop", "no-op", "n/a", "-", "",
}


# ── Failures ──────────────────────────────────────────────────────────────────

class BudgetExceeded(Exception):
    """A spend guard tripped. The run stops and reports what it has."""


class FatalAgentError(Exception):
    """Not worth retrying: bad key, bad model id, malformed request."""


class TransientAgentError(Exception):
    """Worth retrying: rate limit, 5xx, connection dropped."""


class RateLimitError(TransientAgentError):
    """A quota measured per minute. Worth retrying, but not on the seconds-long
    backoff a dropped connection deserves -- the window itself is a minute, so
    a retry that comes back inside it just spends another attempt."""


class QuotaExhausted(FatalAgentError):
    """A quota measured per day. Waiting will not clear it, so the run stops
    and keeps the episodes that finished rather than burning its retries."""


# ── Rate guard ────────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Proactive pacing for quotas measured per minute.

    A free-tier key is not a slow paid key: exceeding its rate does not cost
    more, it fails the run. The harness calls sequentially, so left alone it
    issues requests as fast as the endpoint answers -- twenty to forty a minute
    against a cap of eight -- and a sweep budgeted for an hour dies in its
    second minute, mid-episode, having already spent the quota it needed.

    Both limits are sliding sixty-second windows, because that is how the
    provider measures them: a fixed sleep between calls satisfies a request cap
    but not a token cap, and Gemma's free tier binds on tokens (16K/min) long
    before it binds on requests (30/min). Tokens are estimated from the last
    call, since what a request costs is only known once it is made.
    """

    def __init__(self, rpm: float = 0, tpm: float = 0):
        self.rpm = rpm or 0
        self.tpm = tpm or 0
        self.waited = 0.0
        self._calls: list[float] = []
        self._tokens: list[tuple[float, int]] = []
        self._last = 0

    @property
    def active(self) -> bool:
        return bool(self.rpm or self.tpm)

    def describe(self) -> str:
        parts = []
        if self.rpm:
            parts.append(f"{self.rpm:g} rpm")
        if self.tpm:
            parts.append(f"{self.tpm:g} tpm")
        return " + ".join(parts)

    def _delay(self, now: float) -> float:
        cutoff = now - 60.0
        self._calls = [t for t in self._calls if t > cutoff]
        self._tokens = [(t, n) for t, n in self._tokens if t > cutoff]

        delay = 0.0
        if self.rpm and len(self._calls) >= self.rpm:
            delay = max(delay, 60.0 - (now - self._calls[0]))
        if self.tpm and self._last and self._tokens:
            used = sum(n for _, n in self._tokens)
            if used + self._last > self.tpm:
                delay = max(delay, 60.0 - (now - self._tokens[0][0]))
        return delay

    def wait(self) -> None:
        """Block until another call fits inside every window."""
        if not self.active:
            return
        while True:
            now = time.monotonic()
            delay = self._delay(now)
            if delay <= 0:
                self._calls.append(now)
                return
            time.sleep(min(delay, 60.0))
            self.waited += min(delay, 60.0)

    def record(self, tokens: int) -> None:
        if not self.active:
            return
        self._last = tokens
        if tokens:
            self._tokens.append((time.monotonic(), tokens))


# ── Spend guard ───────────────────────────────────────────────────────────────

class Budget:
    """
    Hard ceilings on a run. Every backend reports usage through `record`, and
    every call site checks `guard` before spending, so a run can overshoot a
    limit by at most one call.
    """

    def __init__(self, max_calls: int, max_cost: float, price_in: float, price_out: float):
        self.max_calls = max_calls
        self.max_cost = max_cost          # 0 disables the cost ceiling
        self.price_in = price_in          # USD per 1M tokens, 0 = unknown
        self.price_out = price_out
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.tokens_cached = 0
        self.skipped = 0                  # days answered without a model call

    @property
    def cost(self) -> float:
        """Estimated USD. Cache reads bill at ~0.1x input, so they are cheap
        but not free; unknown prices estimate as 0 and the ceiling is inert."""
        billed_in = self.tokens_in + self.tokens_cached * 0.1
        return (billed_in * self.price_in + self.tokens_out * self.price_out) / 1_000_000

    @property
    def priced(self) -> bool:
        return self.price_in > 0 or self.price_out > 0

    def guard(self):
        if self.max_calls and self.calls >= self.max_calls:
            raise BudgetExceeded(f"call ceiling reached ({self.max_calls} calls)")
        if self.max_cost and self.priced and self.cost >= self.max_cost:
            raise BudgetExceeded(
                f"cost ceiling reached (${self.cost:.2f} of ${self.max_cost:.2f})"
            )

    def record(self, tokens_in: int = 0, tokens_out: int = 0, cached: int = 0):
        self.calls += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.tokens_cached += cached

    def summary(self) -> str:
        parts = [f"{self.calls} calls"]
        if self.skipped:
            parts.append(f"{self.skipped} days auto-passed")
        if self.tokens_in or self.tokens_out:
            parts.append(f"{self.tokens_in:,} in / {self.tokens_out:,} out tokens")
        if self.tokens_cached:
            parts.append(f"{self.tokens_cached:,} cached")
        if self.priced:
            parts.append(f"~${self.cost:.2f}")
        return " | ".join(parts)


# ── Prompting ─────────────────────────────────────────────────────────────────

# Only the fields an agent can act on. `available_traits` is the expensive one
# and it is the whole decision, so it stays; the rest is state it needs to weigh
# spending now against spending later.
_PROMPT_KEYS = (
    "day", "dna", "dna_earned", "cure_progress", "infected_pct", "dead_pct",
    "victory_progress", "countries_infected", "evolved_traits",
    "devolve_options", "available_traits",
)


def build_system_prompt(manifest: dict, extra: str | None) -> str:
    vow = manifest["binding_vow"]
    rules = "\n".join(f"- {r}" for r in manifest.get("action_rules", []))
    trees = "\n".join(
        f"- {name}: {desc}"
        for name, desc in manifest.get("traits", {}).get("trees", {}).items()
    )
    parts = [
        f"You are the agent in the '{manifest['name']}' benchmark environment.",
        manifest["description"],
        "",
        vow["description"],
        "",
        "OBSERVATION FIELDS",
        "\n".join(
            f"- {k}: {v}" for k, v in vow["observation_space"]["fields"].items()
        ),
        "",
        "TRAIT TREES",
        trees,
        "",
        "ACTION RULES",
        rules,
        "",
        f"REWARD: {vow['reward']['description']}",
        f"SCORING: ranked by {manifest['scoring']['primary_metric']}. "
        f"{manifest.get('ranking', '')}",
        "",
        "Each turn, reply in exactly this format and nothing else:",
        "REASON: <one short sentence>",
        "ACTION: <trait_id from available_traits | devolve:<trait_id> | null>",
        "",
        "ACTION must be a bare trait id with no quotes or punctuation. Use null "
        "to bank DNA for a more expensive trait later — it is a legitimate move, "
        "not a wasted turn.",
    ]
    if extra:
        parts += ["", extra]
    return "\n".join(parts)


def build_user_prompt(obs: dict, history: list[str]) -> str:
    board = {k: obs[k] for k in _PROMPT_KEYS if k in obs}
    lines = []
    if history:
        lines += ["RECENT TURNS", *history, ""]
    lines += [
        "OBSERVATION",
        json.dumps(board, indent=2, sort_keys=True),
        "",
        obs.get("action_hint", ""),
        "",
        "Your move. REASON then ACTION.",
    ]
    return "\n".join(lines)


# Reasoning a model writes into the reply body rather than a separate field.
# Gemma 4 uses <thought>; others reach for <think> or <thinking>.
_THOUGHT_BLOCK = re.compile(r"<(thought|think|thinking)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_THOUGHT_CLOSE = re.compile(r"</(?:thought|think|thinking)\s*>", re.I)
_THOUGHT_OPEN = re.compile(r"<(?:thought|think|thinking)\b[^>]*>", re.I)


def strip_thoughts(text: str) -> str:
    """
    Drop an inline reasoning block, closed or not.

    A model that reasons in the reply body and then runs out of tokens leaves a
    fragment ending in a closing tag and never reaches its answer. Left in,
    `parse_reply` takes that fragment's last line as the action, and the
    environment records a move it could not read -- which lands in the bucket
    that means "the parser failed", and hides the warning that would have named
    the actual cause: the model needed more room to answer.

    An unmatched closing tag means the reasoning began before it; an unmatched
    opening tag means it never ended. Both leave nothing usable on the far side.
    """
    cleaned = _THOUGHT_BLOCK.sub(" ", text)
    closes = list(_THOUGHT_CLOSE.finditer(cleaned))
    if closes:
        cleaned = cleaned[closes[-1].end():]
    opened = _THOUGHT_OPEN.search(cleaned)
    if opened:
        cleaned = cleaned[:opened.start()]
    return cleaned


def parse_reply(text: str) -> tuple[str | None, str]:
    """
    Pull (action, reasoning) out of a model reply.

    Deliberately lenient on the action: whatever survives here still goes
    through the adapter's own fuzzy matcher, which is the behaviour a hosted
    agent gets. Being stricter here would score models on format compliance
    that the real harness forgives.
    """
    text = strip_thoughts(text)
    if not text.strip():
        # Nothing but reasoning: the answer never arrived. Reported as an empty
        # reply, which is what it is, so the truncation warning can fire.
        return None, ""

    reasoning, action_line = "", None
    for line in text.splitlines():
        stripped = line.strip().lstrip("*# ").strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low.startswith("reason"):
            reasoning = stripped.split(":", 1)[-1].strip()
        elif low.startswith("action"):
            action_line = stripped.split(":", 1)[-1].strip()

    if action_line is None:
        # No ACTION line. Take the last non-empty line as the answer and treat
        # everything before it as the reasoning -- the common shape when a
        # weaker model narrates first and names the trait last.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return None, ""
        action_line = lines[-1]
        reasoning = reasoning or " ".join(lines[:-1])[:500]

    return _clean_action(action_line), (reasoning or action_line)[:500]


def _clean_action(raw: str) -> str | None:
    # Backticks and asterisks first: "**ACTION:** Air1" leaves a stray "**"
    # on the value once the label is split off, and bold is what models reach
    # for when asked to emphasise a field.
    action = raw.strip().strip("`*").strip()
    if action.startswith("{"):
        try:
            action = str(json.loads(action).get("action", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
    action = action.strip().strip("\"'`*").rstrip(".!,").strip()
    if action.lower() in _NULL_WORDS:
        return None
    # The adapter matches trait names and stems inside free text, so a long
    # reply is still usable; cap it so a runaway response is not posted whole.
    return action[:500]


# ── Agents ────────────────────────────────────────────────────────────────────

class Agent:
    """Turns an observation into (action, reasoning)."""

    uses_model = True

    def act(self, obs: dict, history: list[str]) -> tuple[str | None, str]:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def provenance(self) -> dict:
        """
        Whatever pins down which model this actually was. A tag is mutable --
        `llama3.2` means whatever `latest` points at on the day -- and a run
        published permanently under a name that can be repointed is not a
        reproducible result. Best effort: a backend that cannot say returns {}.
        """
        return {}

    def begin_episode(self, rng_seed) -> None:
        """Called after reset, for an agent whose own choices need seeding."""


class PolicyAgent(Agent):
    """A reference policy from tools/calibrate.py. No model, no spend."""

    uses_model = False

    def __init__(self, name: str):
        if name not in POLICIES:
            raise SystemExit(
                f"Unknown policy '{name}'. Choose from: {', '.join(POLICIES)}"
            )
        self.name = name
        self.policy = POLICIES[name]

    def act(self, obs, history):
        action = self.policy(obs)
        return action, f"policy/{self.name}: {action or 'pass'}"

    def begin_episode(self, rng_seed):
        """
        `policy_random` draws from the module generator, which nothing here was
        seeding -- so the one baseline with any randomness in it scored
        differently on every run, and a published `random` line that a reader
        cannot reproduce is worse than no baseline at all. Seeded from the
        episode's own seed rather than its position in the list, so `random` on
        Russia plays the same game whether Russia is run alone or ninth.
        """
        random.seed(rng_seed)

    def describe(self):
        return f"policy/{self.name} (reference policy, not a language model)"


class _PromptedAgent(Agent):
    """Shared plumbing for the backends that actually prompt a model."""

    def __init__(self, model: str, system_prompt: str, budget: Budget, retries: int):
        self.model = model
        self.system_prompt = system_prompt
        self.budget = budget
        self.retries = retries
        # Replaced by build_agent when --rpm/--tpm are set. Inert by default, so
        # a paid key pays no pacing cost it did not ask for.
        self.limiter = RateLimiter()

    def act(self, obs, history):
        user = build_user_prompt(obs, history)
        return self.complete(user)

    def complete(self, user: str) -> tuple[str | None, str]:
        last = None
        for attempt in range(self.retries + 1):
            self.budget.guard()
            self.limiter.wait()
            spent = self.budget.tokens_in + self.budget.tokens_out
            try:
                raw = self._call(user)
            except RateLimitError as exc:
                # The window is a minute wide, so seconds of backoff only spend
                # attempts. Climb towards it instead.
                last = exc
                if attempt < self.retries:
                    time.sleep(min(20 * 2 ** attempt, 60))
                continue
            except TransientAgentError as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
                continue
            finally:
                # Tokens are spent whether or not the reply parses, and the
                # limiter has to know before it paces the next call.
                self.limiter.record(self.budget.tokens_in + self.budget.tokens_out - spent)
            return parse_reply(raw)
        raise FatalAgentError(f"gave up after {self.retries + 1} attempts: {last}")

    def _call(self, user: str) -> str:
        raise NotImplementedError


class OllamaAgent(_PromptedAgent):
    """Local Ollama. What `mesocosm run local` used, and free."""

    def __init__(self, model, system_prompt, budget, retries, host, temperature,
                 max_tokens, think=None):
        super().__init__(model, system_prompt, budget, retries)
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.think = think          # None = leave the model's own default alone

    def _call(self, user):
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        if self.think is not None:
            payload["think"] = self.think
        body, status = _post_json(f"{self.host}/api/chat", payload, timeout=300)
        if status == 404:
            raise FatalAgentError(
                f"Ollama has no model '{self.model}'. Pull it: ollama pull {self.model}"
            )
        if status >= 400:
            raise TransientAgentError(f"ollama {status}: {body[:200]}")
        data = json.loads(body)
        self.budget.record(
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
        )

        message = data.get("message", {})
        content = (message.get("content") or "").strip()
        # Thinking models (qwen3, deepseek-r1) return their reasoning in a
        # separate field, and num_predict covers thinking AND content -- so a
        # budget that looks generous can be spent entirely on thinking, leaving
        # content empty. That reads downstream as "the model passed", which
        # would score a capable model as if it sat out the game.
        thinking = (message.get("thinking") or "").strip()
        if not content and thinking:
            raise FatalAgentError(
                f"{self.model} used its whole {self.max_tokens}-token budget thinking "
                f"and never answered. Raise --max-tokens (4096 is usually enough), "
                f"or disable thinking with --ollama-think off."
            )
        if thinking and "REASON" not in content:
            # Keep something readable for the replay when the model answered
            # with a bare action and put its argument in the thinking field.
            summary = thinking.splitlines()[-1][:300]
            content = "\n".join([f"REASON: {summary}", content])
        return content

    def describe(self):
        think = "" if self.think is None else f", think={'on' if self.think else 'off'}"
        return f"ollama/{self.model} at {self.host}{think}"

    def provenance(self):
        """
        The weights behind the tag: digest, parameter count and quantization.
        `llama3.2` is 3.2B Q4_K_M today and could be repointed tomorrow, and a
        published comparison has to say which one it measured.
        """
        try:
            body, status = _post_json(
                f"{self.host}/api/show", {"model": self.model}, timeout=30
            )
            if status >= 400:
                return {}
            shown = json.loads(body)
        except (TransientAgentError, json.JSONDecodeError):
            return {}

        details = shown.get("details") or {}
        info = shown.get("model_info") or {}
        found = {
            "resolved_from": self.model,
            "family": details.get("family"),
            "parameter_size": details.get("parameter_size"),
            "parameter_count": info.get("general.parameter_count"),
            "quantization_level": details.get("quantization_level"),
            "format": details.get("format"),
            "basename": info.get("general.basename"),
            "finetune": info.get("general.finetune"),
            "digest": self._digest(),
        }
        return {key: value for key, value in found.items() if value is not None}

    def _digest(self):
        """Ollama reports it on the tag listing rather than on /api/show."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=15) as resp:
                tags = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        for entry in tags.get("models", []):
            if entry.get("name") == wanted:
                return entry.get("digest")
        return None


class AnthropicAgent(_PromptedAgent):
    """
    Claude via the official SDK.

    The system prompt is identical on every one of the ~600 calls in an
    episode, so it carries a cache breakpoint: cached reads bill at about a
    tenth of input rate, which is most of the prompt cost in a run this shaped.
    """

    def __init__(self, model, system_prompt, budget, retries, effort, thinking, max_tokens):
        super().__init__(model, system_prompt, budget, retries)
        try:
            import anthropic
        except ImportError:
            raise SystemExit(
                "The anthropic backend needs the SDK:\n"
                "    .venv/Scripts/python.exe -m pip install anthropic"
            )
        self._sdk = anthropic
        # One SDK-level retry; `complete` handles the rest so retries count
        # against the call budget rather than hiding underneath it.
        self.client = anthropic.Anthropic(max_retries=1)
        self.effort = effort
        self.thinking = thinking
        self.max_tokens = max_tokens

    def _call(self, user):
        sdk = self._sdk
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": [{"role": "user", "content": user}],
        }
        if self.thinking == "adaptive":
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        else:
            kwargs["thinking"] = {"type": "disabled"}
        if self.effort != "none":
            kwargs["output_config"] = {"effort": self.effort}

        try:
            resp = self.client.messages.create(**kwargs)
        except (sdk.AuthenticationError, sdk.PermissionDeniedError) as exc:
            raise FatalAgentError(f"auth rejected: {exc}")
        except sdk.NotFoundError as exc:
            raise FatalAgentError(f"no such model '{self.model}': {exc}")
        except sdk.BadRequestError as exc:
            # Usually an unsupported parameter for this model -- effort and
            # thinking are model-gated. Retrying spends money on the same 400.
            raise FatalAgentError(
                f"request rejected: {exc}\n"
                f"  If the model predates the Opus 5 family, try "
                f"--effort none --thinking off."
            )
        except sdk.RateLimitError as exc:
            raise TransientAgentError(f"rate limited: {exc}")
        except sdk.APIConnectionError as exc:
            raise TransientAgentError(f"connection failed: {exc}")
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientAgentError(f"server error {exc.status_code}: {exc}")
            raise FatalAgentError(f"API error {exc.status_code}: {exc}")

        usage = resp.usage
        self.budget.record(
            tokens_in=usage.input_tokens + (usage.cache_creation_input_tokens or 0),
            tokens_out=usage.output_tokens,
            cached=usage.cache_read_input_tokens or 0,
        )
        if resp.stop_reason == "refusal":
            return "ACTION: null"
        return "".join(b.text for b in resp.content if b.type == "text")

    def describe(self):
        return f"anthropic/{self.model} (effort={self.effort}, thinking={self.thinking})"


class OpenAICompatAgent(_PromptedAgent):
    """
    Any /v1/chat/completions endpoint: OpenAI, OpenRouter, vLLM, LM Studio, and
    Gemini through Google's OpenAI-compatibility layer at
    https://generativelanguage.googleapis.com/v1beta/openai
    """

    def __init__(self, model, system_prompt, budget, retries, base_url, api_key,
                 temperature, max_tokens):
        super().__init__(model, system_prompt, budget, retries)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _call(self, user):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body, status = _post_json(
            f"{self.base_url}/chat/completions", payload, timeout=300, headers=headers
        )
        if status in (400, 401, 403, 404):
            raise FatalAgentError(f"{status} from {self.base_url}: {body[:300]}")
        if status == 429:
            # Google reports both caps as 429. A daily one will not clear by
            # waiting, so it stops the run cleanly -- with the finished
            # episodes saved -- rather than sleeping out the retries first.
            if re.search(r"per\s*day|perday|daily", body, re.I):
                raise QuotaExhausted(
                    f"daily quota exhausted for {self.model}: {body[:200]}"
                )
            raise RateLimitError(f"rate limited: {body[:200]}")
        if status >= 400:
            raise TransientAgentError(f"{status}: {body[:200]}")

        data = json.loads(body)
        usage = data.get("usage") or {}
        self.budget.record(
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )
        choices = data.get("choices") or []
        if not choices:
            raise TransientAgentError(f"no choices in response: {body[:200]}")
        return choices[0].get("message", {}).get("content") or ""

    def describe(self):
        return f"openai-compatible {self.model} at {self.base_url}"


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, timeout: float, headers: dict | None = None):
    """POST JSON, returning (body_text, status). Never raises on HTTP status."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), resp.status
    except urllib.error.HTTPError as exc:
        return exc.read().decode("utf-8", "replace"), exc.code
    except urllib.error.URLError as exc:
        raise TransientAgentError(f"cannot reach {url}: {exc.reason}")
    except (http.client.HTTPException, OSError) as exc:
        # A connection dropped *mid-response* lands here rather than as a
        # URLError: urllib wraps what `request()` raises, but re-raises
        # whatever `getresponse()` throws. RemoteDisconnected is the common
        # one, and it is exactly the "connection dropped" case this error
        # class exists for -- uncaught it escaped the retry loop, escaped
        # run_episode, and took a four-hour sweep down with it.
        raise TransientAgentError(f"{type(exc).__name__} from {url}: {exc}")


class EnvClient:
    """The adapter, over HTTP. Same surface a hosted run talks to."""

    def __init__(self, url: str, timeout: float = 60.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def reset(self, seed, rng_seed=None):
        out = self._post("/reset", {"seed": seed, "rng_seed": rng_seed})
        # Older adapters do not echo the seed; fall back to what was asked for
        # rather than recording a null into the run.
        return out["observation"], out.get("rng_seed", rng_seed if rng_seed is not None else seed)

    def step(self, action):
        out = self._post("/step", {"action": action})
        return out["observation"], out["reward"], out["done"], out["info"]

    def close(self):
        try:
            self._post("/close", {})
        except Exception:
            pass

    def _post(self, path, payload):
        body, status = _post_json(f"{self.url}{path}", payload, self.timeout)
        data = json.loads(body)
        if status >= 400 or "error" in data:
            raise SystemExit(f"adapter {path} failed: {data.get('error', body[:200])}")
        return data


# ── Episode loop ──────────────────────────────────────────────────────────────

# Rejected replies kept per episode. Enough to see the shape of the failure --
# whether it is one systematic mistake or many different ones -- without
# turning a committed record into a transcript.
_REJECTION_SAMPLES = 25

_OBS_KEYS = (
    "day", "dna", "dna_earned", "cure_progress", "infected_pct", "dead_pct",
    "victory_progress", "countries_infected",
)
_AFTER_KEYS = _OBS_KEYS + ("evolved_traits",)


def run_episode(env: EnvClient, agent: Agent, seed, budget: Budget, args) -> dict:
    obs, rng_seed = env.reset(seed, args.rng_seed)
    agent.begin_episode(rng_seed)
    turns, history, done, step = [], [], False, 0
    truncated, terminal = None, None
    # Budget counters run for the whole run, so an episode's own usage is the
    # delta across it. Recorded per episode because that is the unit a reader
    # compares: "gemma3 costs 452s an episode" is the number that decides
    # whether a ten-seed sweep fits in a night.
    started_at = time.time()
    spent = (budget.calls, budget.tokens_in, budget.tokens_out, budget.tokens_cached)
    # What the model's turns actually did. A score is only a measure of play if
    # the actions were understood: a model whose every reply is rejected scores
    # the same as one that deliberately passes all game, and without this the
    # two are indistinguishable in the results.
    health = dict(accepted=0, rejected_unknown=0, rejected_illegal=0,
                  passed=0, auto_passed=0, unparsed=0)
    # What the rejected replies actually said. A count alone tells you a run
    # failed without telling you why, and that is not recoverable afterwards:
    # a five-hour sweep that rejected 42% of its moves left no evidence of what
    # it had emitted, because the raw strings only ever went to a --verbose
    # stdout nobody had asked for. Capped, because the point is a diagnosis,
    # not a transcript.
    rejections: list[dict] = []

    while not done and step < args.max_steps:
        step += 1
        before = obs

        if args.skip_idle and not before["available_traits"] and agent.uses_model:
            # The only moves left are null or a devolve-for-refund. Spending a
            # model call to hear "null" is the bulk of an episode's cost.
            action, reasoning = None, "auto-pass: nothing affordable"
            budget.skipped += 1
            health["auto_passed"] += 1
        else:
            try:
                action, reasoning = agent.act(before, history)
            except BudgetExceeded:
                truncated = "budget"
                break
            except FatalAgentError as exc:
                print(f"\n  agent failed: {exc}", file=sys.stderr)
                truncated = "agent-error"
                break

        obs, reward, done, info = env.step(action)
        # The adapter normalises free text into a trait ID; prefer what it
        # actually played so the replay and the purchase history are readable.
        played = info.get("action", action)
        if done:
            # env.step merges final_score() into info on the terminating step.
            # Grab it before the per-turn filter below drops everything the
            # replay does not read.
            terminal = info.get("score")

        accepted = info.get("action_accepted")
        if action is None:
            if not (args.skip_idle and not before["available_traits"] and agent.uses_model):
                # An empty reply and a deliberate "null" both reach the env as
                # no action, but they mean opposite things about the model.
                health["unparsed" if not reasoning.strip() else "passed"] += 1
        elif info.get("action_error"):
            # Two different failures wear the same "rejected" label, and they
            # belong to different people. An unreadable trait ID is the
            # harness's problem -- the reply parser did not recover what the
            # model meant. A legal-but-wrong move (buying a trait it already
            # owns, or cannot afford) is the model's, and is exactly the
            # long-horizon state-tracking the benchmark exists to measure.
            if "not a valid trait ID" in info["action_error"]:
                health["rejected_unknown"] += 1
            else:
                health["rejected_illegal"] += 1
        else:
            health["accepted"] += 1

        if info.get("action_error"):
            if len(rejections) < _REJECTION_SAMPLES:
                rejections.append({
                    "day": info["day"],
                    "replied": action,
                    "error": info["action_error"],
                })
            if args.verbose:
                print(f"    day {info['day']}: rejected {action!r} — {info['action_error']}")
        history.append(
            f"day {info['day']}: {played or 'pass'}"
            f"{'' if accepted is not False else ' (rejected)'}"
            f" | infected {obs['infected_pct']}% dead {obs['dead_pct']}%"
            f" cure {obs['cure_progress'] * 100:.0f}% dna {obs['dna']}"
        )
        history[:] = history[-args.history:] if args.history else []

        turns.append({
            "step": step,
            "observation": {k: before[k] for k in _OBS_KEYS},
            "board_before": {k: before[k] for k in _OBS_KEYS},
            "board_after": {k: obs[k] for k in _AFTER_KEYS},
            "reasoning": reasoning,
            "action": played,
            "reward": reward,
            "terminated": done,
            "info": {
                "day": info["day"],
                "dna": info["dna"],
                "cure_progress": info["cure_progress"],
                "outcome": info["outcome"],
                "action_accepted": accepted,
                "world": info["world"],
            },
        })

        if args.verbose and info["day"] % 30 == 0:
            print(
                f"    day {info['day']:>3} | infected {obs['infected_pct']:>6.2f}% "
                f"| dead {obs['dead_pct']:>5.2f}% | cure {obs['cure_progress'] * 100:>5.1f}% "
                f"| dna {obs['dna']:>3} | {budget.calls} calls"
            )

    score = terminal or (_incomplete_score(turns) if turns else {})
    if turns:
        turns[-1]["episode_end"] = {
            "total_reward": round(sum(t["reward"] for t in turns), 4),
            "steps": step,
            "status": "completed" if done else (truncated or "max_steps"),
            "terminal_info": score,
        }
    return {
        "seed": seed,
        "rng_seed": rng_seed,
        "health": health,
        "rejections": rejections,
        "steps": step,
        "done": done,
        "truncated": truncated,
        "score": score,
        "turns": turns,
        "wall_time_seconds": round(time.time() - started_at, 1),
        "usage": {
            "calls": budget.calls - spent[0],
            "tokens_in": budget.tokens_in - spent[1],
            "tokens_out": budget.tokens_out - spent[2],
            "tokens_cached": budget.tokens_cached - spent[3],
        },
    }


def _incomplete_score(turns: list[dict]) -> dict:
    """
    Stand-in terminal for an episode cut short by a budget or an agent error,
    so a stopped run reports the board it reached rather than nothing at all.
    Marked `incomplete` -- these are not comparable to a finished episode, and
    `aggregate` counts them only for the fields they actually carry.
    """
    board = turns[-1]["board_after"]
    return {
        "outcome": None,
        "day": board["day"],
        "victory_progress": board["victory_progress"],
        "dead_pct": board["dead_pct"],
        "affected_pct": round(board["infected_pct"] + board["dead_pct"], 2),
        "incomplete": True,
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

# Two-sided 95% critical values of Student's t, by degrees of freedom. A ten
# seed sweep has df=9, where the normal 1.96 understates the interval by about
# 15% -- the difference between two models reading as tied and reading as
# ranked. Past df=30 the gap stops mattering and 1.96 is used.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _spread(values: list[float]) -> dict:
    """
    The sample spread across seeds, and the 95% interval around the mean.

    A bare mean invites the one error this benchmark cannot afford: reading a
    0.003 gap between two models as a ranking. Ten seeds is a small sample and
    the per-seed scores are far apart, so the interval is wide, and two models
    whose intervals overlap have not been told apart by the run. That belongs
    in the record itself -- a reader comparing two published runs will not
    recompute it from the episode list, so a mean published alone will be
    compared as though it were exact.
    """
    n = len(values)
    if n < 2:
        # One episode has a mean but no spread. None, not 0.0, which would read
        # as a model that scored identically every time.
        return {"sd": None, "sem": None, "ci95": None}
    mean = sum(values) / n
    sd = statistics.stdev(values)
    sem = sd / math.sqrt(n)
    half = _T95.get(n - 1, 1.96) * sem
    return {
        "sd": round(sd, 6),
        "sem": round(sem, 6),
        "ci95": [round(mean - half, 6), round(mean + half, 6)],
    }


def metric_means(manifest: dict, episodes: list[dict]) -> dict[str, dict]:
    """
    Mean of each terminal_field metric named in the manifest, with the count it
    was taken over and the spread around it. `n` below `episodes` means some
    episode did not report the field -- a budget-stopped one, usually -- and a
    reader must see that rather than a mean quietly taken over fewer runs than
    it claims.
    """
    means = {}
    for metric in manifest["scoring"]["metrics"]:
        if metric.get("type") != "terminal_field":
            continue
        field = metric["field"]
        values = [
            ep["score"][field] for ep in episodes
            if ep["score"] and isinstance(ep["score"].get(field), (int, float))
        ]
        means[metric["name"]] = {
            "field": field,
            "mean": sum(values) / len(values) if values else None,
            **_spread(values),
            "n": len(values),
            "episodes": len(episodes),
        }
    return means


def aggregate(manifest: dict, episodes: list[dict]) -> list[tuple[str, str]]:
    """The same means, formatted for the terminal -- each beside the spread
    that says whether it can be told apart from the next model's."""
    rows = []
    for name, stat in metric_means(manifest, episodes).items():
        if stat["mean"] is None:
            rows.append((name, "n/a"))
            continue
        note = "" if stat["n"] == stat["episodes"] else f"  (n={stat['n']})"
        spread = ""
        if stat["ci95"]:
            low, high = stat["ci95"]
            spread = f"  sd {stat['sd']:.4f}   95% CI [{low:.4f}, {high:.4f}]"
        rows.append((name, f"{stat['mean']:.4f}{spread}{note}"))
    return rows


def outcome_counts(episodes: list[dict]) -> dict[str, int]:
    counts = {}
    for ep in episodes:
        key = (ep["score"] or {}).get("outcome") or "incomplete"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def health_totals(episodes: list[dict]) -> dict[str, int]:
    """
    Sum the per-episode counters. Only the integer counters: a health block
    read back off disk also carries the derived `rates`, and re-aggregating a
    saved run -- comparing two published records, say -- is a normal thing to
    do, so summing must not choke on a value that is not a tally.
    """
    total = dict(accepted=0, rejected_unknown=0, rejected_illegal=0,
                 passed=0, auto_passed=0, unparsed=0)
    for ep in episodes:
        for key, value in (ep.get("health") or {}).items():
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            total[key] = total.get(key, 0) + value
    return total


def health_rates(total: dict[str, int]) -> dict:
    """
    The rejection counts as proportions of what the model actually attempted.

    A rejected move is a move the environment threw away, so a model with a
    fifth of its actions rejected only really played four turns in five --
    the rest of its score is whatever the simulation did unattended. The raw
    counts do not show that on their own: `103 illegal` means something very
    different beside 393 accepted than beside 3900, and a reader comparing two
    published runs should not have to do the division to find out which they
    are looking at.
    """
    rejected = total["rejected_unknown"] + total["rejected_illegal"]
    attempted = total["accepted"] + rejected
    if not attempted:
        # A run of pure passes -- the reference `pass` policy, say. No move was
        # attempted, so there is no rate; 0.0 would claim a clean record.
        return {"attempted": 0, "rejected": rejected, "rejected_rate": None,
                "illegal_rate": None, "unreadable_rate": None}
    return {
        "attempted": attempted,
        "rejected": rejected,
        "rejected_rate": round(rejected / attempted, 4),
        "illegal_rate": round(total["rejected_illegal"] / attempted, 4),
        "unreadable_rate": round(total["rejected_unknown"] / attempted, 4),
    }


def health_with_rates(episodes: list[dict]) -> dict:
    """The counts the record stores, with the rates alongside them. Nested so
    that `health_totals` stays a pure sum of integers."""
    total = health_totals(episodes)
    return {**total, "rates": health_rates(total)}


def action_health(episodes: list[dict]) -> tuple[str, str | None]:
    """
    Summarise what the model's turns did, and warn when a score is not really
    about play. A rejection rate above a quarter means the number below is
    substantially a measure of how well the model matched an output format --
    publish that as a capability result and it is simply wrong.
    """
    total = health_totals(episodes)

    rates = health_rates(total)
    rejected, attempted = rates["rejected"], rates["attempted"]
    # The share, not just the count: it is the figure that says how much of the
    # score below was actually played.
    share = "" if rates["rejected_rate"] is None else f" — {rates['rejected_rate']:.0%} of attempted"
    line = (
        f"{total['accepted']} accepted, {rejected} rejected{share} "
        f"({total['rejected_illegal']} illegal moves, "
        f"{total['rejected_unknown']} unreadable), "
        f"{total['passed']} passed, {total['auto_passed']} auto-passed"
    )
    if total["unparsed"]:
        line += f", {total['unparsed']} empty replies"

    warning = None
    if attempted and total["rejected_unknown"] / attempted > 0.10:
        # Only the unreadable ones implicate the harness. Illegal moves are a
        # result, not a defect, so they must not trigger a "your numbers are
        # suspect" warning -- that would train the reader to discount exactly
        # the failure the benchmark is measuring.
        warning = (
            f"{total['rejected_unknown'] / attempted:.0%} of attempted actions could not "
            f"be read as a trait ID. That is the reply parser failing, not the model "
            f"playing badly — inspect with --verbose before reporting these scores."
        )
    elif total["unparsed"] > max(3, 0.1 * (attempted + total["passed"])):
        warning = (
            f"{total['unparsed']} turns produced no readable reply. If this is a "
            f"reasoning model, --max-tokens may be truncating it before it answers."
        )
    return line, warning


# ── Wiring ────────────────────────────────────────────────────────────────────

def build_agent(args, system_prompt: str, budget: Budget) -> Agent:
    agent = _construct_agent(args, system_prompt, budget)
    if isinstance(agent, _PromptedAgent):
        agent.limiter = RateLimiter(args.rpm, args.tpm)
    return agent


def _construct_agent(args, system_prompt: str, budget: Budget) -> Agent:
    backend, _, model = args.model.partition("/")
    if not model and backend not in POLICIES:
        raise SystemExit(
            "--model must be <backend>/<model>, e.g. ollama/llama3.2, "
            "policy/expert, anthropic/claude-opus-5, openai/gpt-5"
        )

    if backend == "policy":
        return PolicyAgent(model)
    if backend == "ollama":
        think = None if args.ollama_think == "auto" else (args.ollama_think == "on")
        return OllamaAgent(
            model, system_prompt, budget, args.retries,
            args.ollama_host, args.temperature, args.max_tokens, think,
        )
    if backend == "anthropic":
        return AnthropicAgent(
            model, system_prompt, budget, args.retries,
            args.effort, args.thinking, args.max_tokens,
        )
    if backend == "openai":
        key = os.environ.get(args.api_key_env, "")
        if not key:
            raise SystemExit(
                f"${args.api_key_env} is not set. Set it, or point --api-key-env "
                f"at the variable holding the key for {args.base_url}."
            )
        return OpenAICompatAgent(
            model, system_prompt, budget, args.retries,
            args.base_url, key, args.temperature, args.max_tokens,
        )
    raise SystemExit(f"Unknown backend '{backend}'. Use policy, ollama, anthropic or openai.")


def resolve_prices(args) -> tuple[float, float]:
    if args.price_in is not None or args.price_out is not None:
        return args.price_in or 0.0, args.price_out or 0.0
    backend, _, model = args.model.partition("/")
    if backend == "anthropic":
        for known, prices in ANTHROPIC_PRICES.items():
            if model == known or model.startswith(known):
                return prices
    return 0.0, 0.0


def parse_seeds(raw: str | None, episodes: int) -> list:
    if not raw:
        return DEFAULT_SEEDS[:episodes] if episodes <= len(DEFAULT_SEEDS) else (
            DEFAULT_SEEDS * (episodes // len(DEFAULT_SEEDS) + 1)
        )[:episodes]
    seeds = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        seeds.append(int(token) if token.lstrip("-").isdigit() else token)
    return seeds


def _display_path(path: Path) -> str:
    """Repo-relative where it is inside the repo, absolute otherwise."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _force_utf8_output() -> None:
    """
    Windows hands a redirected run the cp1252 codepage, and the summary prints
    `→`, `±` and box-drawing characters. Piping a sweep to a log file therefore
    dies on the first episode summary with UnicodeEncodeError -- after the
    episode has been played and paid for, and before anything is written to
    `runs/`. The one place that is worth guarding is a paid sweep someone
    sensibly decided to keep a log of.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass                            # already UTF-8, or not reconfigurable


def main() -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default="ollama/llama3.2",
                        help="<backend>/<model>: ollama/…, anthropic/…, openai/…, policy/…")
    parser.add_argument("--episodes", type=int, default=5,
                        help="Episode count. Ignored when --seeds names them explicitly.")
    parser.add_argument("--seeds", help="Comma-separated country names or integers")
    parser.add_argument("--rng-seed", type=int,
                        help="Force every episode's world RNG to this seed. Omitted, each "
                             "episode derives it from its own seed, so a seed list replays "
                             "identically for every model — which is what makes two models' "
                             "scores comparable.")
    parser.add_argument("--max-steps", type=int, default=600, help="Day cap per episode")
    parser.add_argument("--env-url", default="http://localhost:8765")
    parser.add_argument("--manifest", default=str(ROOT / "benchanything.json"))
    parser.add_argument("--system-prompt", help="Extra instruction appended for the agent")
    parser.add_argument("--history", type=int, default=8,
                        help="Recent turns shown to the model (0 for none)")

    parser.add_argument("--skip-idle", action="store_true",
                        help="Auto-pass days with no affordable trait, without a model call")
    parser.add_argument("--max-calls", type=int,
                        help="Hard ceiling on model calls (default: episodes x max-steps)")
    parser.add_argument("--max-cost", type=float,
                        help="Hard ceiling on estimated USD (default 5.00 for paid backends, 0 disables)")
    parser.add_argument("--price-in", type=float, help="USD per 1M input tokens, for cost estimates")
    parser.add_argument("--price-out", type=float, help="USD per 1M output tokens")
    parser.add_argument("--probe", action="store_true",
                        help="One model call on a fresh board, printed in full, then exit")
    parser.add_argument("--retries", type=int, default=2, help="Retries per transient failure")
    parser.add_argument("--rpm", type=float, default=0,
                        help="Pace calls to this many requests per minute (0 = no pacing). "
                             "Set it to the key's quota: on a free tier, exceeding the rate "
                             "fails the run rather than costing more.")
    parser.add_argument("--tpm", type=float, default=0,
                        help="Pace calls to this many tokens per minute (0 = no pacing). "
                             "The binding limit on some free tiers — Gemma allows 30 rpm but "
                             "only 16K tpm, and one turn of this benchmark costs ~1.8K.")

    parser.add_argument("--temperature", type=float, default=0.3,
                        help="ollama and openai backends (Claude models reject it)")
    parser.add_argument("--max-tokens", type=int, default=1024, help="Response cap per call")
    parser.add_argument("--effort", default="medium",
                        choices=["none", "low", "medium", "high", "xhigh", "max"],
                        help="anthropic backend: output_config.effort ('none' omits it)")
    parser.add_argument("--thinking", default="adaptive", choices=["adaptive", "off"],
                        help="anthropic backend: adaptive thinking")
    parser.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    parser.add_argument("--ollama-think", default="auto", choices=["auto", "on", "off"],
                        help="Thinking models (qwen3, deepseek-r1): 'auto' leaves the "
                             "model's own default, which spends --max-tokens on thinking "
                             "before it answers.")
    parser.add_argument("--base-url", default="https://api.openai.com/v1",
                        help="openai backend endpoint, e.g. "
                             "https://generativelanguage.googleapis.com/v1beta/openai for Gemini")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY",
                        help="Env var holding the key for --base-url (e.g. GEMINI_API_KEY)")

    parser.add_argument("--export", help="Write the run to PATH in the run-export shape")
    parser.add_argument("--runs-dir", default=str(run_store.RUNS_DIR),
                        help="Where run records are kept (default: runs/)")
    parser.add_argument("--no-save", dest="save_run", action="store_false",
                        help="Do not write a run record. Saving is the default because "
                             "a sweep that only ever reached a terminal is not a result.")
    parser.add_argument("--quiet", dest="verbose", action="store_false",
                        help="Suppress the per-30-day progress lines")
    args = parser.parse_args()

    manifest_text = Path(args.manifest).read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    system_prompt = build_system_prompt(manifest, args.system_prompt)

    seeds = parse_seeds(args.seeds, args.episodes)
    price_in, price_out = resolve_prices(args)
    backend = args.model.partition("/")[0]
    paid = backend in _PAID_BACKENDS
    max_cost = args.max_cost if args.max_cost is not None else (5.00 if paid else 0.0)
    budget = Budget(
        max_calls=args.max_calls if args.max_calls is not None else len(seeds) * args.max_steps,
        max_cost=max_cost,
        price_in=price_in,
        price_out=price_out,
    )
    agent = build_agent(args, system_prompt, budget)

    env = EnvClient(args.env_url)
    if not env.health():
        raise SystemExit(
            f"No adapter at {args.env_url}. Start it first:\n"
            f"    python adapter.py"
        )

    print(f"agent      : {agent.describe()}")
    if agent.uses_model:
        caps = [f"{budget.max_calls} calls"]
        if max_cost and budget.priced:
            caps.append(f"${max_cost:.2f}")
        elif paid and not budget.priced:
            caps.append("cost unknown — pass --price-in/--price-out to enforce a $ cap")
        if agent.limiter.active:
            caps.append(f"paced to {agent.limiter.describe()}")
        print(f"guards     : {', '.join(caps)}"
              f"{' | skip-idle on' if args.skip_idle else ''}")
    print(f"episodes   : {len(seeds)} — seeds {seeds}")
    print(f"env        : {args.env_url}")
    print()

    if args.probe:
        if not agent.uses_model:
            raise SystemExit("--probe needs a model backend; policy/* makes no calls.")
        obs, _ = env.reset(seeds[0], args.rng_seed)
        user = build_user_prompt(obs, [])
        print("─" * 70)
        print(system_prompt)
        print("─" * 70)
        print(user)
        print("─" * 70)
        action, reasoning = agent.act(obs, [])
        print(f"action    : {action!r}")
        print(f"reasoning : {reasoning}")
        print(f"usage     : {budget.summary()}")
        env.close()
        return 0

    episodes, stopped = [], None
    started = time.time()
    # One run_id for the whole sweep, allocated up front: the record is
    # rewritten after every episode, and re-allocating each time would scatter
    # a single run across ten directories.
    runs_dir = Path(args.runs_dir)
    run_id = run_store.allocate_run_id(args.model, runs_dir) if args.save_run else None

    def checkpoint(reason):
        """Write what has finished so far.

        A sweep is hours long, and its record used to be written only after the
        final episode -- so any failure in between destroyed every completed
        episode along with it. Ten hours of finished work must not depend on
        the eleventh hour succeeding.
        """
        if not (args.save_run and episodes):
            return None
        record = run_store.build_run_record(
            run_id=run_id, args=args, agent_description=agent.describe(),
            system_prompt=system_prompt, manifest=manifest,
            manifest_text=manifest_text, seeds=seeds, episodes=episodes,
            budget=budget, metrics=metric_means(manifest, episodes),
            outcomes=outcome_counts(episodes), health=health_with_rates(episodes),
            wall_time=time.time() - started, model_provenance=agent.provenance(),
            stopped=reason, runs_dir=runs_dir,
        )
        written = run_store.save_run(record, runs_dir)
        run_store.append_to_index(record, written, runs_dir)
        return written

    for index, seed in enumerate(seeds, 1):
        print(f"[{index}/{len(seeds)}] seed {seed!r}")
        try:
            record = run_episode(env, agent, seed, budget, args)
        except KeyboardInterrupt:
            stopped = "interrupted"
            print(f"  interrupted during {seed!r} — keeping the "
                  f"{len(episodes)} episode(s) already finished", file=sys.stderr)
            break
        except Exception as exc:
            # Anything unhandled. The sweep stops the way a tripped guard does:
            # finished episodes intact and the reason recorded, rather than a
            # traceback thrown over four hours of completed work.
            stopped = f"error: {type(exc).__name__}: {exc}"
            print(f"  {seed!r} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            print(f"  keeping the {len(episodes)} episode(s) already finished",
                  file=sys.stderr)
            break
        episodes.append(record)
        score = record["score"] or {}
        print(
            f"    → {score.get('outcome') or record['truncated'] or 'incomplete'} "
            f"on day {score.get('day', '?')} | victory {score.get('victory_progress', 0):.4f} "
            f"| dead {score.get('dead_pct', 0)}% | {budget.summary()}"
        )
        if agent.uses_model:
            print(f"      actions: {action_health([record])[0]}")
        checkpoint(None)
        if record["truncated"]:
            stopped = record["truncated"]
            break

    elapsed = time.time() - started
    print()
    print("=== Run summary ===")
    print(f"agent    : {agent.describe()}")
    print(f"episodes : {len(episodes)} in {elapsed:.0f}s")
    if agent.uses_model and agent.limiter.waited:
        # Distinguishes a slow model from a throttled one: the same wall time
        # means very different things about the two.
        print(f"paced    : {agent.limiter.waited:.0f}s of {elapsed:.0f}s spent "
              f"waiting on the {agent.limiter.describe()} limit")
    if agent.uses_model:
        print(f"usage    : {budget.summary()}")
        health_line, health_warning = action_health(episodes)
        print(f"actions  : {health_line}")
        if health_warning:
            print()
            print(f"  ⚠  {health_warning}")
    if stopped:
        print(f"stopped  : {stopped} — metrics below cover the episodes that finished")
    print()
    rows = aggregate(manifest, episodes)
    width = max(len(name) for name, _ in rows)
    primary = manifest["scoring"]["primary_metric"]
    for name, value in rows:
        mark = " <- primary" if name == primary else ""
        print(f"  {name:<{width}}  {value}{mark}")

    outcomes = outcome_counts(episodes)
    print()
    print("  outcomes: " + ", ".join(f"{k} x{v}" for k, v in outcomes.items()))

    saved = checkpoint(stopped)
    if saved:
        index_path = runs_dir / "index.json"
        print(f"\n  recorded {_display_path(saved)} (+ {_display_path(index_path)})")

    if args.export:
        path = Path(args.export)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The showcase reads `run.config.model` for the label and matches
        # `episodes[].id` against the `replay` keys for the seed and terminal
        # block, exactly as a platform export lays them out. Top-level `seed`
        # takes precedence over the per-episode one in the UI, so it is only
        # set when there is a single episode to describe.
        keyed = [(f"ep{i}-{ep['seed']}", ep) for i, ep in enumerate(episodes, 1)]
        doc = {
            "schema_version": "1",
            "domain_id": manifest["id"],
            "domain_name": manifest["name"],
            "binding_vow_version": manifest["binding_vow"]["version"],
            "visibility": "local",
            "generated_by": f"tools/bench_local.py — {agent.describe()}",
            "run": {"config": {"model": args.model}},
            "episodes": [
                {"id": key, "seed": ep["seed"], "rng_seed": ep["rng_seed"],
                 "action_health": ep["health"], "terminal_info": ep["score"]}
                for key, ep in keyed
            ],
            "replay": {key: ep["turns"] for key, ep in keyed},
        }
        if len(keyed) == 1:
            doc["seed"] = keyed[0][1]["seed"]
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        print(f"\n  exported {path} ({path.stat().st_size / 1024:.0f} KB)")

    env.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
